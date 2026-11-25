"""
Дополнительные разделы Word-отчёта, которые собираются в момент скачивания:

- «Assessment criteria» — strands выбранных критериев и возможности учеников
  проявить их на уроке (results["criteria_rows"]);
- «Discussion» — комментарии методиста и учителя (меняются после анализа,
  поэтому их нельзя «запечь» в отчёт при генерации).

Основной отчёт по-прежнему рендерится из templates/lesson_report_template.docx
(src/report.py), а этот модуль дописывает разделы в готовый файл через
python-docx — шаблон, который могли отредактировать в Word, не трогается.
Разделы вставляются перед «Methodology», если такой заголовок есть, иначе в конец.
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from docx import Document
from docx.shared import Pt, RGBColor

def format_time(ts: float) -> str:
    """Время в часовом поясе школы (сервер на Railway работает в UTC)."""
    try:
        tz = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Almaty"))
    except Exception:  # noqa: BLE001 - нет tzdata или неверное имя пояса
        tz = None
    return datetime.fromtimestamp(ts, tz).strftime("%d.%m.%Y %H:%M")


OPPORTUNITY_EN = {
    "Strong": "Students worked on it",
    "Partial": "Touched on",
    "Not observed": "Not observed",
    "Not observable": "Not observable from audio",
}
AUDIO_EN = {
    "full": "",
    "partial": " (only partially observable from audio)",
    "none": " (not observable from audio)",
}
ROLE_EN = {"teacher": "Teacher", "observer": "Coordinator", "admin": "Administrator"}
SECTION_EN = {
    "general": "",
    "summary": "Summary",
    "plan": "Planned vs observed",
    "criteria": "Assessment criteria",
    "questions": "Questions",
    "inquiry": "Inquiry",
    "transcript": "Transcript",
}


def _table(doc, rows: list[list[str]], widths_hint: list[int] | None = None):
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    for style in ("Light Grid Accent 1", "Table Grid"):
        try:
            table.style = doc.styles[style]
            break
        except KeyError:
            continue
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            cell = table.cell(r, c)
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            run.font.size = Pt(9)
            if r == 0:
                run.bold = True
    return table


def _criteria_section(doc, criteria_rows: list[dict]) -> None:
    doc.add_heading("Block 5 — Assessment Criteria: Opportunities by Strand", level=1)
    note = doc.add_paragraph(
        "This is not a rubric score — that requires student work. It shows whether the lesson "
        "gave students an opportunity to demonstrate each strand of the selected criteria. "
        "Strands are worded as in the MYP year 5 objectives."
    )
    for run in note.runs:
        run.italic = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x55, 0x5B, 0x63)

    by_crit: dict[str, list[dict]] = {}
    for r in criteria_rows:
        by_crit.setdefault(r.get("criterion", "?"), []).append(r)
    for code, rows in by_crit.items():
        first = rows[0]
        doc.add_heading(
            f"Criterion {code}: {first.get('criterion_label', '')}{AUDIO_EN.get(first.get('audio', ''), '')}",
            level=2,
        )
        data = [["Strand", "Opportunity", "Evidence", "Idea for next time"]]
        for r in rows:
            evidence = r.get("evidence") or ""
            if r.get("timestamp") and r["timestamp"] not in evidence:
                evidence = f"[{r['timestamp']}] {evidence}".strip()
            data.append([
                f"{r.get('strand_id', '')} {r.get('strand', '')}",
                OPPORTUNITY_EN.get(r.get("opportunity", ""), r.get("opportunity", "")),
                evidence or "—",
                r.get("suggestion") or "—",
            ])
        _table(doc, data)
        doc.add_paragraph()


def _discussion_section(doc, comments: list[dict]) -> None:
    doc.add_heading("Block 6 — Discussion", level=1)
    for c in comments:
        meta = doc.add_paragraph()
        who = meta.add_run(c.get("author_name") or c.get("author_email") or "")
        who.bold = True
        when = format_time(c.get("created_at") or 0)
        extra = [ROLE_EN.get(c.get("author_role", ""), ""), when]
        section = SECTION_EN.get(c.get("section", "general"), "")
        if section:
            extra.append(f"re: {section}")
        tail = meta.add_run("  ·  " + "  ·  ".join(x for x in extra if x))
        tail.font.size = Pt(9)
        tail.font.color.rgb = RGBColor(0x55, 0x5B, 0x63)
        doc.add_paragraph(c.get("body", ""))


def build_report(src_path: str, results: dict, comments: list[dict]) -> bytes:
    doc = Document(src_path)
    body = doc.element.body

    anchor = None
    for p in doc.paragraphs:
        if p.style is not None and p.style.name.startswith("Heading") and p.text.strip().lower().startswith("methodolog"):
            anchor = p
            break

    before = len(body)
    criteria_rows = results.get("criteria_rows") or []
    if criteria_rows:
        _criteria_section(doc, criteria_rows)
    if comments:
        _discussion_section(doc, comments)

    if anchor is not None and len(body) > before:
        # python-docx дописывает перед sectPr; переносим новые элементы перед «Methodology».
        new_elems = [el for el in list(body)[before - 1:] if el.tag.endswith("}p") or el.tag.endswith("}tbl")]
        sect = body[-1] if body[-1].tag.endswith("}sectPr") else None
        new_elems = [el for el in new_elems if el is not sect]
        # список body до вставки заканчивался sectPr, поэтому новые элементы начинаются с before-1
        for el in new_elems:
            anchor._p.addprevious(el)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
