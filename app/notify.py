"""
Уведомления: на сайте (колокольчик) и, если настроен SMTP, по почте.

Кому что приходит:
- comment       — новый комментарий к уроку: автору урока и всем, кто уже
                  писал в обсуждении (кроме самого автора комментария);
- lesson_done   — анализ урока готов: автору урока;
- lesson_error  — анализ остановился с ошибкой: автору урока.

Почта (необязательно): задайте SMTP_HOST, SMTP_PORT (587), SMTP_USER,
SMTP_PASSWORD, SMTP_FROM и APP_URL (адрес сайта для ссылок). Пользователь
может отключить письма в профиле. Письмо уходит в фоновом потоке и не
задерживает ответ сайта; ошибка отправки пишется в лог и ни на что не влияет.
"""

from __future__ import annotations

import os
import smtplib
import ssl
import traceback
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formataddr

import db

_mail_pool = ThreadPoolExecutor(max_workers=1)

SUBJECTS = {
    "comment": {
        "ru": "Новый комментарий к уроку «{lesson}»",
        "kk": "«{lesson}» сабағына жаңа пікір",
        "en": "New comment on “{lesson}”",
    },
    "lesson_done": {
        "ru": "Отчёт по уроку «{lesson}» готов",
        "kk": "«{lesson}» сабағы бойынша есеп дайын",
        "en": "Report for “{lesson}” is ready",
    },
    "lesson_error": {
        "ru": "Анализ урока «{lesson}» остановился",
        "kk": "«{lesson}» сабағын талдау тоқтады",
        "en": "Analysis of “{lesson}” stopped",
    },
}
BODIES = {
    "comment": {
        "ru": "{actor} оставил(а) комментарий:\n\n{excerpt}\n\nОткрыть обсуждение: {link}",
        "kk": "{actor} пікір қалдырды:\n\n{excerpt}\n\nТалқылауды ашу: {link}",
        "en": "{actor} left a comment:\n\n{excerpt}\n\nOpen the discussion: {link}",
    },
    "lesson_done": {
        "ru": "Анализ завершён. Открыть отчёт: {link}",
        "kk": "Талдау аяқталды. Есепті ашу: {link}",
        "en": "The analysis is complete. Open the report: {link}",
    },
    "lesson_error": {
        "ru": "Анализ остановился с ошибкой. Его можно перезапустить на странице урока: {link}",
        "kk": "Талдау қатемен тоқтады. Оны сабақ бетінде қайта іске қосуға болады: {link}",
        "en": "The analysis stopped with an error. You can restart it on the lesson page: {link}",
    },
}
FOOTER = {
    "ru": "\n\n—\nMYP Lesson Analyzer. Письма можно отключить в профиле.",
    "kk": "\n\n—\nMYP Lesson Analyzer. Хаттарды профильде өшіруге болады.",
    "en": "\n\n—\nMYP Lesson Analyzer. You can turn off emails in your profile.",
}


def _lesson_title(lesson: dict) -> str:
    return lesson.get("lesson_title") or lesson.get("subject") or "—"


def notify(user_ids: set[int], lesson: dict, kind: str, actor: dict | None = None, excerpt: str = "") -> None:
    data = {
        "lesson_title": _lesson_title(lesson),
        "actor_name": (actor or {}).get("name") or (actor or {}).get("email") or "",
        "excerpt": excerpt[:280],
    }
    for uid in user_ids:
        user = db.get_user(uid)
        if not user or not user["is_active"]:
            continue
        db.add_notification(uid, lesson["id"], kind, data)
        if user.get("email_notifications", 1) and smtp_configured():
            _mail_pool.submit(_send_mail, user, lesson, kind, data)


def notify_comment(lesson: dict, author: dict, body: str) -> None:
    recipients = {lesson["user_id"]} | {c["user_id"] for c in db.list_comments(lesson["id"])}
    recipients.discard(author["id"])
    notify(recipients, lesson, "comment", author, body)


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def _send_mail(user: dict, lesson: dict, kind: str, data: dict) -> None:
    lang = user.get("ui_language") or "ru"
    if lang not in ("ru", "kk", "en"):
        lang = "ru"
    base = os.environ.get("APP_URL", "").rstrip("/")
    tab = "?tab=discussion" if kind == "comment" else ""
    link = f"{base}/#/lessons/{lesson['id']}{tab}" if base else f"/#/lessons/{lesson['id']}{tab}"
    subject = SUBJECTS[kind][lang].format(lesson=data["lesson_title"])
    text = BODIES[kind][lang].format(actor=data["actor_name"], excerpt=data["excerpt"], link=link) + FOOTER[lang]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("MYP Lesson Analyzer", os.environ["SMTP_FROM"]))
    msg["To"] = user["email"]
    msg.set_content(text)
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        host = os.environ["SMTP_HOST"]
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls(context=ssl.create_default_context())
        with server:
            if os.environ.get("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(msg)
    except Exception:  # noqa: BLE001 - почта не должна ломать сайт
        print(f"[notify] не удалось отправить письмо {user['email']}:")
        traceback.print_exc()
