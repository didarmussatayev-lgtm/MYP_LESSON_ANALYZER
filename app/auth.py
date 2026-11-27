"""
Аутентификация: email + пароль, серверные сессии в SQLite.

- Пароли хешируются scrypt (hashlib, стандартная библиотека) с солью.
- В cookie лежит случайный токен; в БД хранится только его SHA-256, так что
  утечка файла БД не даёт готовых сессий.
- Cookie: HttpOnly + SameSite=Lax (браузер не отправит её с чужого сайта
  при POST, это закрывает CSRF для нашего API) + Secure за HTTPS.
- Регистрации нет: учётные записи создаёт администратор. Первый администратор
  создаётся при старте из переменных ADMIN_EMAIL / ADMIN_PASSWORD.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time

from fastapi import HTTPException, Request, Response

import db

# teacher  — видит и анализирует только свои уроки;
# observer — методист/координатор: видит все уроки и динамику, комментирует;
# admin    — всё, что observer, плюс управление пользователями.
ROLES = ("teacher", "observer", "admin")

SESSION_COOKIE = "myp_session"
SESSION_TTL = 30 * 24 * 3600  # 30 дней

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def validate_new_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(400, "Пароль должен быть не короче 8 символов.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(response: Response, request: Request, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    db.create_session(_token_hash(token), user_id, SESSION_TTL)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )


def end_session(response: Response, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(_token_hash(token))
    response.delete_cookie(SESSION_COOKIE, path="/")


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def current_user(request: Request) -> dict:
    """FastAPI dependency: пользователь текущей сессии или 401."""
    token = request.cookies.get(SESSION_COOKIE)
    user = db.get_session_user(_token_hash(token)) if token else None
    if user is None:
        raise HTTPException(401, "Требуется вход.")
    return user


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Доступно только администратору.")
    return user


def can_view_all(user: dict) -> bool:
    return user["role"] in ("admin", "observer")


def public_user(user: dict) -> dict:
    out = {k: user[k] for k in ("id", "email", "name", "role")}
    out["ui_language"] = user.get("ui_language") or "ru"
    out["email_notifications"] = bool(user.get("email_notifications", 1))
    return out


# ---------------------------------------------------------------------------
# Защита от перебора пароля: после 5 неудачных попыток на email - пауза 5 минут.
# В памяти процесса: при рестарте счётчик сбрасывается, для одной школы этого
# достаточно.
# ---------------------------------------------------------------------------

_FAILS: dict[str, list[float]] = {}
_FAILS_LOCK = threading.Lock()
_MAX_FAILS, _WINDOW = 5, 300.0


def check_rate_limit(email: str) -> None:
    now = time.time()
    with _FAILS_LOCK:
        recent = [t for t in _FAILS.get(email, []) if now - t < _WINDOW]
        _FAILS[email] = recent
        if len(recent) >= _MAX_FAILS:
            raise HTTPException(429, "Слишком много попыток входа. Попробуйте через 5 минут.")


def register_failure(email: str) -> None:
    with _FAILS_LOCK:
        _FAILS.setdefault(email, []).append(time.time())


def clear_failures(email: str) -> None:
    with _FAILS_LOCK:
        _FAILS.pop(email, None)


def bootstrap_admin() -> None:
    """Создаёт первого администратора из env, если пользователей ещё нет."""
    if db.count_users() > 0:
        return
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        print(
            "[auth] Пользователей нет. Задайте ADMIN_EMAIL и ADMIN_PASSWORD, "
            "чтобы создать первого администратора."
        )
        return
    db.create_user(email, os.environ.get("ADMIN_NAME", "Администратор"), hash_password(password), "admin")
    print(f"[auth] Создан администратор {email}")
