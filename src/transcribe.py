"""
Транскрипция аудио через faster-whisper (открытая модель, бесплатна,
работает локально на CPU или GPU - см. README про выбор размера модели).

Без ML-диаризации: каждый трек транскрибируется независимо и просто
отдаёт список сегментов с таймкодами. Роли (Teacher/Student) назначаются
позже в align.py через сопоставление таймкодов между двумя треками -
см. обсуждение в чате, почему это осознанное упрощение вместо
pyannote-диаризации.
"""

from __future__ import annotations

from dataclasses import asdict
import json

from faster_whisper import WhisperModel

from common import Segment


def transcribe_track(
    audio_path: str,
    model_size: str = "medium",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
) -> list[Segment]:
    """
    model_size: "small" - быстрее, ниже точность; "medium" - разумный
    компромисс для CPU; "large-v3" - лучшая точность, требует GPU для
    приемлемой скорости на 40-минутном уроке.

    language: None = автоопределение. Если урок билингвальный
    (рус/каз/eng вперемешку), лучше не фиксировать язык жёстко -
    Whisper справляется с переключением языка внутри аудио неидеально,
    но с автоопределением обычно лучше, чем с жёстко заданным одним языком.
    Для казахского - см. предупреждение в README про точность.
    """
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=True,  # отсекает длинные паузы/тишину - ускоряет и чистит
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments = [
        Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
        for s in segments_iter
        if s.text.strip()
    ]

    print(
        f"[{audio_path}] detected language={info.language} "
        f"(p={info.language_probability:.2f}), segments={len(segments)}"
    )
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

    if len(sys.argv) < 3:
        print("Usage: python transcribe.py <audio_path> <out_json> [model_size]")
        sys.exit(1)

    audio_path, out_json = sys.argv[1], sys.argv[2]
    model_size = sys.argv[3] if len(sys.argv) > 3 else "medium"

    segs = transcribe_track(audio_path, model_size=model_size)
    save_segments(segs, out_json)
    print(f"Saved {len(segs)} segments to {out_json}")
