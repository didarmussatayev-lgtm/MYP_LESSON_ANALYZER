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


# ---------------------------------------------------------------------------
# Починка результатов, сохранённых старыми версиями анализа
# ---------------------------------------------------------------------------

RESULTS_VERSION = 2


def _mmss(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h, rest = divmod(sec, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60:02d}:{rest % 60:02d}"


def _norm_ts(value) -> str:
    text = str(value if value is not None else "").strip()
    if not text or ":" in text:
        return text
    try:
        return _mmss(float(text.replace(",", ".")))
    except ValueError:
        return text


def repair_results(results: dict) -> bool:
    """
    Старые версии могли сохранить «битые» таймкоды расшифровки (конец реплики
    раньше начала) — из-за них доли речи получались отрицательными или
    больше 100%, — а модель иногда писала таймкоды секундами («1422.0»).
    Пересчитывает время речи по сохранённой расшифровке и приводит таймкоды
    к MM:SS. Возвращает True, если что-то изменилось.
    """
    if not results or results.get("version", 1) >= RESULTS_VERSION:
        return False
    from align import talk_time_summary
    from common import Utterance

    tt = results.get("talk_time") or {}
    total = tt.get("total_duration_seconds")
    utts = []
    for u in results.get("utterances") or []:
        try:
            start, end = float(u["start"]), float(u["end"])
        except (KeyError, TypeError, ValueError):
            continue
        estimated = max(1.0, 0.45 * len(str(u.get("text", "")).split()))
        if end <= start or end - start > max(30.0, 4 * estimated):
            end = start + estimated
        utts.append(Utterance(start=start, end=end, speaker=u.get("speaker", "Teacher"),
                              text=u.get("text", ""), source=u.get("source", "lapel")))
    utts.sort(key=lambda x: x.start)
    for a, b in zip(utts, utts[1:]):
        if a.end > b.start:
            a.end = max(a.start + 0.3, b.start)
    if utts:
        new_tt = talk_time_summary(utts, total_duration_seconds=total)
        results["talk_time"] = new_tt
        results["utterances"] = [u.__dict__ for u in utts]
        summary = results.setdefault("summary", {})
        summary["teacher_pct"] = new_tt["teacher_pct"]
        summary["student_pct"] = new_tt["student_pct"]

    for key, fields in (("questions", ("timestamp",)),
                        ("inquiry_episodes", ("start_timestamp", "end_timestamp")),
                        ("criteria_rows", ("timestamp",))):
        for item in results.get(key) or []:
            if isinstance(item, dict):
                for f in fields:
                    if f in item:
                        item[f] = _norm_ts(item[f])
    results["version"] = RESULTS_VERSION
    return True
