"""
FastAPI-обёртка вокруг src/pipeline.py.

Архитектура (см. обсуждение в чате):
- Браузер загружает файлы через multipart-форму -> POST /jobs
- Обработка запускается в фоновом потоке (ThreadPoolExecutor), не в
  синхронном HTTP-запросе - урок обрабатывается минуты, HTTP-таймаут
  этого не выдержит.
- Браузер опрашивает GET /jobs/{id} для статуса, затем скачивает результат
  через GET /jobs/{id}/download.
- Состояние задач хранится в памяти процесса (JOBS dict) - для личного
  использования одним учителем этого достаточно. Ограничение: при
  рестарте сервиса информация о задачах в процессе теряется (сами
  готовые docx-файлы на диске/volume не удаляются, кроме файла-источника
  аудио - см. _cleanup_job).
"""

from __future__ import annotations

import shutil
import sys
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# src/ содержит весь пайплайн - добавляем в путь импорта
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

import pipeline  # noqa: E402  (импорт после sys.path.insert - осознанно)

APP_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = APP_DIR / "uploads"
OUTPUT_DIR = APP_DIR / "output"
WORK_DIR = APP_DIR / "work"
TEMPLATE_PATH = BASE_DIR / "templates" / "lesson_report_template.docx"
TAXONOMY_PATH = BASE_DIR / "config" / "taxonomy.yaml"

for d in (UPLOADS_DIR, OUTPUT_DIR, WORK_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MYP Lesson Analyzer")
executor = ThreadPoolExecutor(max_workers=1)  # 1 воркер: обработка урока и так тяжёлая по I/O к Gemini


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error
    progress_log: list[str] = field(default_factory=list)
    error: str | None = None
    report_path: str | None = None


JOBS: dict[str, Job] = {}


def _run_job(job_id: str, teacher_path: Path, classroom_path: Path, planned_path: Path, pptx_path: Path | None) -> None:
    job = JOBS[job_id]
    job.status = "running"

    def on_progress(msg: str) -> None:
        job.progress_log.append(msg)

    try:
        out_path = OUTPUT_DIR / f"{job_id}.docx"
        pipeline.run_pipeline(
            teacher_track=str(teacher_path),
            classroom_track=str(classroom_path),
            planned_lesson_path=str(planned_path),
            out_path=str(out_path),
            pptx_path=str(pptx_path) if pptx_path else None,
            workdir=str(WORK_DIR / job_id),
            taxonomy_path=str(TAXONOMY_PATH),
            template_path=str(TEMPLATE_PATH),
            on_progress=on_progress,
        )
        job.report_path = str(out_path)
        job.status = "done"
    except Exception as e:  # noqa: BLE001 - хотим поймать всё и показать в статусе задачи
        job.error = f"{e}\n\n{traceback.format_exc()}"
        job.status = "error"
    finally:
        # Аудиофайлы содержат голоса детей - удаляем сразу после обработки,
        # не храним дольше необходимого (см. README, раздел про приватность).
        for p in (teacher_path, classroom_path, pptx_path):
            if p and p.exists():
                p.unlink(missing_ok=True)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = APP_DIR / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/jobs")
async def create_job(
    teacher_track: UploadFile = File(...),
    classroom_track: UploadFile = File(...),
    pptx: UploadFile | None = File(None),
    teacher_name: str = Form(""),
    subject: str = Form(""),
    lesson_date: str = Form(""),
    key_concept: str = Form(""),
    related_concept: str = Form(""),
    global_context: str = Form(""),
    statement_of_inquiry: str = Form(""),
    inquiry_questions: str = Form(""),
    learning_objectives: str = Form(""),
    atl_skills: str = Form(""),
    learner_profile: str = Form(""),
    assessment_criteria: str = Form(""),
    learning_experiences: str = Form(""),
) -> dict:
    job_id = str(uuid.uuid4())
    job_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    teacher_path = job_dir / f"teacher_{teacher_track.filename}"
    classroom_path = job_dir / f"classroom_{classroom_track.filename}"
    with open(teacher_path, "wb") as f:
        shutil.copyfileobj(teacher_track.file, f)
    with open(classroom_path, "wb") as f:
        shutil.copyfileobj(classroom_track.file, f)

    pptx_path = None
    if pptx is not None and pptx.filename:
        pptx_path = job_dir / f"slides_{pptx.filename}"
        with open(pptx_path, "wb") as f:
            shutil.copyfileobj(pptx.file, f)

    planned = {
        "teacher_name": teacher_name,
        "subject": subject,
        "lesson_date": lesson_date,
        "key_concept": key_concept,
        "related_concept": related_concept,
        "global_context": global_context,
        "statement_of_inquiry": statement_of_inquiry,
        "inquiry_questions": inquiry_questions,
        "learning_objectives": learning_objectives,
        "atl_skills": atl_skills,
        "learner_profile": learner_profile,
        "assessment_criteria": assessment_criteria,
        "learning_experiences": learning_experiences,
    }
    planned_path = job_dir / "planned_lesson.yaml"
    with open(planned_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(planned, f, allow_unicode=True)

    JOBS[job_id] = Job(id=job_id)
    executor.submit(_run_job, job_id, teacher_path, classroom_path, planned_path, pptx_path)

    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "status": job.status,
        "progress_log": job.progress_log,
        "error": job.error,
        "download_ready": job.status == "done",
    }


@app.get("/jobs/{job_id}/download")
async def download_job(job_id: str) -> FileResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.report_path:
        raise HTTPException(status_code=409, detail=f"Job not ready (status={job.status})")
    return FileResponse(
        job.report_path,
        filename="lesson_observation_report.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
