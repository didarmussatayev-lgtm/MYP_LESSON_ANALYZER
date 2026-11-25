"""
FastAPI-приложение: вход, история уроков, загрузка, фоновая обработка,
веб-отчёт и скачивание docx.

Устройство:
- Состояние (пользователи, сессии, уроки, результаты анализа) хранится в
  SQLite в DATA_DIR (app/db.py). На Railway DATA_DIR должен указывать на
  подключённый Volume, иначе данные теряются при каждом редеплое.
- Обработка урока идёт в фоновом потоке (ThreadPoolExecutor, 1 воркер):
  урок обрабатывается минуты, HTTP-запрос столько ждать не может.
  Интерфейс опрашивает GET /api/lessons/{id}.
- Если сервер перезапустился посреди обработки, при старте незавершённые
  уроки ставятся в очередь заново с resume=True: уже пройденные этапы
  (включая платную транскрипцию) берутся из workdir и не оплачиваются
  повторно.
- Аудио удаляется сразу после успешной обработки (голоса детей).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(APP_DIR))

import auth  # noqa: E402
import db  # noqa: E402
import pipeline  # noqa: E402
import recordings  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", str(APP_DIR))).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"
WORK_DIR = DATA_DIR / "work"
DB_PATH = DATA_DIR / "myp_analyzer.sqlite3"
TEMPLATE_PATH = BASE_DIR / "templates" / "lesson_report_template.docx"
TAXONOMY_PATH = BASE_DIR / "config" / "taxonomy.yaml"
SUBJECT_FRAMEWORKS_PATH = BASE_DIR / "config" / "subject_frameworks.yaml"

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".oga", ".opus", ".flac", ".webm", ".mp4", ".amr", ".3gp"}

for d in (UPLOADS_DIR, OUTPUT_DIR, WORK_DIR):
    d.mkdir(parents=True, exist_ok=True)

db.init(DB_PATH)
auth.bootstrap_admin()
recordings.init(DATA_DIR)

executor = ThreadPoolExecutor(max_workers=1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _resume_unfinished()
    yield


app = FastAPI(title="MYP Lesson Analyzer", docs_url=None, redoc_url=None, lifespan=lifespan)


# ---------------------------------------------------------------------------
# Фоновая обработка
# ---------------------------------------------------------------------------

def _friendly_error(exc: Exception) -> str:
    """Короткое объяснение для учителя; полный traceback видит только администратор."""
    text = str(exc)
    if "GEMINI_API_KEY" in text:
        return "Сервис анализа не настроен: не задан ключ Gemini API. Сообщите администратору."
    if "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        return "Сервис распознавания временно перегружен или исчерпан лимит. Попробуйте запустить анализ повторно через несколько минут."
    if "не-JSON" in text:
        return "Модель вернула некорректный ответ на одном из этапов. Запустите анализ повторно — уже пройденные этапы не будут оплачены заново."
    if any(s in text.lower() for s in ("decode", "ffmpeg", "audio", "format")):
        return "Не удалось прочитать аудиофайл. Проверьте, что файл открывается и не повреждён (поддерживаются mp3, m4a, wav, ogg, webm)."
    if any(s in text.lower() for s in ("timeout", "connection", "unavailable", "503", "500")):
        return "Сервис распознавания не ответил вовремя. Запустите анализ повторно — уже пройденные этапы сохранены."
    return "При обработке урока произошла ошибка. Запустите анализ повторно; если ошибка повторится — сообщите администратору."


def _run_lesson(lesson_id: str, resume: bool = False) -> None:
    lesson = db.get_lesson(lesson_id)
    if lesson is None:
        return
    paths = lesson["upload_paths"]
    teacher_path = Path(paths["teacher"])
    classroom_path = Path(paths["classroom"]) if paths.get("classroom") else None
    pptx_path = Path(paths["pptx"]) if paths.get("pptx") else None
    planned_path = Path(paths["planned"])

    if not teacher_path.exists():
        db.update_lesson(
            lesson_id,
            status="error",
            error_public="Аудиофайл урока не найден на сервере (возможно, был удалён). Загрузите урок заново.",
            error_detail=f"missing {teacher_path}",
        )
        return

    db.update_lesson(lesson_id, status="running", error_public=None, error_detail=None)

    def on_progress(msg: str) -> None:
        db.append_progress(lesson_id, msg)

    def on_step(step: int, total: int, label: str) -> None:
        db.update_lesson(lesson_id, step=step, step_total=total, step_label=label)

    out_path = OUTPUT_DIR / f"{lesson_id}.docx"
    try:
        results = pipeline.run_pipeline(
            teacher_track=str(teacher_path),
            classroom_track=str(classroom_path) if classroom_path else None,
            planned_lesson_path=str(planned_path),
            out_path=str(out_path),
            pptx_path=str(pptx_path) if pptx_path else None,
            workdir=str(WORK_DIR / lesson_id),
            resume=resume,
            taxonomy_path=str(TAXONOMY_PATH),
            template_path=str(TEMPLATE_PATH),
            subject_frameworks_path=str(SUBJECT_FRAMEWORKS_PATH),
            subject_key=lesson["subject_key"] or None,
            on_progress=on_progress,
            on_step=on_step,
        )
    except Exception as e:  # noqa: BLE001 - любую ошибку показываем в статусе урока
        db.update_lesson(
            lesson_id,
            status="error",
            error_public=_friendly_error(e),
            error_detail=f"{e}\n\n{traceback.format_exc()}",
        )
        # Аудио и workdir НЕ удаляем: пользователь может нажать «Повторить»,
        # и пайплайн продолжит с последнего успешного этапа.
        return

    db.update_lesson(
        lesson_id,
        status="done",
        results=results,
        report_path=str(out_path),
        finished_at=time.time(),
        upload_paths={},
    )
    _delete_sources(lesson_id)


def _delete_sources(lesson_id: str) -> None:
    """Удаляет аудио/слайды и промежуточные файлы. Отчёт и результаты остаются."""
    shutil.rmtree(UPLOADS_DIR / lesson_id, ignore_errors=True)
    shutil.rmtree(WORK_DIR / lesson_id, ignore_errors=True)


def _resume_unfinished() -> None:
    for lesson in db.unfinished_lessons():
        db.append_progress(lesson["id"], "Сервер перезапустился — обработка продолжена с последнего завершённого этапа.")
        db.update_lesson(lesson["id"], status="queued")
        executor.submit(_run_lesson, lesson["id"], True)


# ---------------------------------------------------------------------------
# Страница и справочники
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/api/form-options")
async def get_form_options(user: dict = Depends(auth.current_user)) -> dict:
    """Справочники формы - единый источник правды с промптами бэкенда."""
    with open(SUBJECT_FRAMEWORKS_PATH, encoding="utf-8") as f:
        frameworks = yaml.safe_load(f)
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        taxonomy = yaml.safe_load(f)
    return {
        "key_concepts": frameworks["key_concepts"],
        "global_contexts": frameworks["global_contexts"],
        "learner_profile_attributes": frameworks["learner_profile_attributes"],
        "subjects": frameworks["subjects"],
        "atl_skill_clusters": taxonomy["atl_skill_clusters"],
        "question_categories": {
            k: v["definition"].strip() for k, v in taxonomy["question_categories"].items()
        },
        "inquiry_levels": {
            k: {"name": v["name"], "definition": v["definition"].strip()}
            for k, v in taxonomy["inquiry_levels"].items()
        },
    }


# ---------------------------------------------------------------------------
# Вход / выход / профиль
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
async def login(body: LoginBody, request: Request) -> JSONResponse:
    email = body.email.strip().lower()
    auth.check_rate_limit(email)
    user = db.get_user_by_email(email)
    if user is None or not user["is_active"] or not auth.verify_password(body.password, user["password_hash"]):
        auth.register_failure(email)
        raise HTTPException(401, "Неверный email или пароль.")
    auth.clear_failures(email)
    response = JSONResponse({"user": auth.public_user(user)})
    auth.start_session(response, request, user["id"])
    return response


@app.post("/api/auth/logout")
async def logout(request: Request) -> JSONResponse:
    response = JSONResponse({"ok": True})
    auth.end_session(response, request)
    return response


@app.get("/api/auth/me")
async def me(request: Request) -> dict:
    try:
        user = auth.current_user(request)
    except HTTPException:
        return {"user": None, "needs_setup": db.count_users() == 0}
    return {"user": auth.public_user(user)}


class PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/password")
async def change_password(body: PasswordChangeBody, user: dict = Depends(auth.current_user)) -> dict:
    if not auth.verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(400, "Текущий пароль указан неверно.")
    auth.validate_new_password(body.new_password)
    db.update_user(user["id"], password_hash=auth.hash_password(body.new_password))
    return {"ok": True}


class ProfileBody(BaseModel):
    name: str


@app.post("/api/auth/profile")
async def update_profile(body: ProfileBody, user: dict = Depends(auth.current_user)) -> dict:
    db.update_user(user["id"], name=body.name.strip())
    return {"ok": True}


# ---------------------------------------------------------------------------
# Пользователи (администратор)
# ---------------------------------------------------------------------------

class NewUserBody(BaseModel):
    email: str
    name: str = ""
    role: str = "teacher"
    password: str


@app.get("/api/users")
async def users_list(admin: dict = Depends(auth.require_admin)) -> dict:
    return {"users": db.list_users()}


@app.post("/api/users")
async def users_create(body: NewUserBody, admin: dict = Depends(auth.require_admin)) -> dict:
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Некорректный email.")
    if body.role not in ("teacher", "admin"):
        raise HTTPException(400, "Неизвестная роль.")
    if db.get_user_by_email(email):
        raise HTTPException(409, "Пользователь с таким email уже существует.")
    auth.validate_new_password(body.password)
    user_id = db.create_user(email, body.name, auth.hash_password(body.password), body.role)
    return {"id": user_id}


class UserPatchBody(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


@app.patch("/api/users/{user_id}")
async def users_update(user_id: int, body: UserPatchBody, admin: dict = Depends(auth.require_admin)) -> dict:
    target = db.get_user(user_id)
    if target is None:
        raise HTTPException(404, "Пользователь не найден.")
    if user_id == admin["id"] and (body.is_active is False or (body.role and body.role != "admin")):
        raise HTTPException(400, "Нельзя отключить или понизить собственную учётную запись.")
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.role is not None:
        if body.role not in ("teacher", "admin"):
            raise HTTPException(400, "Неизвестная роль.")
        fields["role"] = body.role
    if body.is_active is not None:
        fields["is_active"] = 1 if body.is_active else 0
    if body.password:
        auth.validate_new_password(body.password)
        fields["password_hash"] = auth.hash_password(body.password)
    db.update_user(user_id, **fields)
    if body.is_active is False or body.password:
        db.delete_user_sessions(user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Уроки
# ---------------------------------------------------------------------------

def _get_owned_lesson(lesson_id: str, user: dict) -> dict:
    lesson = db.get_lesson(lesson_id)
    if lesson is None or (lesson["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "Урок не найден.")
    return lesson


def _save_upload(upload: UploadFile, dest_dir: Path, prefix: str, allowed_ext: set[str] | None) -> Path:
    ext = Path(upload.filename or "").suffix.lower()
    ext = re.sub(r"[^a-z0-9.]", "", ext)
    if allowed_ext is not None and ext not in allowed_ext:
        raise HTTPException(400, f"Формат файла «{upload.filename}» не поддерживается.")
    # Имя - только uuid + расширение: исходные имена с кириллицей и пробелами
    # ломали Gemini SDK (угадывание MIME и HTTP-заголовки).
    dest = dest_dir / f"{prefix}_{uuid.uuid4().hex}{ext or '.bin'}"
    written = 0
    with open(dest, "wb") as f:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"Файл «{upload.filename}» больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ.")
            f.write(chunk)
    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Файл «{upload.filename}» пустой.")
    return dest


PLANNED_FIELDS = [
    "key_concept", "related_concept", "global_context", "statement_of_inquiry",
    "inquiry_questions", "learning_objectives", "atl_skills", "learner_profile",
    "assessment_criteria", "learning_experiences",
]


@app.post("/api/lessons")
async def create_lesson(
    teacher_track: UploadFile | None = File(None),
    recording_id: str = Form(""),
    classroom_track: UploadFile | None = File(None),
    pptx: UploadFile | None = File(None),
    teacher_name: str = Form(""),
    subject: str = Form(""),
    subject_key: str = Form(""),
    lesson_date: str = Form(""),
    lesson_title: str = Form(""),
    grade: str = Form(""),
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
    user: dict = Depends(auth.current_user),
) -> dict:
    lesson_id = uuid.uuid4().hex
    job_dir = UPLOADS_DIR / lesson_id
    job_dir.mkdir(parents=True, exist_ok=True)
    has_file = teacher_track is not None and bool(teacher_track.filename)
    if not has_file and not recording_id:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, "Добавьте запись учителя: файл или запись, сделанную на сайте.")
    try:
        paths: dict[str, str] = {}
        if has_file:
            paths["teacher"] = str(_save_upload(teacher_track, job_dir, "teacher", AUDIO_EXTENSIONS))
        if classroom_track is not None and classroom_track.filename:
            paths["classroom"] = str(_save_upload(classroom_track, job_dir, "classroom", AUDIO_EXTENSIONS))
        if pptx is not None and pptx.filename:
            paths["pptx"] = str(_save_upload(pptx, job_dir, "slides", {".pptx"}))
        # Запись с сайта забираем последней: если до этого что-то не прошло
        # проверку, она остаётся нетронутой и её можно использовать снова.
        if not has_file:
            paths["teacher"] = str(recordings.take_for_lesson(recording_id, user, job_dir, lesson_id))
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    teacher_name = teacher_name.strip() or user["name"]
    meta = {
        "teacher_name": teacher_name,
        "subject": subject.strip(),
        "subject_key": subject_key,
        "lesson_date": lesson_date.strip(),
        "lesson_title": lesson_title.strip(),
        "grade": grade.strip(),
    }
    planned_values = {
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
    planned = {
        **{k: meta[k] for k in ("teacher_name", "subject", "lesson_date")},
        **{f: planned_values[f].strip() for f in PLANNED_FIELDS},
    }
    planned_path = job_dir / "planned_lesson.yaml"
    with open(planned_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(planned, f, allow_unicode=True)
    paths["planned"] = str(planned_path)

    db.create_lesson(lesson_id, user["id"], meta, planned, paths)
    executor.submit(_run_lesson, lesson_id, False)
    return {"id": lesson_id}


@app.get("/api/lessons")
async def lessons_list(scope: str = "mine", user: dict = Depends(auth.current_user)) -> dict:
    all_lessons = scope == "all" and user["role"] == "admin"
    return {"lessons": db.list_lessons(None if all_lessons else user["id"])}


@app.get("/api/lessons/{lesson_id}")
async def lesson_detail(lesson_id: str, user: dict = Depends(auth.current_user)) -> dict:
    lesson = _get_owned_lesson(lesson_id, user)
    lesson.pop("upload_paths", None)
    lesson.pop("report_path", None)
    if user["role"] != "admin":
        lesson.pop("error_detail", None)
    owner = db.get_user(lesson["user_id"])
    lesson["owner_name"] = owner["name"] if owner else ""
    lesson["can_retry"] = lesson["status"] == "error"
    return {"lesson": lesson}


@app.post("/api/lessons/{lesson_id}/retry")
async def lesson_retry(lesson_id: str, user: dict = Depends(auth.current_user)) -> dict:
    lesson = _get_owned_lesson(lesson_id, user)
    if lesson["status"] != "error":
        raise HTTPException(409, "Повторный запуск возможен только после ошибки.")
    db.update_lesson(lesson_id, status="queued", error_public=None, error_detail=None)
    db.append_progress(lesson_id, "Повторный запуск анализа.")
    executor.submit(_run_lesson, lesson_id, True)
    return {"ok": True}


@app.delete("/api/lessons/{lesson_id}")
async def lesson_delete(lesson_id: str, user: dict = Depends(auth.current_user)) -> Response:
    lesson = _get_owned_lesson(lesson_id, user)
    if lesson["status"] in ("queued", "running"):
        raise HTTPException(409, "Урок ещё обрабатывается. Удалить можно после завершения.")
    _delete_sources(lesson_id)
    (OUTPUT_DIR / f"{lesson_id}.docx").unlink(missing_ok=True)
    db.delete_lesson(lesson_id)
    return Response(status_code=204)


@app.get("/api/lessons/{lesson_id}/report.docx")
async def lesson_download(lesson_id: str, user: dict = Depends(auth.current_user)) -> FileResponse:
    lesson = _get_owned_lesson(lesson_id, user)
    path = lesson.get("report_path")
    if lesson["status"] != "done" or not path or not Path(path).exists():
        raise HTTPException(409, "Отчёт ещё не готов.")
    parts = [lesson["lesson_date"], lesson["subject"], lesson["teacher_name"]]
    stem = "_".join(re.sub(r"[^\w\-]+", "-", p).strip("-") for p in parts if p) or "lesson"
    return FileResponse(
        path,
        filename=f"{stem}_report.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


app.include_router(recordings.router)


# ---------------------------------------------------------------------------
# Автозаполнение плана урока из unit planner
# ---------------------------------------------------------------------------

PLANNER_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}


@app.post("/api/planner/extract")
async def planner_extract(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    subject_key: str = Form(""),
    user: dict = Depends(auth.current_user),
) -> dict:
    import planner  # noqa: PLC0415 - тянет google-genai, грузим по требованию

    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in PLANNER_EXTENSIONS:
            raise HTTPException(400, "Поддерживаются файлы .docx, .pdf и .txt. Google Doc можно скачать как .docx.")
        data = file.file.read(25 * 1024 * 1024 + 1)
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, "Файл больше 25 МБ.")
        source = {"bytes": data, "ext": ext}
    elif text.strip():
        source = {"text": text.strip()[:60000]}
    else:
        raise HTTPException(400, "Прикрепите файл unit planner или вставьте его текст.")

    with open(SUBJECT_FRAMEWORKS_PATH, encoding="utf-8") as f:
        frameworks = yaml.safe_load(f)
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        taxonomy = yaml.safe_load(f)
    try:
        fields = await run_in_threadpool(planner.extract_planner, source, frameworks, taxonomy, subject_key or None)
    except planner.PlannerError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, _friendly_error(e)) from e
    return {"fields": fields}


app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
