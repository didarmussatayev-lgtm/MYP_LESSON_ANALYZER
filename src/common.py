"""Общие структуры данных, используемые несколькими модулями пайплайна."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    """Один сегмент ASR-транскрипта одного трека (до слияния ролей)."""

    start: float
    end: float
    text: str


@dataclass
class Utterance:
    """Одна реплика в объединённой ленте урока (после align.py)."""

    start: float
    end: float
    speaker: str  # "Teacher" | "Student"
    text: str
    source: str  # "lapel" | "classroom"
