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
import threading

import yaml
from google import genai
from google.genai import types

from common import Utterance

MODEL = "gemini-3.6-flash"  # см. README про выбор модели / актуальные названия - проверять периодически

_client: genai.Client | None = None

# Язык пояснений в ответах модели. Хранится на поток: анализ уроков идёт в
# фоновом потоке, и язык одного урока не должен «протечь» в другой.
_lang = threading.local()


def set_feedback_language(language: str) -> None:
    """language — в предложном падеже: «русском», «казахском», «английском»."""
    _lang.value = language


def _language_instruction() -> str:
    language = getattr(_lang, "value", None) or "русском"
    return (
        f"\n\nЯЗЫК ОТВЕТА: все пояснения, выводы и рекомендации (rationale, summary, "
        f"strengths, areas_for_development, suggested_next_lesson_strategy, suggestion, "
        f"пересказы в observed_evidence/evidence) пиши на {language} языке. Цитаты из урока "
        f"(quote, evidence_quote и цитаты внутри пояснений) оставляй на языке оригинала. "
        f"Коды и служебные значения (category, level, alignment, opportunity, field, "
        f"strand_id) не переводи."
    )


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
            system_instruction=system_prompt + _language_instruction(),
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
        lines.append(f"[{_mmss(u.start)}-{_mmss(u.end)}] {u.speaker}: {u.text}")
    return "\n".join(lines)


