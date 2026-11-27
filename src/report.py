"""
Word-отчёт: заполнение templates/lesson_report_template.docx через docxtpl.

Отчёт строится из сохранённых результатов анализа (pipeline.build_results),
сведений об уроке и комментариев. Веб-приложение рендерит его заново при
каждом скачивании, поэтому в файле всегда актуальное обсуждение, а правки
шаблона применяются и к старым урокам.

Все тексты в контексте экранируются (autoescape), многострочные поля
передаются как Listing — переносы строк сохраняются.
"""

from __future__ import annotations

import io
import os
from datetime import datetime

from docxtpl import DocxTemplate, Listing

from metrics import lesson_metrics, ts_seconds

LEVEL_LABELS = {
    "level_1": "Level 1 — Teacher asks / student answers",
    "level_2": "Level 2 — Teacher gives question / student investigates",
    "level_3": "Level 3",
    "level_4": "Level 4 — Student formulates / investigates / evaluates / reflects",
}
LEVEL_SHORT = {"level_1": "Level 1", "level_2": "Level 2", "level_3": "Level 3", "level_4": "Level 4"}

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

CATEGORY_LABELS = {
    "recall": "Recall",
    "understanding": "Understanding",
    "application": "Application",
    "analysis": "Analysis",
}
OPPORTUNITY_LABELS = {
    "Strong": "Students worked on it",
    "Partial": "Touched on",
    "Not observed": "Not observed",
    "Not observable": "Not observable from audio",
}
AUDIO_SUFFIX = {"full": "", "partial": " (partially observable from audio)", "none": " (not observable from audio)"}
ROLE_LABELS = {"teacher": "Teacher", "observer": "Coordinator", "admin": "Administrator"}
SECTION_LABELS = {
    "summary": "Summary", "plan": "Planned vs observed", "criteria": "Assessment criteria",
    "questions": "Questions", "inquiry": "Inquiry", "transcript": "Transcript",
}
LANGUAGE_LABELS = {"ru": "Russian", "kk": "Kazakh", "en": "English", "mixed": "Mixed"}


