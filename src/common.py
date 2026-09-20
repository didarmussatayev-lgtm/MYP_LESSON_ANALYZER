"""Общие структуры данных, используемые несколькими модулями пайплайна."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    """Один сегмент ASR-транскрипта одного трека (до слияния ролей)."""

    start: float
    end: float
    text: str
    # Заполняется только в single-track режиме (см. gemini_transcribe.py,
    # identify_speakers=True) - предположение модели "teacher"/"student" по
    # содержанию и тону речи внутри одного файла, а не акустический анализ
    # голоса. В two-track режиме остаётся None - там роль определяется
    # надёжнее, через физическое сравнение двух треков (align.py).
    speaker_hint: str | None = None


@dataclass
class Utterance:
    """Одна реплика в объединённой ленте урока (после align.py)."""

    start: float
    end: float
    speaker: str  # "Teacher" | "Student"
    text: str
    source: str  # "lapel" | "classroom"
