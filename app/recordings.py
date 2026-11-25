"""
Запись урока прямо на сайте.

Как это работает:
- Браузер пишет звук через MediaRecorder и каждые несколько секунд
  отправляет очередной кусок на сервер (PUT /api/recordings/{id}/chunks/{segment}/{seq}).
  Если связь пропала — кусок ждёт в очереди браузера и отправляется позже;
  если вкладка закрылась — всё, что уже дошло до сервера, сохранено.
- Сегмент — одна непрерывная сессия MediaRecorder. Если запись прервалась
  (iPhone заблокировали, микрофон отобрало другое приложение, страницу
  перезагрузили), браузер начинает новый сегмент в той же записи.
- POST /finish проверяет, что все куски дошли, склеивает каждый сегмент,
  а затем все сегменты через ffmpeg в один mono mp3: этот формат надёжно
  понимают и ffprobe, и Gemini (webm из MediaRecorder часто без длительности
  в заголовке, а Gemini webm не принимает).
- Готовая запись подставляется в новый анализ как запись учителя
  (POST /api/lessons с recording_id) и после этого удаляется отсюда.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth
import db

router = APIRouter(prefix="/api/recordings")

RECORDINGS_DIR: Path = Path("recordings")  # переопределяется в init()
MAX_CHUNK_BYTES = 20 * 1024 * 1024
_finalizer = ThreadPoolExecutor(max_workers=1)
_lock = threading.Lock()

_EXT_BY_MIME = {"webm": ".webm", "mp4": ".mp4", "ogg": ".ogg", "mpeg": ".mp3", "wav": ".wav", "aac": ".aac"}


def init(data_dir: Path) -> None:
    global RECORDINGS_DIR
    RECORDINGS_DIR = data_dir / "recordings"
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    # Если сервер перезапустился во время склейки — повторяем её.
    for user_rec in _all_with_status("finalizing"):
        _finalizer.submit(_finalize, user_rec["id"])


def _all_with_status(status: str) -> list[dict]:
    with db.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM recordings WHERE status = ?", (status,)).fetchall()]


def _rec_dir(rec_id: str) -> Path:
    return RECORDINGS_DIR / rec_id


def _ext_for(mime: str) -> str:
    for key, ext in _EXT_BY_MIME.items():
        if key in mime:
            return ext
    return ".bin"


def _owned(rec_id: str, user: dict) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", rec_id):
        raise HTTPException(404, "Запись не найдена.")
    rec = db.get_recording(rec_id)
    if rec is None or rec["user_id"] != user["id"]:
        raise HTTPException(404, "Запись не найдена.")
    return rec


def _segments_on_disk(rec_id: str) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    base = _rec_dir(rec_id)
    if not base.exists():
        return out
    for seg_dir in base.glob("seg*"):
        m = re.fullmatch(r"seg(\d+)", seg_dir.name)
        if not m or not seg_dir.is_dir():
            continue
        seqs = sorted(int(p.stem) for p in seg_dir.glob("*.part"))
        out[int(m.group(1))] = seqs
    return out


def _public(rec: dict) -> dict:
    segs = _segments_on_disk(rec["id"]) if rec["status"] == "recording" else {}
    return {
        "id": rec["id"],
        "status": rec["status"],
        "mime": rec["mime"],
        "bytes_received": rec["bytes_received"],
        "duration_seconds": rec["duration_seconds"],
        "error": rec["error"],
        "created_at": rec["created_at"],
        "segments": {str(k): {"count": len(v), "max_seq": (v[-1] if v else -1)} for k, v in segs.items()},
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class CreateBody(BaseModel):
    mime: str = ""


@router.post("")
async def create(body: CreateBody, user: dict = Depends(auth.current_user)) -> dict:
    rec_id = uuid.uuid4().hex
    _rec_dir(rec_id).mkdir(parents=True, exist_ok=True)
    db.create_recording(rec_id, user["id"], body.mime[:100])
    return {"id": rec_id}


@router.get("")
async def list_mine(user: dict = Depends(auth.current_user)) -> dict:
    return {"recordings": [_public(r) for r in db.list_recordings(user["id"])]}


@router.get("/{rec_id}")
async def get_one(rec_id: str, user: dict = Depends(auth.current_user)) -> dict:
    return {"recording": _public(_owned(rec_id, user))}


@router.put("/{rec_id}/chunks/{segment}/{seq}")
async def put_chunk(rec_id: str, segment: int, seq: int, request: Request, user: dict = Depends(auth.current_user)) -> dict:
    rec = _owned(rec_id, user)
    if rec["status"] != "recording":
        raise HTTPException(409, "Запись уже завершена.")
    if not (0 <= segment < 1000 and 0 <= seq < 1_000_000):
        raise HTTPException(400, "Некорректный номер куска.")
    data = await request.body()
    if len(data) > MAX_CHUNK_BYTES:
        raise HTTPException(413, "Слишком большой кусок записи.")
    seg_dir = _rec_dir(rec_id) / f"seg{segment:03d}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    dest = seg_dir / f"{seq:06d}.part"
    # Повторная отправка того же куска (ответ потерялся в сети) — не ошибка.
    if dest.exists() and dest.stat().st_size == len(data):
        return {"ok": True, "duplicate": True}
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    db.add_recording_bytes(rec_id, len(data))
    return {"ok": True}


class FinishBody(BaseModel):
    # {"0": 41, "1": 7} — номер последнего куска в каждом сегменте
    segments: dict[str, int]


@router.post("/{rec_id}/finish")
async def finish(rec_id: str, body: FinishBody, user: dict = Depends(auth.current_user)) -> dict:
    rec = _owned(rec_id, user)
    if rec["status"] in ("finalizing", "ready"):
        return {"recording": _public(rec)}
    if rec["status"] != "recording":
        raise HTTPException(409, "Запись нельзя завершить в текущем состоянии.")
    on_disk = _segments_on_disk(rec_id)
    missing: list[list[int]] = []
    for seg_str, last in body.segments.items():
        seg = int(seg_str)
        have = set(on_disk.get(seg, []))
        missing += [[seg, s] for s in range(0, last + 1) if s not in have]
    if missing:
        raise HTTPException(409, {"message": "Не все куски записи дошли до сервера.", "missing": missing[:500]})
    if not any(on_disk.values()):
        raise HTTPException(400, "Запись пустая.")
    db.update_recording(rec_id, status="finalizing", error=None)
    _finalizer.submit(_finalize, rec_id)
    return {"recording": _public(db.get_recording(rec_id))}


@router.get("/{rec_id}/audio")
async def download(rec_id: str, user: dict = Depends(auth.current_user)) -> FileResponse:
    rec = _owned(rec_id, user)
    if rec["status"] != "ready" or not rec["audio_path"] or not Path(rec["audio_path"]).exists():
        raise HTTPException(409, "Запись ещё не готова.")
    stamp = re.sub(r"\D", "", str(int(rec["created_at"])))
    return FileResponse(rec["audio_path"], filename=f"lesson_recording_{stamp}.mp3", media_type="audio/mpeg")


@router.delete("/{rec_id}")
async def delete(rec_id: str, user: dict = Depends(auth.current_user)) -> dict:
    rec = _owned(rec_id, user)
    if rec["status"] == "finalizing":
        raise HTTPException(409, "Запись ещё обрабатывается. Подождите несколько секунд.")
    shutil.rmtree(_rec_dir(rec_id), ignore_errors=True)
    db.delete_recording(rec_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Склейка
# ---------------------------------------------------------------------------

def _finalize(rec_id: str) -> None:
    rec = db.get_recording(rec_id)
    if rec is None:
        return
    base = _rec_dir(rec_id)
    ext = _ext_for(rec["mime"])
    try:
        seg_files: list[Path] = []
        for seg, seqs in sorted(_segments_on_disk(rec_id).items()):
            if not seqs:
                continue
            seg_file = base / f"segment_{seg:03d}{ext}"
            with open(seg_file, "wb") as out:
                for s in seqs:
                    with open(base / f"seg{seg:03d}" / f"{s:06d}.part", "rb") as f:
                        shutil.copyfileobj(f, out)
            seg_files.append(seg_file)

        out_path = base / "lesson.mp3"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for f in seg_files:
            cmd += ["-i", str(f)]
        if len(seg_files) > 1:
            inputs = "".join(f"[{i}:a]" for i in range(len(seg_files)))
            cmd += ["-filter_complex", f"{inputs}concat=n={len(seg_files)}:v=0:a=1[a]", "-map", "[a]"]
        else:
            cmd += ["-vn"]
        cmd += ["-ac", "1", "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "48k", str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(out_path)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        duration = float(probe.stdout.strip() or 0)
    except Exception as e:  # noqa: BLE001
        detail = e.stderr.decode(errors="ignore")[-800:] if isinstance(e, subprocess.CalledProcessError) and e.stderr else str(e)
        db.update_recording(rec_id, status="error", error=f"Не удалось обработать запись: {detail}")
        return

    # Куски больше не нужны — оставляем только итоговый mp3.
    for p in base.iterdir():
        if p != out_path:
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    db.update_recording(rec_id, status="ready", audio_path=str(out_path), duration_seconds=duration)


def take_for_lesson(rec_id: str, user: dict, dest_dir: Path, lesson_id: str) -> Path:
    """Переносит готовую запись в папку урока и помечает её использованной."""
    with _lock:
        rec = _owned(rec_id, user)
        if rec["status"] != "ready" or not rec["audio_path"] or not Path(rec["audio_path"]).exists():
            raise HTTPException(409, "Запись ещё не готова или уже использована.")
        dest = dest_dir / f"teacher_{uuid.uuid4().hex}.mp3"
        shutil.move(rec["audio_path"], dest)
        shutil.rmtree(_rec_dir(rec_id), ignore_errors=True)
        db.update_recording(rec_id, status="used", audio_path=None, lesson_id=lesson_id)
        return dest
