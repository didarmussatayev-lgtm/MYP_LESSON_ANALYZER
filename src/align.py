"""
Объединение транскриптов петличного и классного треков в единую ленту
реплик с ролями (Teacher / Student) - БЕЗ голосовой диаризации.

Логика (см. обсуждение в чате):
1. Все сегменты петличного трека -> Teacher (петличка почти всегда = только
   учитель, шум минимален).
2. Сегменты классного трека сравниваются по времени с сегментами учителя:
   - если сегмент классного трека существенно перекрывается по времени
     с репликой учителя (петличка) -> это, скорее всего, тот же голос
     учителя, пойманный телефоном (эхо/bleed-through) -> отбрасываем как
     дубликат, текст берём из петличного трека (он чище).
   - если перекрытия нет -> помечаем как Student.

Ограничение, которое нужно держать в голове (см. чат): при одновременной
речи учителя и ученика (overlap) весь сегмент классного трека может быть
ошибочно списан в Teacher-дубликат. Для MVP это приемлемый компромисс;
v2-fallback - точечная проверка спорных сегментов через голосовой эмбеддинг
(resemblyzer), если такие ошибки станут заметны на реальных данных.
"""

from __future__ import annotations

import json

from common import Segment, Utterance


def _overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Доля пересечения интервала A с интервалом B относительно длины A."""
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    a_len = max(a_end - a_start, 1e-6)
    return inter / a_len


def align_tracks(
    teacher_segments: list[Segment],
    classroom_segments: list[Segment],
    classroom_offset_seconds: float = 0.0,
    overlap_threshold: float = 0.4,
) -> list[Utterance]:
    """
    classroom_offset_seconds - результат sync.find_offset_seconds(); прибавляется
    к таймкодам классного трека, чтобы привести оба трека к общей временной шкале.

    overlap_threshold - если доля пересечения сегмента классного трека с любым
    сегментом учителя >= порога, сегмент считается дубликатом-эхо и отбрасывается.
    0.4 - стартовое значение, имеет смысл откалибровать на реальных записях
    (см. README, раздел "калибровка").
    """
    utterances: list[Utterance] = []

    for seg in teacher_segments:
        utterances.append(
            Utterance(start=seg.start, end=seg.end, speaker="Teacher", text=seg.text, source="lapel")
        )

    for seg in classroom_segments:
        c_start = seg.start + classroom_offset_seconds
        c_end = seg.end + classroom_offset_seconds

        best_overlap = max(
            (_overlap_ratio(c_start, c_end, t.start, t.end) for t in teacher_segments),
            default=0.0,
        )

        if best_overlap >= overlap_threshold:
            continue  # вероятный дубликат учителя - пропускаем

        utterances.append(
            Utterance(start=c_start, end=c_end, speaker="Student", text=seg.text, source="classroom")
        )

    utterances.sort(key=lambda u: u.start)
    return utterances


def align_single_track(segments: list[Segment]) -> list[Utterance]:
    """
    Используется, когда есть только ОДИН аудиотрек (см. чат: петличка, на
    которой слышны и ученики). В отличие от align_tracks(), здесь нет
    физического способа отличить учителя от учеников (нет второго трека для
    сравнения по времени) - роль берётся из Segment.speaker_hint, который
    Gemini проставляет по смыслу речи при identify_speakers=True (см.
    gemini_transcribe.py). Это смысловая эвристика модели, не акустический
    анализ голоса - заметно менее надёжно, чем align_tracks().

    Сегменты без speaker_hint (например, если вызвали без identify_speakers)
    по умолчанию считаются Teacher - тот же fallback, что и раньше, но
    теперь как явный запасной вариант, а не единственная логика.
    """
    utterances = [
        Utterance(
            start=seg.start,
            end=seg.end,
            speaker="Student" if seg.speaker_hint == "student" else "Teacher",
            text=seg.text,
            source="lapel",
        )
        for seg in segments
    ]
    utterances.sort(key=lambda u: u.start)
    return utterances


def talk_time_summary(utterances: list[Utterance]) -> dict:
    teacher_time = sum(u.end - u.start for u in utterances if u.speaker == "Teacher")
    student_time = sum(u.end - u.start for u in utterances if u.speaker == "Student")
    total = teacher_time + student_time or 1e-6

    teacher_count = sum(1 for u in utterances if u.speaker == "Teacher")
    student_count = sum(1 for u in utterances if u.speaker == "Student")

    return {
        "teacher_seconds": round(teacher_time, 1),
        "student_seconds": round(student_time, 1),
        "teacher_pct": round(100 * teacher_time / total, 1),
        "student_pct": round(100 * student_time / total, 1),
        "teacher_utterance_count": teacher_count,
        "student_utterance_count": student_count,
        "avg_teacher_utterance_len_sec": round(teacher_time / max(teacher_count, 1), 2),
        "avg_student_utterance_len_sec": round(student_time / max(student_count, 1), 2),
    }


def save_utterances(utterances: list[Utterance], out_path: str) -> None:
    from dataclasses import asdict

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([asdict(u) for u in utterances], f, ensure_ascii=False, indent=2)


def load_utterances(path: str) -> list[Utterance]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [Utterance(**r) for r in raw]


if __name__ == "__main__":
    # Быстрая самопроверка на синтетических данных - без аудио и без сети.
    teacher = [
        Segment(0.0, 3.0, "Кто помнит, что такое фотосинтез?"),
        Segment(10.0, 14.0, "Хорошо, а теперь сравните это с процессом дыхания клетки."),
        Segment(30.0, 31.5, "Угу"),  # реплика-эхо, должна перекрыться с классным треком
    ]
    classroom = [
        Segment(0.2, 2.8, "Кто помнит что такое фотосинтез"),  # дубликат учителя -> отбросить
        Segment(4.0, 7.0, "Это процесс превращения света в энергию растением"),  # ученик
        Segment(29.8, 31.6, "угу"),  # дубликат учителя -> отбросить
        Segment(32.0, 36.0, "Я думаю разница в том что дыхание идёт и днём и ночью"),  # ученик
    ]

    result = align_tracks(teacher, classroom, classroom_offset_seconds=0.0)
    for u in result:
        print(f"[{u.start:5.1f}-{u.end:5.1f}] {u.speaker:8s} ({u.source:9s}): {u.text}")

    print()
    print(talk_time_summary(result))
