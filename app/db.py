"""
Постоянное хранилище приложения: SQLite (стандартная библиотека, без
отдельного сервера БД).

Почему SQLite, а не Postgres: нагрузка - десятки уроков в неделю, один
процесс uvicorn. SQLite в WAL-режиме с этим справляется, а деплой остаётся
одним контейнером. Файл БД лежит в DATA_DIR - на Railway это должен быть
подключённый Volume, иначе при каждом редеплое данные пропадут (см. README).

Каждая функция открывает своё короткое соединение: пайплайн работает в
фоновом потоке, а sqlite3-соединение нельзя безопасно делить между потоками.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_DB_PATH: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'teacher',   -- teacher | admin
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id                  TEXT PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | error
    step                INTEGER NOT NULL DEFAULT 0,
    step_total          INTEGER NOT NULL DEFAULT 0,
    step_label          TEXT NOT NULL DEFAULT '',
    progress_log        TEXT NOT NULL DEFAULT '[]',
    error_public        TEXT,
    error_detail        TEXT,
    teacher_name        TEXT NOT NULL DEFAULT '',
    subject             TEXT NOT NULL DEFAULT '',
    subject_key         TEXT NOT NULL DEFAULT '',
    lesson_date         TEXT NOT NULL DEFAULT '',
    lesson_title        TEXT NOT NULL DEFAULT '',
    grade               TEXT NOT NULL DEFAULT '',
    planned             TEXT NOT NULL DEFAULT '{}',
    results             TEXT,
    report_path         TEXT,
    upload_paths        TEXT NOT NULL DEFAULT '{}',
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    finished_at         REAL
);

CREATE INDEX IF NOT EXISTS idx_lessons_user ON lessons(user_id, created_at DESC);
"""


def init(db_path: Path) -> None:
    global _DB_PATH
    _DB_PATH = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    if _DB_PATH is None:
        raise RuntimeError("db.init() не вызван")
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------

def count_users() -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(email: str, name: str, password_hash: str, role: str) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (email.strip().lower(), name.strip(), password_hash, role, time.time()),
        )
        return int(cur.lastrowid)


def get_user(user_id: int) -> dict | None:
    with connect() as c:
        return _row(c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_email(email: str) -> dict | None:
    with connect() as c:
        return _row(
            c.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        )


def list_users() -> list[dict]:
    with connect() as c:
        rows = c.execute(
            """
            SELECT u.id, u.email, u.name, u.role, u.is_active, u.created_at,
                   (SELECT COUNT(*) FROM lessons l WHERE l.user_id = u.id) AS lesson_count
            FROM users u ORDER BY u.created_at
            """
        ).fetchall()
        return [dict(r) for r in rows]


def update_user(user_id: int, **fields: Any) -> None:
    allowed = {"name", "role", "is_active", "password_hash"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = ?" for k in sets)
    with connect() as c:
        c.execute(f"UPDATE users SET {cols} WHERE id = ?", (*sets.values(), user_id))


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def create_session(token_hash: str, user_id: int, ttl_seconds: float) -> None:
    now = time.time()
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now, now + ttl_seconds),
        )


def get_session_user(token_hash: str) -> dict | None:
    with connect() as c:
        row = c.execute(
            """
            SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1
            """,
            (token_hash, time.time()),
        ).fetchone()
        return _row(row)


def delete_session(token_hash: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_user_sessions(user_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------------------
# lessons
# ---------------------------------------------------------------------------

_JSON_COLS = ("progress_log", "planned", "results", "upload_paths")


def _decode_lesson(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for col in _JSON_COLS:
        if col in d and d[col] is not None:
            d[col] = json.loads(d[col])
    return d


def create_lesson(lesson_id: str, user_id: int, meta: dict, planned: dict, upload_paths: dict) -> None:
    now = time.time()
    with connect() as c:
        c.execute(
            """
            INSERT INTO lessons (id, user_id, teacher_name, subject, subject_key, lesson_date,
                                 lesson_title, grade, planned, upload_paths, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lesson_id,
                user_id,
                meta.get("teacher_name", ""),
                meta.get("subject", ""),
                meta.get("subject_key", ""),
                meta.get("lesson_date", ""),
                meta.get("lesson_title", ""),
                meta.get("grade", ""),
                json.dumps(planned, ensure_ascii=False),
                json.dumps(upload_paths, ensure_ascii=False),
                now,
                now,
            ),
        )


def get_lesson(lesson_id: str) -> dict | None:
    with connect() as c:
        return _decode_lesson(c.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone())


def list_lessons(user_id: int | None) -> list[dict]:
    """user_id=None - все уроки (для администратора)."""
    cols = """l.id, l.user_id, l.status, l.step, l.step_total, l.teacher_name, l.subject,
              l.subject_key, l.lesson_date, l.lesson_title, l.grade, l.created_at,
              l.finished_at, l.results, u.name AS owner_name, u.email AS owner_email"""
    with connect() as c:
        if user_id is None:
            rows = c.execute(
                f"SELECT {cols} FROM lessons l JOIN users u ON u.id = l.user_id ORDER BY l.created_at DESC"
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT {cols} FROM lessons l JOIN users u ON u.id = l.user_id "
                "WHERE l.user_id = ? ORDER BY l.created_at DESC",
                (user_id,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        results = json.loads(d.pop("results")) if d.get("results") else None
        d["summary"] = (results or {}).get("summary")
        out.append(d)
    return out


def update_lesson(lesson_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    for col in _JSON_COLS:
        if col in fields and not isinstance(fields[col], str) and fields[col] is not None:
            fields[col] = json.dumps(fields[col], ensure_ascii=False)
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE lessons SET {cols} WHERE id = ?", (*fields.values(), lesson_id))


def append_progress(lesson_id: str, message: str) -> None:
    with connect() as c:
        row = c.execute("SELECT progress_log FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        if row is None:
            return
        log = json.loads(row[0])
        log.append({"t": time.time(), "msg": message})
        c.execute(
            "UPDATE lessons SET progress_log = ?, updated_at = ? WHERE id = ?",
            (json.dumps(log, ensure_ascii=False), time.time(), lesson_id),
        )


def delete_lesson(lesson_id: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))


def unfinished_lessons() -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM lessons WHERE status IN ('queued', 'running') ORDER BY created_at"
        ).fetchall()
        return [_decode_lesson(r) for r in rows]
