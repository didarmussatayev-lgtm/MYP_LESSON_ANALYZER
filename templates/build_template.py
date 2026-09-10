"""
Одноразовый скрипт: собирает templates/lesson_report_template.docx —
Word-шаблон с Jinja-тегами ({{ }}, {% %}), который затем заполняется
через docxtpl в src/report.py.

Запускать один раз (или после ручной правки структуры). Готовый .docx
дальше можно и нужно редактировать прямо в Word (форматирование, логотип
школы и т.п.) - docxtpl не ломает ручное форматирование вокруг тегов,
если сами теги остаются одним run'ом (см. функцию _tag ниже).

Важно: методист может так же открыть готовый lesson_report_template.docx
в Word и поправить оформление напрямую, не трогая код - теги остаются
как обычный текст вида {{ field }} и {% for x in y %}...{% endfor %}.
"""

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


def set_cell_shading(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def add_heading(doc, text, level=1, color="1F3864"):
    h = doc.add_heading(level=level)
    run = h.add_run(text)
    run.font.color.rgb = RGBColor.from_string(color)
    return h


def add_tagged_paragraph(doc, tag_text, style=None):
    """Добавляет параграф, где ВЕСЬ текст (включая {{ }}) - один run,
    чтобы docxtpl гарантированно нашёл тег целиком, а не разбитым."""
    p = doc.add_paragraph(style=style)
    p.add_run(tag_text)
    return p


def build():
    doc = Document()

    # --- базовые стили документа ---
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)

    section = doc.sections[0]
    section.left_margin = Cm(2)
    section.right_margin = Cm(2)

    # --- титул ---
    title = doc.add_heading(level=0)
    title_run = title.add_run("AI-Assisted MYP Lesson Observation Report")
    title_run.font.color.rgb = RGBColor.from_string("1F3864")

    meta = doc.add_paragraph()
    meta.add_run("Teacher: ").bold = True
    meta.add_run("{{ teacher_name }}    ")
    meta.add_run("Subject: ").bold = True
    meta.add_run("{{ subject }}    ")
    meta.add_run("Date: ").bold = True
    meta.add_run("{{ lesson_date }}")

    disclaimer = doc.add_paragraph()
    disclaimer_run = disclaimer.add_run(
        "This report is an AI-assisted draft intended to support reflection and "
        "instructional coaching. It is not a formal performance evaluation. "
        "All classifications should be reviewed by the teacher before use."
    )
    disclaimer_run.italic = True
    disclaimer_run.font.size = Pt(9)
    disclaimer_run.font.color.rgb = RGBColor.from_string("666666")

    doc.add_paragraph()

    # =====================================================================
    # BLOCK 1 - Planned vs Observed
    # =====================================================================
    add_heading(doc, "Block 1 — Planned Framework vs Observed Evidence", level=1)

    table1 = doc.add_table(rows=1, cols=4)
    table1.alignment = WD_TABLE_ALIGNMENT.CENTER
    table1.style = "Table Grid"
    hdr = table1.rows[0].cells
    headers = ["MYP Planning Element", "Planned", "Observed Evidence", "Alignment"]
    for cell, text in zip(hdr, headers):
        cell.text = ""
        r = cell.paragraphs[0].add_run(text)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        set_cell_shading(cell, "1F3864")

    # jinja for-loop как отдельная "невидимая" строка таблицы (docxtpl row-loop)
    loop_row = table1.add_row().cells
    loop_row[0].text = ""
    loop_row[0].paragraphs[0].add_run("{%tr for row in alignment_rows %}")

    data_row = table1.add_row().cells
    data_row[0].paragraphs[0].add_run("{{ row.field_label }}")
    data_row[1].paragraphs[0].add_run("{{ row.planned }}")
    data_row[2].paragraphs[0].add_run("{{ row.observed_evidence }}")
    data_row[3].paragraphs[0].add_run("{{ row.alignment }}")

    endloop_row = table1.add_row().cells
    endloop_row[0].paragraphs[0].add_run("{%tr endfor %}")

    doc.add_paragraph()

    # =====================================================================
    # BLOCK 2 - Student vs Teacher Talk
    # =====================================================================
    add_heading(doc, "Block 2 — Student vs Teacher Talk", level=1)

    table2 = doc.add_table(rows=1, cols=3)
    table2.style = "Table Grid"
    hdr2 = table2.rows[0].cells
    for cell, text in zip(hdr2, ["Metric", "Teacher", "Student"]):
        cell.text = ""
        r = cell.paragraphs[0].add_run(text)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        set_cell_shading(cell, "1F3864")

    metric_rows = [
        ("Talk time (%)", "{{ talk_time.teacher_pct }}%", "{{ talk_time.student_pct }}%"),
        ("Talk time (seconds)", "{{ talk_time.teacher_seconds }}", "{{ talk_time.student_seconds }}"),
        ("Number of utterances", "{{ talk_time.teacher_utterance_count }}", "{{ talk_time.student_utterance_count }}"),
        (
            "Avg. utterance length (sec)",
            "{{ talk_time.avg_teacher_utterance_len_sec }}",
            "{{ talk_time.avg_student_utterance_len_sec }}",
        ),
    ]
    for label, t_val, s_val in metric_rows:
        row = table2.add_row().cells
        row[0].paragraphs[0].add_run(label)
        row[1].paragraphs[0].add_run(t_val)
        row[2].paragraphs[0].add_run(s_val)

    note2 = doc.add_paragraph()
    note2_run = note2.add_run(
        "Note: speaker roles are assigned via timestamp alignment between the lapel "
        "track (teacher) and the classroom track, not via voice diarization. "
        "See methodology notes for limitations."
    )
    note2_run.italic = True
    note2_run.font.size = Pt(9)

    doc.add_paragraph()

    # =====================================================================
    # BLOCK 3 - Questioning, Pedagogy, Inquiry Level
    # =====================================================================
    add_heading(doc, "Block 3 — Questioning, Pedagogy & Inquiry Level", level=1)

    add_heading(doc, "3.1 Teacher Question Classification", level=2)
    table3 = doc.add_table(rows=1, cols=4)
    table3.style = "Table Grid"
    for cell, text in zip(table3.rows[0].cells, ["Timestamp", "Question", "Category", "Rationale"]):
        cell.text = ""
        r = cell.paragraphs[0].add_run(text)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        set_cell_shading(cell, "2E5395")

    q_loop = table3.add_row().cells
    q_loop[0].paragraphs[0].add_run("{%tr for q in questions %}")
    q_data = table3.add_row().cells
    q_data[0].paragraphs[0].add_run("{{ q.timestamp }}")
    q_data[1].paragraphs[0].add_run("{{ q.quote }}")
    q_data[2].paragraphs[0].add_run("{{ q.category }}")
    q_data[3].paragraphs[0].add_run("{{ q.rationale }}")
    q_endloop = table3.add_row().cells
    q_endloop[0].paragraphs[0].add_run("{%tr endfor %}")

    add_tagged_paragraph(doc, "Question distribution: {{ question_distribution_summary }}")

    add_heading(doc, "3.2 Intended vs Enacted Pedagogy", level=2)
    add_tagged_paragraph(doc, "{{ intended_vs_enacted_summary }}")

    add_heading(doc, "3.3 Inquiry Level Timeline", level=2)
    table4 = doc.add_table(rows=1, cols=4)
    table4.style = "Table Grid"
    for cell, text in zip(table4.rows[0].cells, ["Start", "End", "Level", "Rationale / Evidence"]):
        cell.text = ""
        r = cell.paragraphs[0].add_run(text)
        r.bold = True
        r.font.color.rgb = RGBColor.from_string("FFFFFF")
        set_cell_shading(cell, "2E5395")

    lvl_loop = table4.add_row().cells
    lvl_loop[0].paragraphs[0].add_run("{%tr for ep in inquiry_episodes %}")
    lvl_data = table4.add_row().cells
    lvl_data[0].paragraphs[0].add_run("{{ ep.start_timestamp }}")
    lvl_data[1].paragraphs[0].add_run("{{ ep.end_timestamp }}")
    lvl_data[2].paragraphs[0].add_run("{{ ep.level_label }}")
    lvl_data[3].paragraphs[0].add_run("{{ ep.rationale }} ({{ ep.evidence_quote }})")
    lvl_endloop = table4.add_row().cells
    lvl_endloop[0].paragraphs[0].add_run("{%tr endfor %}")

    doc.add_paragraph()

    # =====================================================================
    # BLOCK 4 - AI-assisted reflection
    # =====================================================================
    add_heading(doc, "Block 4 — AI-Assisted Reflection on MYP-Aligned Teaching Practice", level=1)

    add_heading(doc, "Top 3 Strengths", level=2)
    add_tagged_paragraph(doc, "{% for s in strengths %}")
    add_tagged_paragraph(doc, "{{ s }}", style="List Bullet")
    add_tagged_paragraph(doc, "{% endfor %}")

    add_heading(doc, "Top 3 Areas for Development", level=2)
    add_tagged_paragraph(doc, "{% for a in areas_for_development %}")
    add_tagged_paragraph(doc, "{{ a }}", style="List Bullet")
    add_tagged_paragraph(doc, "{% endfor %}")

    add_heading(doc, "Suggested Next Lesson Strategy", level=2)
    add_tagged_paragraph(doc, "{{ suggested_next_lesson_strategy }}")

    add_heading(doc, "Methodology Notes & Limitations", level=2)
    add_tagged_paragraph(doc, "{{ methodology_notes }}")

    doc.save("lesson_report_template.docx")
    print("Saved templates/lesson_report_template.docx")


if __name__ == "__main__":
    build()
