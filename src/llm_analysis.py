"""
Все LLM-вызовы пайплайна (текстовый анализ, не аудио). Используется Gemini API
(google-genai SDK) - тот же провайдер, что и для транскрипции в
gemini_transcribe.py, чтобы был один API-ключ и один счёт.

Дизайн-решение: каждый аналитический блок - ОТДЕЛЬНЫЙ вызов со своим
узким промптом и строгим JSON-выводом, а не один гигантский промпт на
весь урок. Так проще отлаживать, тестировать и заменять модель/промпт
по отдельности, и меньше риск, что модель "потеряет" часть инструкции
в длинном контексте.

Требует переменную окружения GEMINI_API_KEY (платный ключ - см. README
про приватность).
"""

from __future__ import annotations

import json
import os
import re

import yaml
from google import genai
from google.genai import types

from common import Utterance

MODEL = "gemini-3.6-flash"  # см. README про выбор модели / актуальные названия - проверять периодически

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY не задан. См. README, раздел 'Настройка API-ключа'."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def _load_taxonomy(taxonomy_path: str) -> dict:
    with open(taxonomy_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _call_gemini_json(system_prompt: str, user_prompt: str) -> dict | list:
    """
    Вызывает Gemini и парсит ответ как JSON. response_mime_type="application/json"
    обычно даёт чистый JSON без markdown-обрамления, но на всякий случай текст
    всё равно подчищается перед парсингом.
    """
    client = _get_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
        ),
    )
    text = response.text or ""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Модель вернула не-JSON ответ:\n{text[:2000]}") from e


