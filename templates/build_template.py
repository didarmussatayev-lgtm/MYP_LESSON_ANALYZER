"""
Собирает templates/lesson_report_template.docx — Word-шаблон с тегами docxtpl
({{ поле }}, {%p ... %}, {%tr ... %}), который заполняется в src/report.py.

Запуск (из папки templates/):  python build_template.py

Готовый .docx можно и нужно править прямо в Word: шрифты, цвета, логотип
школы, колонтитулы, порядок блоков. Правила, чтобы не сломать заполнение:
- текст тега ({{ ... }} или {%... %}) не разрывать и не форматировать
  частично — тег должен быть набран одним куском с одинаковым оформлением;
- строки таблиц с {%tr for ... %} и {%tr endfor %} не удалять — это
  служебные строки цикла, в готовом отчёте их не видно;
- абзацы с {%p if ... %} / {%p for ... %} / {%p endfor %} / {%p endif %}
  тоже служебные и исчезают в готовом отчёте.
Полный список полей — в docs/WORD_TEMPLATE.md.
"""

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

NAVY = "1F3864"
BLUE = "2E5395"
GREY = "5B6068"
LIGHT = "EEF2F7"


def set_cell_shading(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def set_cell_borders(cell, color="FFFFFF", size="0") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single" if size != "0" else "nil")
        el.set(qn("w:sz"), size)
        el.set(qn("w:color"), color)
        borders.append(el)
    tc_pr.append(borders)


def add_heading(doc, text, level=1, color=NAVY):
    h = doc.add_heading(level=level)
    run = h.add_run(text)
    run.font.color.rgb = RGBColor.from_string(color)
    return h


def tag(doc, text, style=None, size=None, italic=False, color=None, bold=False):
    """Абзац, где весь текст — один run (docxtpl должен видеть тег целиком)."""
    p = doc.add_paragraph(style=style)
    r = p.add_run(text)
    if size:
        r.font.size = Pt(size)
    r.italic = italic
    r.bold = bold
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    return p


def note(doc, text):
    return tag(doc, text, size=9, italic=True, color=GREY)


def header_row(table, labels, fill=NAVY):
    for cell, text in zip(table.rows[0].cells, labels):
        cell.text = ""
        r = cell.paragraphs[0].add_run(text)
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        set_cell_shading(cell, fill)


def loop_table(doc, headers, loop_expr, cells, widths=None, fill=NAVY):
    """Таблица: шапка + строка-цикл {%tr for %} + строка данных + {%tr endfor %}."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header_row(table, headers, fill)
    table.add_row().cells[0].paragraphs[0].add_run(f"{{%tr for {loop_expr} %}}")
    data = table.add_row().cells
    for cell, text in zip(data, cells):
        r = cell.paragraphs[0].add_run(text)
        r.font.size = Pt(9.5)
    table.add_row().cells[0].paragraphs[0].add_run("{%tr endfor %}")
    if widths:
        for row in table.rows:
            for cell, w in zip(row.cells, widths):
                cell.width = Cm(w)
    return table


def add_page_number_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("MYP Lesson Analyzer · AI-assisted draft · page ")
    r.font.size = Pt(8)
    r.font.color.rgb = RGBColor.from_string(GREY)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "16")
    rpr.append(sz)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = "1"
    run.append(t)
    fld.append(run)
    p._p.append(fld)


def build():
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)

    section = doc.sections[0]
    section.left_margin = section.right_margin = Cm(2)
    section.top_margin = section.bottom_margin = Cm(1.8)
    add_page_number_footer(section)

    # ------------------------------------------------------------- титул
    title = doc.add_heading(level=0)
    tr = title.add_run("MYP Lesson Observation Report")
    tr.font.color.rgb = RGBColor.from_string(NAVY)
    tag(doc, "{{ lesson_title }}", size=14, bold=True, color=BLUE)

    meta = doc.add_table(rows=4, cols=4)
    meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    rows = [
        ("Teacher", "{{ teacher_name }}", "Lesson date", "{{ lesson_date }}"),
        ("Subject", "{{ subject }}", "Class / MYP year", "{{ grade }}"),
        ("Subject group", "{{ subject_group }}", "Lesson language", "{{ lesson_language }}"),
        ("Recording length", "{{ duration }}", "Report generated", "{{ generated_at }}"),
    ]
    for row, values in zip(meta.rows, rows):
        for i, (cell, text) in enumerate(zip(row.cells, values)):
            set_cell_borders(cell)
            cell.text = ""
            r = cell.paragraphs[0].add_run(text)
            r.font.size = Pt(9.5)
            if i % 2 == 0:
                r.font.color.rgb = RGBColor.from_string(GREY)
            else:
                r.bold = True

    disclaimer = note(
        doc,
        "This report is an AI-assisted draft intended to support reflection and instructional "
        "coaching. It is not a formal performance evaluation. All classifications should be "
        "reviewed by the teacher before use.",
    )
    disclaimer.paragraph_format.space_before = Pt(6)

    # ------------------------------------------------------------- ключевые показатели
    add_heading(doc, "Key figures", level=1)
    kf = doc.add_table(rows=2, cols=4)
    kf.alignment = WD_TABLE_ALIGNMENT.CENTER
    figures = [
        ("Teacher talk", "{{ kpi.teacher_pct }}"),
        ("Student speech", "{{ kpi.student_speech_pct }}"),
        ("Teacher questions", "{{ kpi.questions }}"),
        ("Plan elements achieved", "{{ kpi.plan }}"),
    ]
    for i, (label, value) in enumerate(figures):
        top, bottom = kf.rows[0].cells[i], kf.rows[1].cells[i]
        for c in (top, bottom):
            set_cell_shading(c, LIGHT)
            set_cell_borders(c, "FFFFFF", "12")
            c.text = ""
        r = top.paragraphs[0].add_run(label)
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor.from_string(GREY)
        r = bottom.paragraphs[0].add_run(value)
        r.font.size = Pt(15)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string(NAVY)
    note(doc, "{{ kpi.note }}")

    # ------------------------------------------------------------- Block 1
    add_heading(doc, "Block 1 — Planned Framework vs Observed Evidence", level=1)
    loop_table(
        doc,
        ["MYP planning element", "Planned", "Observed evidence", "Alignment"],
        "row in alignment_rows",
        ["{{ row.field_label }}", "{{ row.planned }}", "{{ row.observed_evidence }}", "{{ row.alignment }}"],
        widths=[3.5, 4.5, 6.5, 2.5],
    )

    # ------------------------------------------------------------- Block 2
    add_heading(doc, "Block 2 — Student vs Teacher Talk", level=1)
    table2 = doc.add_table(rows=1, cols=3)
    table2.style = "Table Grid"
    header_row(table2, ["Metric", "Teacher", "Students"])
    for label, t_val, s_val in [
        ("Share of lesson time (%)", "{{ talk_time.teacher_pct }}%", "{{ talk_time.student_pct }}%"),
        ("Time (seconds)", "{{ talk_time.teacher_seconds }}", "{{ talk_time.student_seconds }}"),
        ("  — measured student speech (sec)", "", "{{ talk_time.student_speech_seconds }}"),
        ("  — silence attributed to independent/group work (sec)", "", "{{ talk_time.silence_attributed_to_student_seconds }}"),
        ("Number of utterances", "{{ talk_time.teacher_utterance_count }}", "{{ talk_time.student_utterance_count }}"),
        ("Average utterance length (sec)", "{{ talk_time.avg_teacher_utterance_len_sec }}", "{{ talk_time.avg_student_utterance_len_sec }}"),
    ]:
        row = table2.add_row().cells
        for cell, text in zip(row, (label, t_val, s_val)):
            cell.paragraphs[0].add_run(text).font.size = Pt(9.5)
    note(doc, "{{ talk_note }}")

    # ------------------------------------------------------------- Block 3
    add_heading(doc, "Block 3 — Questioning, Pedagogy & Inquiry Level", level=1)
    add_heading(doc, "3.1 Teacher questions", level=2, color=BLUE)
    loop_table(
        doc, ["Question type", "Count", "Share"], "c in question_counts",
        ["{{ c.label }}", "{{ c.count }}", "{{ c.pct }}%"], widths=[8, 3, 3], fill=BLUE,
    )
    doc.add_paragraph()
    loop_table(
        doc, ["Time", "Question", "Type", "Why this type"], "q in questions",
        ["{{ q.timestamp }}", "{{ q.quote }}", "{{ q.category_label }}", "{{ q.rationale }}"],
        widths=[1.6, 6.5, 2.4, 6.5], fill=BLUE,
    )

    add_heading(doc, "3.2 Intended vs enacted pedagogy", level=2, color=BLUE)
    tag(doc, "{{ intended_vs_enacted_summary }}")

    add_heading(doc, "3.3 Inquiry level timeline", level=2, color=BLUE)
    tag(doc, "{{ inquiry_summary }}", size=9.5)
    loop_table(
        doc, ["Start", "End", "Level", "What happened / evidence"], "ep in inquiry_episodes",
        ["{{ ep.start_timestamp }}", "{{ ep.end_timestamp }}", "{{ ep.level_label }}", "{{ ep.rationale }} {{ ep.evidence }}"],
        widths=[1.5, 1.5, 4.5, 9.5], fill=BLUE,
    )

    # ------------------------------------------------------------- Block 4
    add_heading(doc, "Block 4 — Assessment Criteria: Opportunities by Strand", level=1)
    tag(doc, "{%p if criteria %}")
    note(
        doc,
        "Not a rubric score — that requires student work. Shows whether the lesson gave students "
        "an opportunity to demonstrate each strand of the selected criteria (strands worded as in "
        "the MYP year 5 objectives).",
    )
    tag(doc, "{%p for c in criteria %}")
    add_heading(doc, "{{ c.title }}", level=2, color=BLUE)
    loop_table(
        doc, ["Strand", "Opportunity", "Evidence", "Idea for next time"], "r in c.rows",
        ["{{ r.strand }}", "{{ r.opportunity }}", "{{ r.evidence }}", "{{ r.suggestion }}"],
        widths=[5, 2.6, 5, 4.4], fill=BLUE,
    )
    tag(doc, "{%p endfor %}")
    tag(doc, "{%p else %}")
    note(doc, "Assessment criteria were not analysed for this lesson.")
    tag(doc, "{%p endif %}")

    # ------------------------------------------------------------- Block 5
    add_heading(doc, "Block 5 — AI-Assisted Reflection", level=1)
    add_heading(doc, "Strengths", level=2, color=BLUE)
    tag(doc, "{%p for s in strengths %}")
    tag(doc, "{{ s }}", style="List Bullet")
    tag(doc, "{%p endfor %}")
    add_heading(doc, "Areas for development", level=2, color=BLUE)
    tag(doc, "{%p for a in areas_for_development %}")
    tag(doc, "{{ a }}", style="List Bullet")
    tag(doc, "{%p endfor %}")
    add_heading(doc, "Suggested next lesson strategy", level=2, color=BLUE)
    tag(doc, "{{ suggested_next_lesson_strategy }}")

    # ------------------------------------------------------------- Block 6
    add_heading(doc, "Block 6 — Discussion", level=1)
    tag(doc, "{%p if comments %}")
    tag(doc, "{%p for c in comments %}")
    tag(doc, "{{ c.header }}", size=9, color=GREY, bold=True)
    tag(doc, "{{ c.body }}")
    tag(doc, "{%p endfor %}")
    tag(doc, "{%p else %}")
    note(doc, "No comments yet. Coordinator and teacher comments from the website appear here.")
    tag(doc, "{%p endif %}")

    # ------------------------------------------------------------- методология
    add_heading(doc, "Methodology Notes & Limitations", level=2, color=GREY)
    tag(doc, "{{ methodology_notes }}", size=9, color=GREY)

    doc.save("lesson_report_template.docx")
    print("Saved templates/lesson_report_template.docx")


if __name__ == "__main__":
    build()
