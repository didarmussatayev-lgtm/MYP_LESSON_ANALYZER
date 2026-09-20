"""
Транскрипция аудио через Gemini API (мультимодальный ввод audio -> text)
вместо локального Whisper.

Почему так: сервер перестаёт тянуть тяжёлую ML-модель и GPU/CPU-нагрузку -
вся транскрипция происходит на стороне Google, платится по факту
использования (~$0.12 за 80 минут аудио на Gemini 2.5 Flash на момент
написания - см. README, раздел "Стоимость", цены нужно перепроверять).

ВАЖНО про приватность (см. README): используйте ПЛАТНЫЙ API-ключ, а не
бесплатный ключ из Google AI Studio. На бесплатном тарифе Google может
использовать переданные данные для улучшения своих моделей - это
неприемлемо для аудиозаписей с голосами несовершеннолетних учеников.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
import re
import shutil
import tempfile

from google import genai
from google.genai import types

from common import Segment

# python:3.11-slim (образ, используемый в Dockerfile) не содержит системный
# /etc/mime.types (пакет mime-support туда не входит), поэтому встроенное
# в Python угадывание MIME-типа по расширению файла ненадёжно и может
# вернуть None даже для обычных аудиоформатов вроде .m4a - тогда Gemini
# Files API падает с "Unknown mime type". Прописываем типы явно, без
# зависимости от системных файлов окружения.
_AUDIO_MIME_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".opus": "audio/opus",
}


def _guess_audio_mime_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime_type = _AUDIO_MIME_TYPES.get(ext)
    if mime_type is None:
        raise ValueError(
            f"Не удалось определить MIME-тип для файла '{path}' (расширение '{ext}'). "
            f"Поддерживаемые форматы: {', '.join(_AUDIO_MIME_TYPES)}. "
            "Если формат другой - добавьте его в _AUDIO_MIME_TYPES в gemini_transcribe.py."
        )
    return mime_type

# Проверьте актуальное имя модели в консоли Google AI перед первым запуском -
# модели обновляются часто (gemini-2.5-flash уже выведена из доступа для
# новых проектов на момент этой правки, сентябрь 2026). gemini-3.6-flash -
# актуальный Flash-уровень с адекватной ценой на этот момент.
MODEL = "gemini-3.6-flash"

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY не задан. См. README, раздел 'Настройка API-ключа'."
            )
        _client = genai.Client(api_key=api_key)
    return _client


TRANSCRIBE_PROMPT = """Ты — ассистент для транскрипции аудиозаписи школьного урока.
Транскрибируй речь на записи ПОЛНОСТЬЮ, разбив на короткие смысловые сегменты
(отдельные реплики/фразы, обычно 2-15 секунд каждая).

Верни ТОЛЬКО валидный JSON-массив, без markdown, без пояснений вне JSON.
Каждый элемент массива должен иметь такую форму:
{"start_sec": <число секунд от начала файла>, "end_sec": <число секунд от начала файла>, "text": "точный текст реплики"}

Правила:
- Таймкоды - числа с плавающей точкой в секундах от начала ЭТОГО аудиофайла (не MM:SS, не строка).
- Сохраняй исходный язык речи как есть (может быть русский, казахский, английский вперемешку) - не переводи.
- Не пропускай короткие реплики и междометия, если они разборчивы.
- Если фрагмент неразборчив - пропусти его, не выдумывай текст.
"""

# Используется, когда есть только ОДИН трек (обычно петличка учителя, но на
# ней слышны и голоса учеников). Просим модель дополнительно предположить
# роль говорящего по содержанию и тону речи - это НЕ акустическая
# диаризация (Gemini не анализирует тембр голоса отдельно), а смысловая
# эвристика: кто ведёт урок/задаёт вопросы (учитель) и кто отвечает
# короткими репликами (ученики). Точность ниже, чем при физическом
# разделении по двум трекам - см. предупреждение в report.py.
TRANSCRIBE_WITH_SPEAKER_HINT_PROMPT = """Ты — ассистент для транскрипции аудиозаписи школьного урока.
Запись сделана на один микрофон (обычно петличка учителя), поэтому на ней
слышен и учитель, и ученики. Транскрибируй речь ПОЛНОСТЬЮ, разбив на короткие
смысловые сегменты (2-15 секунд), и для каждого сегмента предположи, кто
говорит: учитель или ученик.