def _format_utterances(utterances: list[Utterance], speaker: str | None = None) -> str:
    lines = []
    for u in utterances:
        if speaker and u.speaker != speaker:
            continue
        lines.append(f"[{u.start:.1f}-{u.end:.1f}] {u.speaker}: {u.text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Блок 3a: классификация вопросов учителя
# ---------------------------------------------------------------------------

def classify_questions(utterances: list[Utterance], taxonomy: dict) -> list[dict]:
    categories = taxonomy["question_categories"]
    taxonomy_text = "\n".join(
        f"- {name} ({info['definition'].strip()}) Примеры: {'; '.join(info['examples'])}"
        for name, info in categories.items()
    )

    system_prompt = f"""Ты — ассистент для педагогического анализа уроков по методике IB MYP.
Твоя задача — найти в репликах учителя вопросы, обращённые к ученикам,
и классифицировать каждый по одной из категорий:

{taxonomy_text}

Верни ТОЛЬКО валидный JSON-массив, без markdown, без пояснений вне JSON.
Каждый элемент массива:
{{"timestamp": "MM:SS", "quote": "точная цитата вопроса", "category": "recall|understanding|application|analysis", "rationale": "одна короткая фраза почему именно эта категория"}}

Если вопросов нет — верни пустой массив [].
Не придумывай вопросы, которых нет в тексте."""

    user_prompt = "Реплики учителя:\n\n" + _format_utterances(utterances, speaker="Teacher")

    result = _call_gemini_json(system_prompt, user_prompt)
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Блок 3b: inquiry level по эпизодам урока
# ---------------------------------------------------------------------------

def classify_inquiry_levels(utterances: list[Utterance], taxonomy: dict) -> list[dict]:
    levels = taxonomy["inquiry_levels"]
    levels_text = "\n".join(
        f"- {key} ({info['name']}): {info['definition'].strip()}" for key, info in levels.items()
    )

    system_prompt = f"""Ты — ассистент для педагогического анализа уроков по методике IB MYP.
Раздели весь урок на смысловые эпизоды (несколько минут диалога вокруг одной
задачи/темы) и для каждого эпизода определи inquiry level:

{levels_text}

Верни ТОЛЬКО валидный JSON-массив без markdown. Каждый элемент:
{{"start_timestamp": "MM:SS", "end_timestamp": "MM:SS", "level": "level_1|level_2|level_4", "rationale": "1-2 предложения с конкретной привязкой к тому что происходило", "evidence_quote": "короткая цитата-подтверждение"}}

Эпизоды должны покрывать урок последовательно, без больших пропусков."""

    user_prompt = "Полная лента реплик урока (Teacher и Student):\n\n" + _format_utterances(utterances)

    result = _call_gemini_json(system_prompt, user_prompt)
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Блок 1: planned vs observed (10 пунктов unit planner)
# ---------------------------------------------------------------------------

PLANNED_FIELDS = [
    "key_concept",
    "related_concept",
    "global_context",
    "statement_of_inquiry",
    "inquiry_questions",
    "learning_objectives",
    "atl_skills",
    "learner_profile",
    "assessment_criteria",
    "learning_experiences",
]


def planned_vs_observed(
    planned: dict, utterances: list[Utterance], taxonomy: dict
) -> list[dict]:
    atl_text = "\n".join(
        f"- {info['label']}: {', '.join(info['indicators'])}"
        for info in taxonomy["atl_skill_clusters"].values()
    )

    system_prompt = f"""Ты — ассистент для педагогического анализа уроков по методике IB MYP.
Тебе дан план урока (что учитель ЗАПЛАНИРОВАЛ) и полная транскрипция урока.
Для КАЖДОГО из 10 пунктов плана найди в транскрипте конкретные свидетельства
(observed evidence) того, что запланированное реализовалось на практике,
и оцени alignment: "Strong" / "Partial" / "Not observed".

Справочник индикаторов ATL skills (используй при оценке пункта atl_skills):
{atl_text}

Верни ТОЛЬКО валидный JSON-массив из 10 элементов (по одному на каждый пункт
плана, в том же порядке, что дан в разделе "План"), без markdown:
{{"field": "имя_поля_как_в_плане", "planned": "краткое повторение того что было запланировано", "observed_evidence": "конкретная цитата/пересказ с таймкодом из транскрипта, или пусто если не найдено", "alignment": "Strong|Partial|Not observed"}}

Не придумывай свидетельств, которых нет в транскрипте. Если свидетельств
нет — честно ставь "Not observed" и оставляй observed_evidence пустым."""

    planned_text = "\n".join(f"{field}: {planned.get(field, '(не указано)')}" for field in PLANNED_FIELDS)
    user_prompt = (
        f"План урока:\n{planned_text}\n\n"
        f"Транскрипт урока:\n{_format_utterances(utterances)}"
    )

    result = _call_gemini_json(system_prompt, user_prompt)
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Блок 4: синтез рефлексии
# ---------------------------------------------------------------------------

def synthesize_reflection(
    talk_time: dict,
    question_stats: list[dict],
    inquiry_levels: list[dict],
    alignment_rows: list[dict],
) -> dict:
    system_prompt = """Ты — ассистент-коуч для педагогической рефлексии по методике IB MYP.
На основе предоставленных данных анализа урока сформулируй:
- top 3 strengths (сильные стороны), каждая с конкретной ссылкой на данные/evidence
- top 3 areas for development (зоны роста), каждая с конкретной ссылкой на данные/evidence
- suggested_next_lesson_strategy: одна конкретная, выполнимая рекомендация для
  следующего урока, привязанная к выявленным зонам роста (не общая фраза)

Каждый пункт strengths/areas должен ссылаться на конкретные цифры или цитаты
из переданных данных, а не быть общим утверждением без основания.

Верни ТОЛЬКО валидный JSON без markdown:
{"strengths": ["...", "...", "..."], "areas_for_development": ["...", "...", "..."], "suggested_next_lesson_strategy": "..."}"""

    user_prompt = json.dumps(
        {
            "talk_time": talk_time,
            "question_classification": question_stats,
            "inquiry_levels": inquiry_levels,
            "planned_vs_observed": alignment_rows,
        },
        ensure_ascii=False,
        indent=2,
    )

    result = _call_gemini_json(system_prompt, user_prompt)
    return result if isinstance(result, dict) else {}