def _mmss(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h, rest = divmod(sec, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60:02d}:{rest % 60:02d}"


def norm_ts(value) -> str:
    """
    Приводит таймкод из ответа модели к MM:SS: модель иногда возвращает
    секунды («1422.0») вместо минут и секунд.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if ":" in text:
        return text
    try:
        return _mmss(float(text.replace(",", ".")))
    except ValueError:
        return text


def _norm_items(items, keys=("timestamp", "start_timestamp", "end_timestamp")):
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                for k in keys:
                    if k in it:
                        it[k] = norm_ts(it[k])
    return items


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
    return _norm_items(result) if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Блок 3b: inquiry level по эпизодам урока
# ---------------------------------------------------------------------------

def classify_inquiry_levels(utterances: list[Utterance], taxonomy: dict) -> list[dict]:
    levels = taxonomy["inquiry_levels"]
    levels_text = "\n".join(
        f"- {key} ({info['name']}): {info['definition'].strip()}" for key, info in levels.items()
    )
    level_keys = "|".join(levels)
    lesson_start = _mmss(utterances[0].start) if utterances else "00:00"
    lesson_end = _mmss(max((u.end for u in utterances), default=0))

    system_prompt = f"""Ты — ассистент для педагогического анализа уроков по методике IB MYP.
Раздели весь урок на смысловые эпизоды (несколько минут диалога вокруг одной
задачи/темы) и для каждого эпизода определи inquiry level:

{levels_text}

Как различать уровни: смотри, КТО формулирует вопрос (учитель — уровни 1–3,
ученики — уровень 4) и КТО решает, КАК искать ответ (учитель даёт способ —
уровень 2, ученики выбирают способ сами — уровень 3). Если ученики просто
отвечают на вопросы учителя — уровень 1.

Верни ТОЛЬКО валидный JSON-массив без markdown. Каждый элемент:
{{"start_timestamp": "MM:SS", "end_timestamp": "MM:SS", "level": "{level_keys}", "rationale": "1-2 предложения с конкретной привязкой к тому что происходило", "evidence_quote": "короткая цитата-подтверждение"}}

Эпизоды должны идти по порядку и покрывать ВЕСЬ урок от {lesson_start} до
{lesson_end} без пропусков: конец одного эпизода — начало следующего. Паузы и
организационные моменты включай в соседний эпизод."""

    user_prompt = "Полная лента реплик урока (Teacher и Student):\n\n" + _format_utterances(utterances)

    result = _call_gemini_json(system_prompt, user_prompt)
    return _norm_items(result) if isinstance(result, list) else []


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

# ---------------------------------------------------------------------------
# Блок 3.2: intended vs enacted pedagogy
# ---------------------------------------------------------------------------

def summarize_intended_vs_enacted(
    planned: dict,
    talk_time: dict,
    questions: list[dict],
    inquiry_episodes: list[dict],
) -> str:
    """
    В отличие от planned_vs_observed (10 пунктов unit planner - фактическая
    информация), этот вызов сравнивает ЗАЯВЛЕННЫЙ педагогический подход
    (learning_experiences, ATL skills из плана - что учитель собирался делать
    методически) с ФАКТИЧЕСКИ реализованной педагогикой (распределение
    inquiry-level по эпизодам, распределение категорий вопросов, talk-time).

    Возвращает готовый текстовый абзац (не JSON-структуру) для прямой
    вставки в отчёт.
    """
    system_prompt = """Ты — ассистент для педагогического анализа уроков по методике IB MYP.
Тебе даны: заявленный в плане урока педагогический подход (learning_experiences,
atl_skills - что учитель собирался делать методически) и фактические данные о
том, что происходило на уроке (talk-time, распределение категорий вопросов,
распределение inquiry-level по эпизодам урока).

Напиши ОДИН связный абзац (3-5 предложений), сравнивающий
заявленный подход с тем, что реально наблюдалось. Будь конкретен - ссылайся
на цифры и категории из данных, а не пиши общими фразами. Если заявленный
подход и наблюдаемая практика расходятся - прямо это отметь. Если план не
даёт достаточно информации, чтобы судить о заявленном педагогическом
подходе - честно напиши, что сравнение ограничено из-за недостатка деталей
в плане, а не выдумывай.

Верни ТОЛЬКО валидный JSON без markdown: {"summary": "..."}"""

    inquiry_level_counts: dict[str, int] = {}
    for ep in inquiry_episodes:
        lvl = ep.get("level", "unknown")
        inquiry_level_counts[lvl] = inquiry_level_counts.get(lvl, 0) + 1

    question_category_counts: dict[str, int] = {}
    for q in questions:
        cat = q.get("category", "unknown")
        question_category_counts[cat] = question_category_counts.get(cat, 0) + 1

    user_prompt = json.dumps(
        {
            "planned_learning_experiences": planned.get("learning_experiences", ""),
            "planned_atl_skills": planned.get("atl_skills", ""),
            "planned_learning_objectives": planned.get("learning_objectives", ""),
            "observed_talk_time": talk_time,
            "observed_question_category_counts": question_category_counts,
            "observed_inquiry_level_counts": inquiry_level_counts,
        },
        ensure_ascii=False,
        indent=2,
    )

    result = _call_gemini_json(system_prompt, user_prompt)
    if isinstance(result, dict):
        return result.get("summary", "")
    return ""


def synthesize_reflection(
    talk_time: dict,
    question_stats: list[dict],
    inquiry_levels: list[dict],
    alignment_rows: list[dict],
    criteria_rows: list[dict] | None = None,
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
            "assessment_criteria_strand_opportunities": [
                {k: r.get(k) for k in ("strand_id", "strand", "opportunity", "evidence")}
                for r in (criteria_rows or [])
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    result = _call_gemini_json(system_prompt, user_prompt)
    return result if isinstance(result, dict) else {}


# ---------------------------------------------------------------------------
# Блок 5: критерии оценивания предмета — где на уроке отрабатывались strands
# ---------------------------------------------------------------------------

AUDIO_LABELS = {
    "full": "observable from lesson audio",
    "partial": "only partially observable from lesson audio (oral discussion only)",
    "none": "NOT observable from lesson audio (written/practical work)",
}


def criteria_evidence(
    subject_def: dict, selected_codes: list[str], utterances: list[Utterance]
) -> list[dict]:
    """
    Для каждого strand выбранных критериев предмета (config/subject_frameworks.yaml)
    ищет в транскрипте моменты, где ученики работали над этим strand.

    Это не выставление баллов по рубрике (для этого нужны работы учеников),
    а карта возможностей: давал ли урок ученикам повод продемонстрировать
    каждый strand.
    """
    criteria = [c for c in subject_def.get("assessment_criteria", []) if c["code"] in selected_codes]
    if not criteria:
        return []

    criteria_text = "\n".join(
        f"Criterion {c['code']}: {c['label']} ({AUDIO_LABELS.get(c.get('audio', 'partial'), '')})\n"
        + "\n".join(f"  {c['code']}.{i + 1}: {s}" for i, s in enumerate(c.get("strands", [])))
        for c in criteria
    )

    system_prompt = f"""Ты — ассистент для педагогического анализа уроков по методике IB MYP.
Предмет: {subject_def.get('label', '')}.
Учитель запланировал работу по критериям оценивания ниже. Для КАЖДОГО strand
найди в транскрипте урока моменты, где ученики получили возможность
продемонстрировать этот strand (задание, вопрос, обсуждение, ответ ученика).

{criteria_text}

Оценка opportunity для каждого strand:
- "Strong" — ученики явно и содержательно работали над strand (есть их реплики);
- "Partial" — strand затронут (например, учитель объяснил или поставил задачу),
  но ученики почти не демонстрировали его сами;
- "Not observed" — свидетельств в транскрипте нет;
- "Not observable" — strand по своей природе не наблюдается по аудио
  (письменная/практическая работа) и свидетельств нет.

Верни ТОЛЬКО валидный JSON-массив без markdown, по одному элементу на каждый strand,
в том же порядке:
{{"strand_id": "A.1", "opportunity": "Strong|Partial|Not observed|Not observable", "evidence": "конкретная цитата/пересказ на языке урока или пусто", "timestamp": "MM:SS или пусто", "suggestion": "одна короткая конкретная идея, как дать ученикам больше возможности по этому strand; пусто, если Strong"}}

Не придумывай свидетельств, которых нет в транскрипте."""

    user_prompt = "Транскрипт урока:\n\n" + _format_utterances(utterances)
    result = _call_gemini_json(system_prompt, user_prompt)
    if not isinstance(result, list):
        return []

    # Подставляем коды и тексты strands из конфига, а не из ответа модели.
    by_id = {r.get("strand_id"): r for r in result if isinstance(r, dict)}
    out = []
    for c in criteria:
        for i, strand in enumerate(c.get("strands", [])):
            sid = f"{c['code']}.{i + 1}"
            r = by_id.get(sid, {})
            out.append({
                "criterion": c["code"],
                "criterion_label": c["label"],
                "audio": c.get("audio", "partial"),
                "strand_id": sid,
                "strand": strand,
                "opportunity": r.get("opportunity", "Not observed"),
                "evidence": r.get("evidence", ""),
                "timestamp": norm_ts(r.get("timestamp", "")),
                "suggestion": r.get("suggestion", ""),
            })
    return out
