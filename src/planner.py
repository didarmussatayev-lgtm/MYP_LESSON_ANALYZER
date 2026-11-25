"""
Автозаполнение формы урока из unit planner (docx / pdf / текст).

Gemini получает документ и списки допустимых значений из
config/subject_frameworks.yaml и config/taxonomy.yaml и возвращает поля
формы. Всё, что выбирается из списков (key concept, related concepts,
критерии, ATL, learner profile), после ответа модели сверяется со
справочниками: значение, которого нет в списке, отбрасывается, а не
попадает в форму — модель не может «придумать» новый key concept.

Учитель всегда видит результат в форме и может поправить его до запуска
анализа.
"""

from __future__ import annotations

import io
import json
import re

from google.genai import types

import llm_analysis as la


class PlannerError(Exception):
    """Понятная пользователю ошибка (документ пустой, не похож на план и т.п.)."""


def _docx_text(data: bytes) -> str:
    from docx import Document  # python-docx, приходит вместе с docxtpl

    doc = Document(io.BytesIO(data))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    # Unit planner почти всегда — таблицы; читаем их построчно, без повторов
    # объединённых ячеек.
    for table in doc.tables:
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                t = cell.text.strip()
                if t and (not cells or cells[-1] != t):
                    cells.append(t)
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _match(value: str, allowed: list[str]) -> str | None:
    v = (value or "").strip().lower()
    if not v:
        return None
    for a in allowed:
        if a.lower() == v:
            return a
    for a in allowed:  # «Systems (key concept)» → «Systems»
        if a.lower() in v or v in a.lower():
            return a
    return None


def _match_many(values, allowed: list[str]) -> list[str]:
    if isinstance(values, str):
        values = [x for x in values.replace(";", ",").split(",")]
    out: list[str] = []
    for v in values or []:
        m = _match(str(v), allowed)
        if m and m not in out:
            out.append(m)
    return out


def _criteria_codes(values, codes: list[str]) -> list[str]:
    if isinstance(values, str):
        values = values.replace(";", ",").split(",")
    out: list[str] = []
    for v in values or []:
        m = re.search(r"(?:criterion\s*)?\b([A-Da-d])\b", str(v).strip(), flags=re.IGNORECASE)
        code = m.group(1).upper() if m else ""
        if code in codes and code not in out:
            out.append(code)
    return sorted(out)


def extract_planner(source: dict, frameworks: dict, taxonomy: dict, subject_key: str | None) -> dict:
    subjects = frameworks["subjects"]
    atl_labels = [c["label"] for c in taxonomy["atl_skill_clusters"].values()]

    subjects_text = "\n".join(
        f"- {key}: {s['label']}; criteria: "
        + ", ".join(f"{c['code']} {c['label']}" for c in s["assessment_criteria"])
        + (f"; related concepts: {', '.join(s['related_concepts'])}" if s["related_concepts"] else "")
        for key, s in subjects.items()
    )

    system_prompt = f"""Ты помогаешь учителю IB MYP перенести unit planner в форму анализа урока.
Тебе дан документ (unit planner или план урока). Извлеки поля ниже. Бери
формулировки из документа как есть (на языке документа), не сочиняй.
Если поля в документе нет — верни пустую строку или пустой список.

Допустимые значения:
- subject_key — один из ключей:
{subjects_text}
- key_concept — один из: {', '.join(frameworks['key_concepts'])}
- global_context — один из: {', '.join(frameworks['global_contexts'])}
- related_concepts — из списка related concepts выбранного предмета
- assessment_criteria — буквы критериев выбранного предмета, например ["A", "C"]
- atl_clusters — из: {', '.join(atl_labels)}
- learner_profile — из: {', '.join(frameworks['learner_profile_attributes'])}
{f'Учитель уже выбрал предмет: {subject_key}. Используй его, если документ явно не говорит о другом.' if subject_key else ''}

Верни ТОЛЬКО валидный JSON без markdown:
{{"is_planner": true, "lesson_title": "", "subject": "название курса, например Biology", "grade": "класс или MYP year", "subject_key": "", "key_concept": "", "global_context": "", "related_concepts": [], "statement_of_inquiry": "", "inquiry_questions": "Factual: ...\\nConceptual: ...\\nDebatable: ...", "learning_objectives": "", "assessment_criteria": [], "atl_clusters": [], "atl_detail": "конкретные ATL-навыки из документа одной строкой", "learner_profile": [], "learning_experiences": "кратко, что делают ученики"}}

is_planner = false, если документ явно не является планом юнита или урока."""

    if "text" in source:
        contents: list = ["Документ:\n\n" + source["text"]]
    elif source["ext"] == ".docx":
        text = _docx_text(source["bytes"])
        if not text.strip():
            raise PlannerError("В документе не найден текст.")
        contents = ["Документ:\n\n" + text[:60000]]
    elif source["ext"] == ".pdf":
        contents = [types.Part.from_bytes(data=source["bytes"], mime_type="application/pdf"), "Это unit planner."]
    else:
        contents = ["Документ:\n\n" + source["bytes"].decode("utf-8", errors="ignore")[:60000]]

    client = la._get_client()
    response = client.models.generate_content(
        model=la.MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system_prompt, response_mime_type="application/json"),
    )
    try:
        raw = json.loads((response.text or "").strip().strip("`").removeprefix("json").strip())
    except json.JSONDecodeError as e:
        raise PlannerError("Не удалось разобрать документ. Попробуйте ещё раз или вставьте текст плана вручную.") from e
    if not isinstance(raw, dict):
        raise PlannerError("Не удалось разобрать документ.")
    if raw.get("is_planner") is False:
        raise PlannerError("Документ не похож на unit planner. Проверьте, что прикреплён нужный файл.")

    key = raw.get("subject_key") if raw.get("subject_key") in subjects else (subject_key if subject_key in subjects else None)
    subj = subjects.get(key, {}) if key else {}
    codes = [c["code"] for c in subj.get("assessment_criteria", [])]

    def text_field(name: str) -> str:
        v = raw.get(name, "")
        return "\n".join(map(str, v)) if isinstance(v, list) else str(v or "").strip()

    return {
        "lesson_title": text_field("lesson_title"),
        "subject": text_field("subject"),
        "grade": text_field("grade"),
        "subject_key": key or "",
        "key_concept": _match(text_field("key_concept"), frameworks["key_concepts"]) or "",
        "global_context": _match(text_field("global_context"), frameworks["global_contexts"]) or "",
        "related_concepts": _match_many(raw.get("related_concepts"), subj.get("related_concepts", [])),
        "statement_of_inquiry": text_field("statement_of_inquiry"),
        "inquiry_questions": text_field("inquiry_questions"),
        "learning_objectives": text_field("learning_objectives"),
        "assessment_criteria": _criteria_codes(raw.get("assessment_criteria"), codes),
        "atl_clusters": _match_many(raw.get("atl_clusters"), atl_labels),
        "atl_detail": text_field("atl_detail"),
        "learner_profile": _match_many(raw.get("learner_profile"), frameworks["learner_profile_attributes"]),
        "learning_experiences": text_field("learning_experiences"),
    }
