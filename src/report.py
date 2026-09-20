"""
Финальный шаг пайплайна: заполнение Word-шаблона (templates/lesson_report_template.docx)
данными через docxtpl.

Вся "сборка" контекста (человекочитаемые лейблы вместо кодов level_1/level_2/level_4,
таймкоды MM:SS вместо секунд и т.п.) происходит здесь, а не в llm_analysis.py -
LLM-модуль должен отдавать сырые структурированные данные, а форматирование под
конкретный документ - отдельная забота.
"""

from __future__ import annotations

from docxtpl import DocxTemplate

from common import Utterance

LEVEL_LABELS = {
    "level_1": "Level 1 — Teacher asks / student answers",
    "level_2": "Level 2 — Teacher gives question / student investigates",
    "level_4": "Level 4 — Student formulates / investigates / evaluates / reflects",
}

FIELD_LABELS = {
    "key_concept": "Key Concept",
    "related_concept": "Related Concept(s)",
    "global_context": "Global Context",
    "statement_of_inquiry": "Statement of Inquiry",
    "inquiry_questions": "Inquiry Questions",
    "learning_objectives": "Learning Objectives",
    "atl_skills": "ATL Skills",
    "learner_profile": "Learner Profile",
    "assessment_criteria": "Assessment Criteria",
    "learning_experiences": "Learning Experiences",
}


def _sec_to_mmss(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _question_distribution_summary(questions: list[dict]) -> str:
    if not questions:
        return "No questions detected."
    counts: dict[str, int] = {}
    for q in questions:
        counts[q.get("category", "unknown")] = counts.get(q.get("category", "unknown"), 0) + 1
    total = sum(counts.values())
    parts = [f"{cat}: {n} ({round(100 * n / total)}%)" for cat, n in counts.items()]
    return ", ".join(parts)


def build_context(
    teacher_name: str,
    subject: str,
    lesson_date: str,
    talk_time: dict,
    questions: list[dict],
    inquiry_episodes: list[dict],
    alignment_rows: list[dict],
    reflection: dict,
    intended_vs_enacted_summary: str = "",
    methodology_notes: str | None = None,
    single_track_mode: bool = False,
) -> dict:
    """Собирает единый context-словарь под docxtpl из результатов всех модулей."""

    alignment_rows_fmt = [
        {
            "field_label": FIELD_LABELS.get(row.get("field", ""), row.get("field", "")),
            "planned": row.get("planned", ""),
            "observed_evidence": row.get("observed_evidence") or "(no evidence found)",
            "alignment": row.get("alignment", ""),
        }
        for row in alignment_rows
    ]

    inquiry_episodes_fmt = [
        {
            "start_timestamp": ep.get("start_timestamp", ""),
            "end_timestamp": ep.get("end_timestamp", ""),
            "level_label": LEVEL_LABELS.get(ep.get("level", ""), ep.get("level", "")),
            "rationale": ep.get("rationale", ""),
            "evidence_quote": ep.get("evidence_quote", ""),
        }
        for ep in inquiry_episodes
    ]

    if methodology_notes is None:
        methodology_notes = (
            "Speaker roles (Teacher/Student) are derived from timestamp alignment between "
            "two independently transcribed audio tracks, not from voice-based diarization. "
            "Overlapping speech (teacher talking over a student) may be misclassified. "
            "Slide-to-timestamp mapping (if used) is a text-similarity estimate, not an exact "
            "match. All AI classifications (question category, inquiry level, alignment rating) "
            "should be reviewed by the teacher before being used for coaching conversations."
        )
        if single_track_mode:
            methodology_notes += (
                " IMPORTANT: this report was generated from the TEACHER'S TRACK ONLY (no "
                "separate classroom-mic track was provided). Speaker roles (Teacher/Student) "
                "were guessed by the AI from the content and tone of speech within this single "
                "track (who leads the lesson vs who gives short answers), not from a physical "
                "comparison of two independent recordings - this is a semantic heuristic, not "
                "voice/acoustic identification, and is meaningfully less reliable than two-track "
                "mode, especially for overlapping speech, quiet student voices, or short replies "
                "with ambiguous context. Treat talk-time, question attribution, and inquiry-level "
                "in this report as lower-confidence than a two-track report."
            )

    return {
        "teacher_name": teacher_name,
        "subject": subject,
        "lesson_date": lesson_date,
        "talk_time": talk_time,
        "alignment_rows": alignment_rows_fmt,
        "questions": questions,
        "question_distribution_summary": _question_distribution_summary(questions),
        "intended_vs_enacted_summary": intended_vs_enacted_summary,
        "inquiry_episodes": inquiry_episodes_fmt,
        "strengths": reflection.get("strengths", []),
        "areas_for_development": reflection.get("areas_for_development", []),
        "suggested_next_lesson_strategy": reflection.get("suggested_next_lesson_strategy", ""),
        "methodology_notes": methodology_notes,
    }


def render_report(context: dict, template_path: str, out_path: str) -> None:
    tpl = DocxTemplate(template_path)
    tpl.render(context)
    tpl.save(out_path)
    print(f"Report saved to {out_path}")
