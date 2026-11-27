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

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Длинные записи режутся на куски.
#
# Почему: ответ модели ограничен по длине, а расшифровка 80-минутного урока
# одним ответом к нему приближается (обрыв = невалидный JSON = ошибка всего
# анализа). Кроме того, на длинном аудио Gemini хуже держит таймкоды к концу
# записи. Куски по ~10 минут решают обе проблемы, расшифровываются
# параллельно и кэшируются по отдельности: при повторном запуске заново
# идут только те куски, которые не получились.
#
# Как склеиваются: каждый кусок захватывает OVERLAP_SEC аудио с обеих
# сторон от своей «номинальной» границы. Из куска i берутся только реплики,
# начавшиеся в его номинальном интервале [i*CHUNK, (i+1)*CHUNK) — так фраза
# на стыке попадает в расшифровку ровно один раз и целиком.
# ---------------------------------------------------------------------------

CHUNK_SEC = int(os.environ.get("TRANSCRIBE_CHUNK_SEC", "600"))
OVERLAP_SEC = 15
PARALLEL = int(os.environ.get("TRANSCRIBE_PARALLEL", "4"))
MAX_ATTEMPTS = 3


def _duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def _plan_chunks(total: float) -> list[tuple[int, float, float, float, float]]:
    """[(index, nominal_start, nominal_end, audio_start, audio_end)]"""
    chunks = []
    i, start = 0, 0.0
    while start < total:
        end = min(total, start + CHUNK_SEC)
        # хвост короче минуты присоединяем к предыдущему куску
        if total - end < 60:
            end = total
        chunks.append((i, start, end, max(0.0, start - OVERLAP_SEC), min(total, end + OVERLAP_SEC)))
        i, start = i + 1, end
    return chunks


def _cut(src: str, start: float, length: float, dest: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
         "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", dest],
        check=True, capture_output=True,
    )


def _transcribe_file(path: str, prompt: str) -> list[dict]:
    """Один запрос к Gemini для одного файла; повторяет при сбоях и обрыве JSON."""
    client = _get_client()
    mime_type = _guess_audio_mime_type(path)

    # Gemini SDK передаёт имя файла в HTTP-заголовке, а заголовки должны быть
    # ASCII: имена с кириллицей (типично для записей с телефона) ломают запрос.
    # Поэтому загружаем копию с безопасным именем.
    ext = os.path.splitext(path)[1]
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        safe_path = tmp.name
    shutil.copyfile(path, safe_path)

    last_error: Exception | None = None
    try:
        uploaded = client.files.upload(file=safe_path, config=types.UploadFileConfig(mime_type=mime_type))
    finally:
        os.remove(safe_path)
    try:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=[prompt, uploaded],
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                raw = json.loads(_clean_json_text(response.text or ""))
                if not isinstance(raw, list):
                    raise ValueError("ожидался JSON-массив")
                return raw
            except Exception as e:  # noqa: BLE001 - сеть, 429/5xx, обрыв JSON
                last_error = e
                time.sleep(3 * (attempt + 1) ** 2)
        raise ValueError(f"Gemini не вернул корректную расшифровку после {MAX_ATTEMPTS} попыток: {last_error}")
    finally:
        # Аудио с голосами детей не храним у Google дольше необходимого
        # (сами файлы и так удаляются через 48 часов).
        try:
            client.files.delete(name=uploaded.name)
        except Exception:  # noqa: BLE001
            pass


def _to_segments(raw: list[dict], offset: float, keep_from: float, keep_to: float, limit: float) -> list[Segment]:
    out = []
    for s in raw:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        try:
            start = float(s["start_sec"]) + offset
            end = float(s["end_sec"]) + offset
        except (KeyError, TypeError, ValueError):
            continue
        if end < start:
            end = start
        if not (keep_from <= start < keep_to):
            continue
        out.append(Segment(start=round(start, 2), end=round(min(end, limit), 2), text=text,
                           speaker_hint=s.get("speaker_role")))
    return out


def transcribe_track(
    audio_path: str,
    identify_speakers: bool = False,
    language_hint: str | None = None,
    cache_dir: str | None = None,
    on_progress=None,
) -> list[Segment]:
    """
    Расшифровывает запись через Gemini. Короткие записи — одним запросом,
    длинные — кусками по CHUNK_SEC секунд параллельно (см. комментарий выше).

    cache_dir — папка для промежуточных результатов по кускам (resume).
    on_progress(msg) — сообщения о ходе работы для журнала урока.
    """
    prompt = TRANSCRIBE_WITH_SPEAKER_HINT_PROMPT if identify_speakers else TRANSCRIBE_PROMPT
    if language_hint:
        prompt += (
            f"- Основной язык урока: {language_hint}. Реплики на других языках "
            "записывай на том языке, на котором они прозвучали, не переводи.\n"
        )

    total = _duration(audio_path)
    chunks = _plan_chunks(total)
    if len(chunks) == 1:
        segments = _to_segments(_transcribe_file(audio_path, prompt), 0.0, 0.0, float("inf"), total)
        print(f"[{audio_path}] Gemini transcription: {len(segments)} segments")
        return segments

    work = Path(cache_dir) if cache_dir else Path(tempfile.mkdtemp(prefix="chunks_"))
    work.mkdir(parents=True, exist_ok=True)
    say = on_progress or print
    say(f"  Запись {total / 60:.0f} мин — расшифровка {len(chunks)} частями по {CHUNK_SEC // 60} мин")

    def run(chunk) -> list[Segment]:
        i, n_start, n_end, a_start, a_end = chunk
        cache = work / f"chunk_{i:03d}.json"
        if cache.exists():
            raw = json.loads(cache.read_text(encoding="utf-8"))
        else:
            part = work / f"chunk_{i:03d}.mp3"
            _cut(audio_path, a_start, a_end - a_start, str(part))
            try:
                raw = _transcribe_file(str(part), prompt)
            finally:
                part.unlink(missing_ok=True)
            cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        # первый кусок забирает всё до своей границы, последний — всё после
        keep_from = 0.0 if i == 0 else n_start
        keep_to = float("inf") if i == len(chunks) - 1 else n_end
        return _to_segments(raw, a_start, keep_from, keep_to, total)

    results: dict[int, list[Segment]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, PARALLEL)) as pool:
        futures = {pool.submit(run, c): c[0] for c in chunks}
        for done, fut in enumerate(as_completed(futures), 1):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
                say(f"  Расшифрована часть {done} из {len(chunks)}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"часть {idx + 1}: {e}")
    if errors:
        # Удачные части уже в кэше: повторный запуск расшифрует только эти.
        raise ValueError("Не удалось расшифровать " + "; ".join(errors))

    segments = [s for i in sorted(results) for s in results[i]]
    segments.sort(key=lambda s: s.start)
    print(f"[{audio_path}] Gemini transcription: {len(segments)} segments from {len(chunks)} chunks")
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