Ориентируйся на роль в диалоге, а не на громкость: учитель обычно ведёт урок,
задаёт вопросы, даёт инструкции, говорит развёрнуто и связно. Ученики обычно
отвечают, часто короче, реже инициируют тему.

Верни ТОЛЬКО валидный JSON-массив, без markdown, без пояснений вне JSON.
Каждый элемент массива должен иметь такую форму:
{"start_sec": <число>, "end_sec": <число>, "text": "точный текст реплики", "speaker_role": "teacher" | "student"}

Правила:
- Таймкоды - числа с плавающей точкой в секундах от начала ЭТОГО аудиофайла.
- Сохраняй исходный язык речи как есть - не переводи.
- Если не уверены, кто говорит - ставьте наиболее вероятный вариант по контексту, не пропускайте поле.
- Если фрагмент неразборчив - пропусти его, не выдумывай текст.
"""


def _clean_json_text(text: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()


def transcribe_track(audio_path: str, identify_speakers: bool = False) -> list[Segment]:
    """
    Загружает аудиофайл через Gemini Files API (работает для файлов любого
    разумного размера, в т.ч. > 20MB, что типично для 40-минутного трека)
    и просит модель вернуть JSON-транскрипт с таймкодами в секундах.

    identify_speakers=True - используется в single-track режиме (нет
    отдельного трека класса): модель дополнительно пытается угадать
    teacher/student по содержанию речи (см. TRANSCRIBE_WITH_SPEAKER_HINT_PROMPT).
    В обычном two-track режиме не нужно - там роль определяется надёжнее,
    через align.py.
    """
    client = _get_client()

    mime_type = _guess_audio_mime_type(audio_path)

    # Gemini SDK передаёт имя файла в HTTP-заголовке запроса на загрузку, а
    # HTTP-заголовки должны быть ASCII/latin-1. Имена файлов с кириллицей
    # (типично для записей с телефона - названия улиц, папок и т.п.) ломают
    # запрос ещё до отправки в Google (UnicodeEncodeError на стороне httpx).
    # Поэтому перед загрузкой всегда копируем файл во временный с безопасным
    # ASCII-именем - вне зависимости от того, как называется исходный файл.
    ext = os.path.splitext(audio_path)[1]
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        safe_path = tmp.name
    shutil.copyfile(audio_path, safe_path)

    try:
        uploaded_file = client.files.upload(
            file=safe_path,
            config=types.UploadFileConfig(mime_type=mime_type),
        )
    finally:
        os.remove(safe_path)

    prompt = TRANSCRIBE_WITH_SPEAKER_HINT_PROMPT if identify_speakers else TRANSCRIBE_PROMPT

    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt, uploaded_file],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    raw_text = response.text or ""
    cleaned = _clean_json_text(raw_text)

    try:
        raw_segments = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini вернул не-JSON ответ при транскрипции {audio_path}:\n{raw_text[:2000]}"
        ) from e

    segments = [
        Segment(
            start=float(s["start_sec"]),
            end=float(s["end_sec"]),
            text=s["text"].strip(),
            speaker_hint=s.get("speaker_role"),  # None если identify_speakers=False - поля нет в ответе
        )
        for s in raw_segments
        if s.get("text", "").strip()
    ]
    print(f"[{audio_path}] Gemini transcription: {len(segments)} segments")
    return segments


def save_segments(segments: list[Segment], out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in segments], f, ensure_ascii=False, indent=2)


def load_segments(path: str) -> list[Segment]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [Segment(**r) for r in raw]


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python gemini_transcribe.py <audio_path> <out_json>")
        sys.exit(1)

    segs = transcribe_track(sys.argv[1])
    save_segments(segs, sys.argv[2])
    print(f"Saved {len(segs)} segments to {sys.argv[2]}")
