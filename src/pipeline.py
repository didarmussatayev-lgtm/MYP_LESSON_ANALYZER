"""
Главный CLI-скрипт: запускает весь пайплайн от двух аудиофайлов до готового
Word-отчёта.

Каждый этап сохраняет промежуточный результат в --workdir (по умолчанию
./work/<имя_урока>/), поэтому при сбое (например упал LLM-вызов из-за сети)
можно перезапустить с флагом --resume и не платить заново за транскрипцию.

Пример запуска (см. README для полного разбора):

    python pipeline.py \\
        --teacher-track lesson_teacher.wav \\
        --classroom-track lesson_classroom.wav \\
        --planned-lesson ../examples/example_planned_lesson.yaml \\
        --pptx lesson_slides.pptx \\
        --out report.docx
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

import yaml

import align
import gemini_transcribe as transcribe
import llm_analysis as la
import report
import sync
from common import Segment, Utterance


def _stage_path(workdir: Path, name: str) -> Path:
    return workdir / f"{name}.json"


def _save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_pipeline(
    teacher_track: str,
    classroom_track: str | None,
    planned_lesson_path: str,
    out_path: str,
    pptx_path: str | None = None,
    workdir: str = "./work/lesson",
    resume: bool = False,
    taxonomy_path: str = "../config/taxonomy.yaml",
    template_path: str = "../templates/lesson_report_template.docx",
    on_progress: Callable[[str], None] | None = None,
) -> None:
    def progress(msg: str) -> None:
        print(msg)
        if on_progress:
            on_progress(msg)

    single_track_mode = classroom_track is None

    workdir_p = Path(workdir)
    workdir_p.mkdir(parents=True, exist_ok=True)

    taxonomy = la._load_taxonomy(taxonomy_path)

    with open(planned_lesson_path, encoding="utf-8") as f:
        planned = yaml.safe_load(f)

    # --- Stage 1: sync (только если есть второй трек) ---
    offset_path = _stage_path(workdir_p, "01_offset")
    if single_track_mode:
        offset = 0.0
        progress("Этап 1/7: только трек учителя - синхронизация не нужна, пропускаю.")
    elif resume and offset_path.exists():
        offset = _load_json(offset_path)["offset_seconds"]
        progress(f"[resume] offset = {offset:.2f}s")
    else:
        progress("Этап 1/7: синхронизация двух аудиотреков...")
        offset = sync.find_offset_seconds(teacher_track, classroom_track)
        _save_json(offset_path, {"offset_seconds": offset})
        progress(f"  offset = {offset:.2f}s")

    # --- Stage 2: transcribe (Gemini) ---
    teacher_segs_path = _stage_path(workdir_p, "02_teacher_segments")
    classroom_segs_path = _stage_path(workdir_p, "02_classroom_segments")
    if resume and teacher_segs_path.exists() and (single_track_mode or classroom_segs_path.exists()):
        teacher_segments = [Segment(**s) for s in _load_json(teacher_segs_path)]
        classroom_segments = (
            [] if single_track_mode else [Segment(**s) for s in _load_json(classroom_segs_path)]
        )
        progress("[resume] loaded transcripts")
    else:
        if single_track_mode:
            progress("Этап 2/7: транскрипция трека учителя + попытка различить учитель/ученик по смыслу речи (Gemini)...")
            teacher_segments = transcribe.transcribe_track(teacher_track, identify_speakers=True)
            transcribe.save_segments(teacher_segments, str(teacher_segs_path))
            classroom_segments = []
            progress("Этап 3/7: общего трека нет - пропускаю.")
        else:
            progress("Этап 2/7: транскрипция трека учителя (Gemini)...")
            teacher_segments = transcribe.transcribe_track(teacher_track)
            transcribe.save_segments(teacher_segments, str(teacher_segs_path))

            progress("Этап 3/7: транскрипция общего трека класса (Gemini)...")
            classroom_segments = transcribe.transcribe_track(classroom_track)
            transcribe.save_segments(classroom_segments, str(classroom_segs_path))

    # --- Stage 3: align (Teacher/Student roles) ---
    utterances_path = _stage_path(workdir_p, "03_utterances")
    if resume and utterances_path.exists():
        utterances = [Utterance(**u) for u in _load_json(utterances_path)]
        progress("[resume] loaded aligned utterances")
    elif single_track_mode:
        progress("Этап 4/7: разметка ролей по смысловой подсказке модели (без физического разделения треков)...")
        utterances = align.align_single_track(teacher_segments)
        align.save_utterances(utterances, str(utterances_path))
    else:
        progress("Этап 4/7: слияние треков по таймкодам (без ML-диаризации)...")
        utterances = align.align_tracks(teacher_segments, classroom_segments, classroom_offset_seconds=offset)
        align.save_utterances(utterances, str(utterances_path))

    talk_time = align.talk_time_summary(utterances)
    progress(f"  Talk time: Teacher {talk_time['teacher_pct']}% / Student {talk_time['student_pct']}%")
    if single_track_mode:
        progress(
            "  Внимание: роли Teacher/Student в single-track режиме определены моделью по "
            "смыслу речи (кто ведёт урок vs кто отвечает), а не физическим сравнением двух "
            "треков - точность ниже, особенно при одновременной речи или тихих репликах "
            "учеников. См. методологическую заметку в отчёте."
        )

    # --- Stage 3b (optional): slides ---
    intended_vs_enacted_summary = ""
    if pptx_path:
        import slides as slides_mod

        progress("Этап 4b: сопоставление слайдов с уроком (оценочно)...")
        slide_texts = slides_mod.extract_slide_texts(pptx_path)
        slide_timeline = slides_mod.estimate_slide_timeline(slide_texts, utterances)
        _save_json(_stage_path(workdir_p, "03b_slide_timeline"), slide_timeline)

    # --- Stage 4: LLM analysis ---
    questions_path = _stage_path(workdir_p, "04_questions")
    if resume and questions_path.exists():
        questions = _load_json(questions_path)
        progress("[resume] loaded question classification")
    else:
        progress("Этап 5/7: классификация вопросов учителя (Gemini)...")
        questions = la.classify_questions(utterances, taxonomy)
        _save_json(questions_path, questions)
        progress(f"  {len(questions)} questions classified")

    inquiry_path = _stage_path(workdir_p, "05_inquiry_levels")
    if resume and inquiry_path.exists():
        inquiry_episodes = _load_json(inquiry_path)
        progress("[resume] loaded inquiry-level episodes")
    else:
        progress("Этап 6/7: классификация inquiry-level по эпизодам (Gemini)...")
        inquiry_episodes = la.classify_inquiry_levels(utterances, taxonomy)
        _save_json(inquiry_path, inquiry_episodes)
        progress(f"  {len(inquiry_episodes)} episodes classified")

    alignment_path = _stage_path(workdir_p, "06_alignment")
    if resume and alignment_path.exists():
        alignment_rows = _load_json(alignment_path)
        progress("[resume] loaded planned-vs-observed alignment")
    else:
        progress("Этап 7/7: сравнение planned vs observed (Gemini)...")
        alignment_rows = la.planned_vs_observed(planned, utterances, taxonomy)
        _save_json(alignment_path, alignment_rows)

    reflection_path = _stage_path(workdir_p, "07_reflection")
    if resume and reflection_path.exists():
        reflection = _load_json(reflection_path)
        progress("[resume] loaded reflection synthesis")
    else:
        progress("Синтез AI-assisted рефлексии (Gemini)...")
        reflection = la.synthesize_reflection(talk_time, questions, inquiry_episodes, alignment_rows)
        _save_json(reflection_path, reflection)

    # --- Final: render docx ---
    progress("Генерация Word-отчёта...")
    ctx = report.build_context(
        teacher_name=planned.get("teacher_name", ""),
        subject=planned.get("subject", ""),
        lesson_date=planned.get("lesson_date", ""),
        talk_time=talk_time,
        questions=questions,
        inquiry_episodes=inquiry_episodes,
        alignment_rows=alignment_rows,
        reflection=reflection,
        intended_vs_enacted_summary=intended_vs_enacted_summary,
        single_track_mode=single_track_mode,
    )
    report.render_report(ctx, template_path, out_path)
    progress(f"Готово. Отчёт сохранён: {out_path}")
    progress("Напоминание: это AI-assisted ЧЕРНОВИК. Проверьте перед тем, как делиться с учителем/коучем.")


def main() -> None:
    parser = argparse.ArgumentParser(description="MYP AI-assisted lesson observation pipeline")
    parser.add_argument("--teacher-track", required=True, help="Path to lapel mic audio (teacher)")
    parser.add_argument("--classroom-track", default=None, help="Path to classroom phone audio (опционально - без него анализ идёт только по треку учителя)")
    parser.add_argument("--planned-lesson", required=True, help="Path to planned lesson YAML")
    parser.add_argument("--pptx", default=None, help="Optional path to teacher's slides (pptx)")
    parser.add_argument("--out", default="report.docx", help="Output docx path")
    parser.add_argument("--workdir", default="./work/lesson", help="Directory for intermediate stage files")
    parser.add_argument("--resume", action="store_true", help="Reuse completed stage files in --workdir")
    parser.add_argument("--taxonomy", default="../config/taxonomy.yaml", help="Path to taxonomy.yaml")
    parser.add_argument("--template", default="../templates/lesson_report_template.docx", help="Path to docx template")
    args = parser.parse_args()

    run_pipeline(
        teacher_track=args.teacher_track,
        classroom_track=args.classroom_track,
        planned_lesson_path=args.planned_lesson,
        out_path=args.out,
        pptx_path=args.pptx,
        workdir=args.workdir,
        resume=args.resume,
        taxonomy_path=args.taxonomy,
        template_path=args.template,
    )


if __name__ == "__main__":
    main()