def _sec_to_mmss(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _duration(seconds) -> str:
    if not seconds:
        return "—"
    seconds = int(round(seconds))
    h, m = divmod(seconds // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Almaty"))
    except Exception:  # noqa: BLE001 - нет tzdata или неверное имя пояса
        return None


def format_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, _tz()).strftime("%d.%m.%Y %H:%M")


def _date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return value or "—"


def _text(value) -> Listing:
    return Listing(str(value or ""))


def methodology_notes(single_track_mode: bool = False, audio_observability_note: str | None = None) -> str:
    notes = (
        "Speaker roles (Teacher/Student) are derived from timestamp alignment between "
        "two independently transcribed audio tracks, not from voice-based diarization. "
        "Overlapping speech (teacher talking over a student) may be misclassified. "
        "Slide-to-timestamp mapping (if used) is a text-similarity estimate, not an exact "
        "match. Student talk-time includes silence not covered by either speaker's speech, "
        "attributed to independent/group work - this is an ASSUMPTION, not a measurement; "
        "see the measured student speech row for the actually-measured student speech "
        "duration alone. All AI classifications (question category, inquiry level, "
        "alignment rating) should be reviewed by the teacher before being used for "
        "coaching conversations."
    )
    if single_track_mode:
        notes += (
            " IMPORTANT: this report was generated from the TEACHER'S TRACK ONLY (no "
            "separate classroom-mic track was provided). Speaker roles (Teacher/Student) "
            "were inferred by the AI from the content and tone of speech within this single "
            "track, not from a physical comparison of two independent recordings - this is "
            "meaningfully less reliable than two-track mode, especially for overlapping speech, "
            "quiet student voices, or short replies. Treat talk-time, question attribution, and "
            "inquiry-level in this report as lower-confidence than a two-track report."
        )
    if audio_observability_note:
        notes += " SUBJECT-SPECIFIC LIMITATION: " + audio_observability_note.strip()
    return notes


def _quality_note(results: dict) -> str:
    q = results.get("transcript_quality") or {}
    dropped = sum((t or {}).get("dropped_silent_segments", 0) for t in (q.get("teacher"), q.get("classroom")))
    if not dropped:
        return ""
    return (f" TRANSCRIPT CHECK: {dropped} transcribed segment(s) were removed because the recording is "
            "silent at that point — speech-recognition models occasionally invent text over quiet or unclear "
            "audio. Review the transcript before relying on quotes in this report.")


def build_context(results: dict, meta: dict | None = None, comments: list[dict] | None = None,
                  subject_group: str = "") -> dict:
    """
    results  — сохранённые результаты (pipeline.build_results);
    meta     — сведения об уроке: teacher_name, subject, lesson_date, lesson_title,
               grade, lesson_language (код ru/kk/en/mixed);
    comments — комментарии из обсуждения (db.list_comments).
    """
    meta = meta or {}
    planned = results.get("planned") or {}
    tt = results.get("talk_time") or {}
    questions = results.get("questions") or []
    m = lesson_metrics(results)

    def pct(v):
        return "—" if v is None else f"{round(v)}%"

    # --- ключевые показатели
    align_rows = results.get("alignment_rows") or []
    strong = sum(1 for r in align_rows if r.get("alignment") == "Strong")
    partial = sum(1 for r in align_rows if r.get("alignment") == "Partial")
    note_parts = []
    if m.get("higher_order_pct") is not None:
        note_parts.append(f"{round(m['higher_order_pct'])}% of questions call for application or analysis")
    if m.get("inquiry_high_pct") is not None:
        note_parts.append(f"inquiry level 2+ for {round(m['inquiry_high_pct'])}% of episode time")
    if partial:
        note_parts.append(f"{partial} plan element(s) partially achieved")
    kpi = {
        "teacher_pct": pct(m.get("teacher_pct")),
        "student_speech_pct": pct(m.get("student_speech_pct")),
        "questions": str(len(questions)),
        "plan": f"{strong} / {len(align_rows)}" if align_rows else "—",
        "note": " · ".join(note_parts),
    }

    # --- вопросы
    counts: dict[str, int] = {}
    for q in questions:
        counts[q.get("category", "unknown")] = counts.get(q.get("category", "unknown"), 0) + 1
    order = [c for c in CATEGORY_LABELS if c in counts] + [c for c in counts if c not in CATEGORY_LABELS]
    question_counts = [
        {"label": CATEGORY_LABELS.get(c, c), "count": counts[c], "pct": round(100 * counts[c] / len(questions))}
        for c in order
    ]
    questions_fmt = [
        {**q, "category_label": CATEGORY_LABELS.get(q.get("category", ""), q.get("category", "")),
         "quote": _text(q.get("quote")), "rationale": _text(q.get("rationale"))}
        for q in questions
    ]

    # --- inquiry
    episodes = results.get("inquiry_episodes") or []
    level_time: dict[str, float] = {}
    total_ep = 0.0
    for ep in episodes:
        s, e = ts_seconds(ep.get("start_timestamp")), ts_seconds(ep.get("end_timestamp"))
        if s is None or e is None or e <= s:
            continue
        total_ep += e - s
        level_time[ep.get("level", "")] = level_time.get(ep.get("level", ""), 0) + e - s
    inquiry_summary = " · ".join(
        f"{LEVEL_SHORT.get(k, k)}: {round(100 * v / total_ep)}%" for k, v in sorted(level_time.items())
    ) + " of episode time" if total_ep else ""
    episodes_fmt = [
        {
            "start_timestamp": ep.get("start_timestamp", ""),
            "end_timestamp": ep.get("end_timestamp", ""),
            "level_label": LEVEL_LABELS.get(ep.get("level", ""), ep.get("level", "")),
            "rationale": _text(ep.get("rationale")),
            "evidence": f"(“{ep['evidence_quote']}”)" if ep.get("evidence_quote") else "",
        }
        for ep in episodes
    ]

    # --- план и факт
    alignment_fmt = [
        {
            "field_label": FIELD_LABELS.get(r.get("field", ""), r.get("field", "")),
            "planned": _text(r.get("planned") or planned.get(r.get("field", "")) or "—"),
            "observed_evidence": _text(r.get("observed_evidence") or "(no evidence found)"),
            "alignment": r.get("alignment", ""),
        }
        for r in align_rows
    ]

    # --- критерии
    criteria: list[dict] = []
    for r in results.get("criteria_rows") or []:
        if not criteria or criteria[-1]["code"] != r.get("criterion"):
            criteria.append({
                "code": r.get("criterion"),
                "title": f"Criterion {r.get('criterion')}: {r.get('criterion_label', '')}{AUDIO_SUFFIX.get(r.get('audio', ''), '')}",
                "rows": [],
            })
        evidence = r.get("evidence") or ""
        if r.get("timestamp") and r["timestamp"] not in evidence:
            evidence = f"[{r['timestamp']}] {evidence}".strip()
        criteria[-1]["rows"].append({
            "strand": f"{r.get('strand_id', '')} {r.get('strand', '')}".strip(),
            "opportunity": OPPORTUNITY_LABELS.get(r.get("opportunity", ""), r.get("opportunity", "")),
            "evidence": _text(evidence or "—"),
            "suggestion": _text(r.get("suggestion") or "—"),
        })

    # --- обсуждение
    comments_fmt = []
    for c in comments or []:
        parts = [c.get("author_name") or c.get("author_email") or "",
                 ROLE_LABELS.get(c.get("author_role", ""), ""), format_time(c.get("created_at") or 0)]
        section = SECTION_LABELS.get(c.get("section", ""))
        if section:
            parts.append(f"re: {section}")
        comments_fmt.append({"header": " · ".join(p for p in parts if p), "body": _text(c.get("body"))})

    reflection = results.get("reflection") or {}
    single = bool(results.get("single_track_mode"))
    talk_note = (
        "Teacher's recording only: speaker roles were inferred from the content of speech and are less "
        "reliable than with two recordings. "
        if single else
        "Speaker roles come from aligning the teacher's and the classroom recordings, not from voice "
        "recognition. "
    ) + "Student share includes silence attributed to independent or group work — see measured speech."

    return {
        "teacher_name": meta.get("teacher_name") or planned.get("teacher_name") or "—",
        "subject": meta.get("subject") or planned.get("subject") or "—",
        "lesson_date": _date(meta.get("lesson_date") or planned.get("lesson_date") or ""),
        "lesson_title": meta.get("lesson_title") or meta.get("subject") or planned.get("subject") or "Lesson",
        "grade": meta.get("grade") or "—",
        "subject_group": subject_group or "—",
        "lesson_language": LANGUAGE_LABELS.get(meta.get("lesson_language") or "", "—"),
        "duration": _duration(tt.get("total_duration_seconds")),
        "generated_at": format_time(datetime.now().timestamp()),
        "kpi": kpi,
        "talk_time": tt,
        "talk_note": talk_note,
        "alignment_rows": alignment_fmt,
        "question_counts": question_counts,
        "questions": questions_fmt,
        "intended_vs_enacted_summary": _text(results.get("intended_vs_enacted_summary") or "—"),
        "inquiry_summary": inquiry_summary,
        "inquiry_episodes": episodes_fmt,
        "criteria": criteria,
        "strengths": [_text(s) for s in reflection.get("strengths", [])],
        "areas_for_development": [_text(a) for a in reflection.get("areas_for_development", [])],
        "suggested_next_lesson_strategy": _text(reflection.get("suggested_next_lesson_strategy") or "—"),
        "comments": comments_fmt,
        "methodology_notes": _text((results.get("methodology_notes") or methodology_notes(single)) + _quality_note(results)),
    }


def render_report_bytes(context: dict, template_path: str) -> bytes:
    tpl = DocxTemplate(template_path)
    tpl.render(context, autoescape=True)
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


def render_report(context: dict, template_path: str, out_path: str) -> None:
    with open(out_path, "wb") as f:
        f.write(render_report_bytes(context, template_path))
    print(f"Report saved to {out_path}")
