"""Сводные показатели урока (в процентах) — для веб-динамики и Word-отчёта."""

from __future__ import annotations


def ts_seconds(value) -> float | None:
    """'MM:SS' или 'H:MM:SS' -> секунды; None, если не разобрать."""
    try:
        parts = [float(x) for x in str(value).strip().split(":")]
    except ValueError:
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def lesson_metrics(results: dict) -> dict:
    tt = results.get("talk_time") or {}
    summary = results.get("summary") or {}
    total = tt.get("total_duration_seconds") or 0

    ep_total = ep_high = 0.0
    for ep in results.get("inquiry_episodes") or []:
        s, e = ts_seconds(ep.get("start_timestamp")), ts_seconds(ep.get("end_timestamp"))
        if s is None or e is None or e <= s:
            continue
        ep_total += e - s
        if ep.get("level") in ("level_2", "level_3", "level_4"):
            ep_high += e - s

    rows = results.get("alignment_rows") or []
    strong = sum(1 for r in rows if r.get("alignment") == "Strong")
    partial = sum(1 for r in rows if r.get("alignment") == "Partial")

    crit = [r for r in (results.get("criteria_rows") or []) if r.get("opportunity") != "Not observable"]
    crit_strong = sum(1 for r in crit if r.get("opportunity") == "Strong")

    def pct(a, b):
        return round(100 * a / b, 1) if b else None

    questions = results.get("questions") or []
    higher = sum(1 for q in questions if q.get("category") in ("application", "analysis"))
    return {
        "duration_seconds": total or None,
        "teacher_pct": tt.get("teacher_pct"),
        "student_speech_pct": pct(tt.get("student_speech_seconds") or 0, total),
        "question_count": summary.get("question_count", len(questions)),
        "higher_order_pct": summary.get("higher_order_pct", pct(higher, len(questions))),
        "inquiry_high_pct": pct(ep_high, ep_total),
        "plan_strong_pct": pct(strong + 0.5 * partial, len(rows)),
        "criteria_strong_pct": pct(crit_strong, len(crit)),
    }
