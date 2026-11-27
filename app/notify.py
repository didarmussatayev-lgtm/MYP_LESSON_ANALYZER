"""
Уведомления: на сайте (колокольчик) и, если настроен SMTP, по почте.

Кому что приходит:
- comment       — новый комментарий к уроку: автору урока и всем, кто уже
                  писал в обсуждении (кроме самого автора комментария);
- lesson_done   — анализ урока готов: автору урока;
- lesson_error  — анализ остановился с ошибкой: автору урока.

Почта (необязательно, подробно — docs/EMAIL_SETUP.md): EMAIL_FROM + один из
способов — RESEND_API_KEY, BREVO_API_KEY (HTTPS, работают на Railway Hobby)
или SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD (на Railway — только тариф
Pro); APP_URL — адрес сайта для ссылок. Пользователь может отключить письма
в профиле. Письмо уходит в фоновом потоке и не
задерживает ответ сайта; ошибка отправки пишется в лог и ни на что не влияет.
"""

from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
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


def email_provider() -> str | None:
    """Какой способ отправки настроен: resend | brevo | smtp | None."""
    if not _sender_address():
        return None
    if os.environ.get("RESEND_API_KEY"):
        return "resend"
    if os.environ.get("BREVO_API_KEY"):
        return "brevo"
    if os.environ.get("SMTP_HOST"):
        return "smtp"
    return None


def smtp_configured() -> bool:  # прежнее имя, используется в main.py
    return email_provider() is not None


def _sender_address() -> str:
    return os.environ.get("EMAIL_FROM") or os.environ.get("SMTP_FROM") or ""


def _sender_name() -> str:
    return os.environ.get("EMAIL_FROM_NAME", "MYP Lesson Analyzer")


def _lang(user: dict) -> str:
    lang = user.get("ui_language") or "ru"
    return lang if lang in ("ru", "kk", "en") else "ru"


def _link(path: str) -> str:
    base = os.environ.get("APP_URL", "").rstrip("/")
    return f"{base}{path}" if base else path


def _send_mail(user: dict, lesson: dict, kind: str, data: dict) -> None:
    lang = _lang(user)
    tab = "?tab=discussion" if kind == "comment" else ""
    link = _link(f"/#/lessons/{lesson['id']}{tab}")
    subject = SUBJECTS[kind][lang].format(lesson=data["lesson_title"])
    text = BODIES[kind][lang].format(actor=data["actor_name"], excerpt=data["excerpt"], link=link) + FOOTER[lang]
    try:
        deliver(user["email"], subject, text)
    except Exception:  # noqa: BLE001 - почта не должна ломать сайт
        print(f"[notify] не удалось отправить письмо {user['email']}:")
        traceback.print_exc()


TEST_SUBJECT = {
    "ru": "Проверка почты MYP Lesson Analyzer",
    "kk": "MYP Lesson Analyzer поштасын тексеру",
    "en": "MYP Lesson Analyzer email test",
}
TEST_BODY = {
    "ru": "Если вы видите это письмо, уведомления по почте настроены правильно.\n\nСайт: {link}",
    "kk": "Бұл хатты көріп тұрсаңыз, пошта хабарламалары дұрыс бапталған.\n\nСайт: {link}",
    "en": "If you can see this email, email notifications are set up correctly.\n\nSite: {link}",
}


def send_test(user: dict) -> str | None:
    """Синхронно отправляет тестовое письмо; возвращает текст ошибки или None."""
    if not email_provider():
        return "Отправка писем не настроена: задайте EMAIL_FROM и ключ сервиса (см. docs/EMAIL_SETUP.md)."
    lang = _lang(user)
    try:
        deliver(user["email"], TEST_SUBJECT[lang], TEST_BODY[lang].format(link=_link("/")) + FOOTER[lang])
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:600]
    return None


def deliver(to: str, subject: str, text: str) -> None:
    provider = email_provider()
    if provider == "resend":
        _post_json(
            "https://api.resend.com/emails",
            {"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            {"from": formataddr((_sender_name(), _sender_address())), "to": [to], "subject": subject, "text": text},
        )
    elif provider == "brevo":
        _post_json(
            "https://api.brevo.com/v3/smtp/email",
            {"api-key": os.environ["BREVO_API_KEY"]},
            {"sender": {"name": _sender_name(), "email": _sender_address()}, "to": [{"email": to}],
             "subject": subject, "textContent": text},
        )
    elif provider == "smtp":
        _send_smtp(to, subject, text)
    else:
        raise RuntimeError("email is not configured")


def _post_json(url: str, headers: dict, payload: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:400]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None


def _send_smtp(to: str, subject: str, text: str) -> None:
    # На Railway Hobby исходящий SMTP закрыт — используйте Resend или Brevo.
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((_sender_name(), _sender_address()))
    msg["To"] = to
    msg.set_content(text)
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
