"""
Опциональный модуль: сопоставление слайдов PPTX с моментами урока.

ВАЖНО (см. обсуждение в чате): это самый низкоточный модуль в системе.
Реального таймкода "когда показан слайд" в pptx нет, поэтому используется
эвристика: TF-IDF сходство текста слайда с текстом сегментов транскрипта,
с ограничением на монотонный порядок (слайды по умолчанию показываются
по порядку, не вперёд-назад). В отчёте эта привязка должна маркироваться
как "AI-estimated", а не как факт - см. report.py и шаблон.
"""

from __future__ import annotations

from pptx import Presentation
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from common import Utterance


def extract_slide_texts(pptx_path: str) -> list[str]:
    prs = Presentation(pptx_path)
    slide_texts = []
    for slide in prs.slides:
        chunks = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs)
                    if text.strip():
                        chunks.append(text.strip())
        slide_texts.append(" ".join(chunks))
    return slide_texts


def estimate_slide_timeline(
    slide_texts: list[str],
    utterances: list[Utterance],
    min_similarity: float = 0.05,
) -> list[dict]:
    """
    Возвращает список {slide_index, estimated_start, estimated_end, confidence}.

    Алгоритм: жадный монотонный поиск. Для слайда i ищем окно реплик учителя
    (после конца окна слайда i-1), максимизирующее среднее косинусное сходство
    TF-IDF с текстом слайда. Слайды без разумного совпадения (ниже
    min_similarity) помечаются confidence=0 и не привязываются к времени -
    честнее показать "неизвестно", чем выдумать таймкод.
    """
    if not slide_texts or not utterances:
        return []

    teacher_utts = [u for u in utterances if u.speaker == "Teacher"]
    if not teacher_utts:
        return []

    corpus = slide_texts + [u.text for u in teacher_utts]
    # analyzer="char_wb" (символьные n-граммы) вместо словных токенов:
    # устойчивее к русской/казахской морфологии (склонения, спряжения)
    # без необходимости подключать отдельный лемматизатор.
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    tfidf = vectorizer.fit_transform(corpus)

    slide_vecs = tfidf[: len(slide_texts)]
    utt_vecs = tfidf[len(slide_texts):]

    sims = cosine_similarity(slide_vecs, utt_vecs)  # [n_slides, n_utts]

    results = []
    cursor = 0  # индекс реплики, с которого можно начинать поиск следующего слайда

    for i in range(len(slide_texts)):
        window_sims = sims[i, cursor:]
        if window_sims.size == 0 or window_sims.max() < min_similarity:
            results.append(
                {"slide_index": i, "estimated_start": None, "estimated_end": None, "confidence": 0.0}
            )
            continue

        best_j = int(np.argmax(window_sims)) + cursor
        start_time = teacher_utts[best_j].start

        # Конец окна слайда = начало следующего найденного слайда, либо конец урока.
        end_time = None
        for k in range(i + 1, len(slide_texts)):
            future_sims = sims[k, best_j:]
            if future_sims.size and future_sims.max() >= min_similarity:
                next_j = int(np.argmax(future_sims)) + best_j
                end_time = teacher_utts[next_j].start
                break
        if end_time is None:
            end_time = teacher_utts[-1].end

        results.append(
            {
                "slide_index": i,
                "estimated_start": round(start_time, 1),
                "estimated_end": round(end_time, 1),
                "confidence": round(float(window_sims.max()), 2),
            }
        )
        cursor = best_j

    return results
