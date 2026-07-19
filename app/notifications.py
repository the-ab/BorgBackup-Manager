from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Literal
from urllib import parse, request

from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import delete, func, select

from app.config import NOTIFICATION_SETTINGS_PATH
from app.database import SessionLocal
from app.log_filter import extract_error_output
from app.models import Host, Job, NotificationDelivery, Repository, Run
from app.vault import get_system_secret, set_system_secret
from app.security_store import delete_secret

NOTIFICATION_SCOPE = "system"
SMTP_PASSWORD_SECRET = "notification.smtp_password"
WEBHOOK_URL_SECRET = "notification.webhook_url"
TELEGRAM_TOKEN_SECRET = "notification.telegram_token"

EVENT_TYPES = (
    "backup_failed", "backup_warning", "backup_success",
    "run_cancelled",
    "repository_failed", "repository_warning", "repository_success",
    "schedule_failed", "schedule_warning", "schedule_success",
    "operation_failed", "operation_warning", "operation_success",
)
DEFAULT_EVENTS = [
    "backup_failed", "backup_warning", "run_cancelled",
    "repository_failed", "repository_warning", "schedule_failed", "operation_failed",
]
EVENT_LABELS_DE = {
    "backup_failed": "Backup fehlgeschlagen", "backup_warning": "Backup mit Warnungen", "backup_success": "Backup erfolgreich",
    "run_cancelled": "Ausführung abgebrochen",
    "repository_failed": "Repository-Aktion fehlgeschlagen", "repository_warning": "Repository-Aktion mit Warnungen", "repository_success": "Repository-Aktion erfolgreich",
    "schedule_failed": "Zeitplanausführung fehlgeschlagen", "schedule_warning": "Zeitplanausführung mit Warnungen", "schedule_success": "Zeitplanausführung erfolgreich",
    "operation_failed": "Systemaktion fehlgeschlagen", "operation_warning": "Systemaktion mit Warnungen", "operation_success": "Systemaktion erfolgreich",
    "test": "Testbenachrichtigung",
}
EVENT_LABELS_EN = {
    "backup_failed": "Backup failed", "backup_warning": "Backup completed with warnings", "backup_success": "Backup successful",
    "run_cancelled": "Run cancelled",
    "repository_failed": "Repository action failed", "repository_warning": "Repository action completed with warnings", "repository_success": "Repository action successful",
    "schedule_failed": "Scheduled run failed", "schedule_warning": "Scheduled run completed with warnings", "schedule_success": "Scheduled run successful",
    "operation_failed": "System action failed", "operation_warning": "System action completed with warnings", "operation_success": "System action successful",
    "test": "Test notification",
}

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SINGLE_LINE_RE = re.compile(r"^[^\x00\r\n]*$")


def _clean_line(value: str, field: str, maximum: int = 255) -> str:
    text = value.strip()
    if len(text) > maximum or not _SINGLE_LINE_RE.fullmatch(text):
        raise ValueError(f"{field} enthält ungültige Zeichen oder ist zu lang")
    return text


def _validate_http_url(value: str) -> str:
    text = _clean_line(value, "Webhook-URL", 2048)
    parsed = parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Webhook-URL muss eine vollständige HTTP- oder HTTPS-Adresse sein")
    if parsed.username or parsed.password:
        raise ValueError("Webhook-URL darf keine eingebetteten Zugangsdaten enthalten")
    return text


class NotificationSettingsInput(BaseModel):
    enabled: bool = False
    instance_name: str = Field(default="BorgBackup Manager", min_length=1, max_length=100)
    language: Literal["de", "en"] = "de"
    events: list[str] = Field(default_factory=lambda: list(DEFAULT_EVENTS), max_length=len(EVENT_TYPES))
    include_error_excerpt: bool = True
    timeout_seconds: int = Field(default=10, ge=3, le=60)

    smtp_enabled: bool = False
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_username: str = Field(default="", max_length=255)
    smtp_password: SecretStr | None = None
    smtp_clear_password: bool = False
    email_from: str = Field(default="", max_length=320)
    email_recipients: list[str] = Field(default_factory=list, max_length=50)

    webhook_enabled: bool = False
    webhook_kind: Literal["generic", "discord"] = "generic"
    webhook_url: SecretStr | None = None
    webhook_clear_url: bool = False

    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_clear_token: bool = False
    telegram_chat_id: str = Field(default="", max_length=100)

    @field_validator("instance_name", "smtp_host", "smtp_username", "email_from", "telegram_chat_id")
    @classmethod
    def single_line_fields(cls, value: str, info):
        return _clean_line(value, info.field_name, 320 if info.field_name == "email_from" else 255)

    @field_validator("events")
    @classmethod
    def valid_events(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if value not in EVENT_TYPES:
                raise ValueError(f"Unbekanntes Benachrichtigungsereignis: {value}")
            if value not in normalized:
                normalized.append(value)
        return normalized

    @field_validator("email_recipients")
    @classmethod
    def valid_recipients(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            value = _clean_line(raw, "E-Mail-Empfänger", 320)
            if not _EMAIL_RE.fullmatch(value):
                raise ValueError(f"Ungültige E-Mail-Adresse: {value}")
            if value.casefold() not in {item.casefold() for item in normalized}:
                normalized.append(value)
        return normalized


class NotificationSettingsOut(BaseModel):
    enabled: bool
    instance_name: str
    language: Literal["de", "en"]
    events: list[str]
    include_error_excerpt: bool
    timeout_seconds: int
    smtp_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_security: Literal["starttls", "ssl", "none"]
    smtp_username: str
    smtp_password_set: bool
    email_from: str
    email_recipients: list[str]
    webhook_enabled: bool
    webhook_kind: Literal["generic", "discord"]
    webhook_url_set: bool
    telegram_enabled: bool
    telegram_token_set: bool
    telegram_chat_id: str


class NotificationTestIn(BaseModel):
    channel: Literal["email", "webhook", "telegram"]


@dataclass(frozen=True)
class NotificationMessage:
    event_type: str
    severity: str
    title: str
    body: str
    run_id: int | None = None


def default_notification_settings() -> dict:
    return NotificationSettingsInput().model_dump(exclude={
        "smtp_password", "smtp_clear_password", "webhook_url", "webhook_clear_url",
        "telegram_bot_token", "telegram_clear_token",
    })


def load_notification_settings() -> dict:
    values = default_notification_settings()
    try:
        raw = json.loads(NOTIFICATION_SETTINGS_PATH.read_text(encoding="utf-8")) if NOTIFICATION_SETTINGS_PATH.is_file() else {}
        if isinstance(raw, dict):
            values.update({key: value for key, value in raw.items() if key in values})
    except (OSError, ValueError, TypeError):
        pass
    # Revalidate persisted values and fall back safely if a file was manually damaged.
    try:
        validated = NotificationSettingsInput.model_validate(values)
    except ValueError:
        validated = NotificationSettingsInput()
    return validated.model_dump(exclude={
        "smtp_password", "smtp_clear_password", "webhook_url", "webhook_clear_url",
        "telegram_bot_token", "telegram_clear_token",
    })


def notification_settings_out() -> NotificationSettingsOut:
    values = load_notification_settings()
    return NotificationSettingsOut(
        **values,
        smtp_password_set=bool(get_system_secret(SMTP_PASSWORD_SECRET)),
        webhook_url_set=bool(get_system_secret(WEBHOOK_URL_SECRET)),
        telegram_token_set=bool(get_system_secret(TELEGRAM_TOKEN_SECRET)),
    )


def save_notification_settings(data: NotificationSettingsInput) -> NotificationSettingsOut:
    current_smtp_password = get_system_secret(SMTP_PASSWORD_SECRET)
    current_webhook_url = get_system_secret(WEBHOOK_URL_SECRET)
    current_telegram_token = get_system_secret(TELEGRAM_TOKEN_SECRET)

    smtp_password = data.smtp_password.get_secret_value() if data.smtp_password else current_smtp_password
    webhook_url = data.webhook_url.get_secret_value() if data.webhook_url else current_webhook_url
    telegram_token = data.telegram_bot_token.get_secret_value() if data.telegram_bot_token else current_telegram_token
    if data.smtp_clear_password:
        smtp_password = None
    if data.webhook_clear_url:
        webhook_url = None
    if data.telegram_clear_token:
        telegram_token = None

    if data.smtp_enabled:
        if not data.smtp_host or not data.email_from or not data.email_recipients:
            raise ValueError("Für E-Mail sind SMTP-Server, Absender und mindestens ein Empfänger erforderlich")
        if not _EMAIL_RE.fullmatch(data.email_from):
            raise ValueError("Ungültige Absenderadresse")
        if data.smtp_username and not smtp_password:
            raise ValueError("Für den konfigurierten SMTP-Benutzer fehlt das Passwort")
    if data.webhook_enabled:
        if not webhook_url:
            raise ValueError("Für den Webhook fehlt die URL")
        _validate_http_url(webhook_url)
    if data.telegram_enabled:
        if not telegram_token or not data.telegram_chat_id:
            raise ValueError("Für Telegram sind Bot-Token und Chat-ID erforderlich")
        if not re.fullmatch(r"[A-Za-z0-9:_-]{20,200}", telegram_token):
            raise ValueError("Telegram-Bot-Token hat ein ungültiges Format")
        if not re.fullmatch(r"-?[A-Za-z0-9_@-]{1,100}", data.telegram_chat_id):
            raise ValueError("Telegram-Chat-ID hat ein ungültiges Format")

    persisted = data.model_dump(exclude={
        "smtp_password", "smtp_clear_password", "webhook_url", "webhook_clear_url",
        "telegram_bot_token", "telegram_clear_token",
    })
    NOTIFICATION_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = NOTIFICATION_SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(NOTIFICATION_SETTINGS_PATH)

    if smtp_password:
        set_system_secret(SMTP_PASSWORD_SECRET, smtp_password)
    else:
        delete_secret(NOTIFICATION_SCOPE, SMTP_PASSWORD_SECRET)
    if webhook_url:
        set_system_secret(WEBHOOK_URL_SECRET, _validate_http_url(webhook_url))
    else:
        delete_secret(NOTIFICATION_SCOPE, WEBHOOK_URL_SECRET)
    if telegram_token:
        set_system_secret(TELEGRAM_TOKEN_SECRET, telegram_token)
    else:
        delete_secret(NOTIFICATION_SCOPE, TELEGRAM_TOKEN_SECRET)
    return notification_settings_out()


def _event_type(run: Run) -> str:
    if run.status == "cancelled":
        return "run_cancelled"
    suffix = {"failed": "failed", "warning": "warning", "success": "success"}.get(run.status, "failed")
    if run.action == "backup":
        return f"backup_{suffix}"
    if run.action == "schedule":
        return f"schedule_{suffix}"
    if run.job_id is None or run.action.startswith("repository-"):
        return f"repository_{suffix}"
    return f"operation_{suffix}"


def _severity(status: str) -> str:
    return {"success": "success", "warning": "warning", "failed": "error", "cancelled": "warning"}.get(status, "info")


def _warning_text(run: Run) -> str:
    if not run.warning_summary_json:
        return ""
    try:
        summary = json.loads(run.warning_summary_json)
    except (TypeError, ValueError):
        return ""
    causes = (summary.get("items") or summary.get("causes")) if isinstance(summary, dict) else None
    if not isinstance(causes, list):
        return ""
    values: list[str] = []
    for cause in causes[:10]:
        if not isinstance(cause, dict):
            continue
        detail = cause.get("detail") or cause.get("reason") or cause.get("path") or cause.get("message")
        kind = cause.get("kind") or cause.get("type")
        text = " – ".join(str(item) for item in (kind, detail) if item)
        if text:
            values.append(text)
    return "\n".join(values)


def build_run_message(run_id: int, *, test: bool = False) -> NotificationMessage | None:
    settings = load_notification_settings()
    language = settings["language"]
    labels = EVENT_LABELS_EN if language == "en" else EVENT_LABELS_DE
    if test:
        title = f"[{settings['instance_name']}] {labels['test']}"
        body = (
            "The notification channel is configured correctly."
            if language == "en" else "Der Benachrichtigungskanal ist korrekt eingerichtet."
        )
        return NotificationMessage("test", "info", title, body, None)

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run or run.status not in {"success", "warning", "failed", "cancelled"}:
            return None
        event_type = _event_type(run)
        if event_type not in settings["events"]:
            return None
        job = db.get(Job, run.job_id) if run.job_id else None
        repository = db.get(Repository, run.repository_id) if run.repository_id else None
        host = db.get(Host, job.host_id) if job else None
        label = labels.get(event_type, event_type)
        subject = run.job_name_snapshot or (job.name if job else None) or (repository.name if repository else None) or f"Run #{run.id}"
        title = f"[{settings['instance_name']}] {label}: {subject}"
        if language == "en":
            lines = [
                f"Event: {label}", f"Run: #{run.id}", f"Action: {run.action}",
                f"Status: {run.status}", f"Subject: {subject}",
            ]
            if host:
                lines.append(f"Device: {host.name}")
            if repository:
                lines.append(f"Repository: {repository.name} (ID {repository.id})")
            if run.trigger_type == "schedule":
                lines.append(f"Schedule: {run.schedule_name_snapshot or '-'}")
        else:
            lines = [
                f"Ereignis: {label}", f"Ausführung: #{run.id}", f"Aktion: {run.action}",
                f"Status: {run.status}", f"Betreff: {subject}",
            ]
            if host:
                lines.append(f"Gerät: {host.name}")
            if repository:
                lines.append(f"Repository: {repository.name} (ID {repository.id})")
            if run.trigger_type == "schedule":
                lines.append(f"Zeitplan: {run.schedule_name_snapshot or '-'}")
        if run.finished_at:
            lines.append(("Finished: " if language == "en" else "Beendet: ") + run.finished_at.astimezone(timezone.utc).isoformat())
        warning = _warning_text(run)
        if warning:
            lines.extend(["", "Warnings:" if language == "en" else "Warnungsursachen:", warning])
        if settings["include_error_excerpt"]:
            diagnostic = extract_error_output(run.error or "") or extract_error_output(run.log_output or "")
            if diagnostic:
                lines.extend(["", "Diagnostic:" if language == "en" else "Diagnose:", diagnostic[-4000:]])
        return NotificationMessage(event_type, _severity(run.status), title, "\n".join(lines), run.id)


def _record_delivery(message: NotificationMessage, channel: str, status: str, detail: str) -> None:
    with SessionLocal() as db:
        db.add(NotificationDelivery(
            run_id=message.run_id,
            event_type=message.event_type,
            channel=channel,
            status=status,
            title=message.title[:300],
            detail=detail[:4000],
        ))
        db.commit()
        count = db.scalar(select(func.count()).select_from(NotificationDelivery)) or 0
        if count > 1000:
            stale_ids = list(db.scalars(select(NotificationDelivery.id).order_by(NotificationDelivery.id).limit(count - 1000)))
            if stale_ids:
                db.execute(delete(NotificationDelivery).where(NotificationDelivery.id.in_(stale_ids)))
                db.commit()


def _send_email(settings: dict, message: NotificationMessage) -> None:
    mail = EmailMessage()
    mail["Subject"] = message.title
    mail["From"] = settings["email_from"]
    mail["To"] = ", ".join(settings["email_recipients"])
    mail.set_content(message.body)
    context = ssl.create_default_context()
    timeout = settings["timeout_seconds"]
    if settings["smtp_security"] == "ssl":
        client = smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], timeout=timeout, context=context)
    else:
        client = smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=timeout)
    with client:
        client.ehlo()
        if settings["smtp_security"] == "starttls":
            client.starttls(context=context)
            client.ehlo()
        password = get_system_secret(SMTP_PASSWORD_SECRET)
        if settings["smtp_username"]:
            client.login(settings["smtp_username"], password or "")
        client.send_message(mail)


def _post_json(url: str, payload: dict, timeout: int) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "BorgBackup-Manager/notifications",
    })
    with request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
        if not 200 <= int(response.status) < 300:
            raise RuntimeError(f"HTTP {response.status}")
        response.read(1024)


def _send_webhook(settings: dict, message: NotificationMessage) -> None:
    url = get_system_secret(WEBHOOK_URL_SECRET)
    if not url:
        raise ValueError("Webhook-URL fehlt")
    if settings["webhook_kind"] == "discord":
        colors = {"success": 0x2E7D32, "warning": 0xED6C02, "error": 0xC62828, "info": 0x1565C0}
        payload = {"embeds": [{"title": message.title, "description": message.body[:4000], "color": colors.get(message.severity, 0x1565C0)}]}
    else:
        payload = {
            "source": "borgbackup-manager", "event": message.event_type, "severity": message.severity,
            "title": message.title, "message": message.body, "run_id": message.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    _post_json(url, payload, settings["timeout_seconds"])


def _send_telegram(settings: dict, message: NotificationMessage) -> None:
    token = get_system_secret(TELEGRAM_TOKEN_SECRET)
    if not token:
        raise ValueError("Telegram-Bot-Token fehlt")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": settings["telegram_chat_id"], "text": f"{message.title}\n\n{message.body}"[:4096]}
    _post_json(url, payload, settings["timeout_seconds"])


def _safe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for secret_name in (SMTP_PASSWORD_SECRET, WEBHOOK_URL_SECRET, TELEGRAM_TOKEN_SECRET):
        secret = get_system_secret(secret_name)
        if not secret:
            continue
        text = text.replace(secret, "***")
        if secret_name == WEBHOOK_URL_SECRET:
            try:
                parsed = parse.urlsplit(secret)
                sensitive_parts = [part for part in parsed.path.split("/") if len(part) >= 6]
                sensitive_parts.extend(value for values in parse.parse_qs(parsed.query).values() for value in values if len(value) >= 6)
                for part in sensitive_parts:
                    text = text.replace(part, "***")
            except ValueError:
                pass
    return text[:4000]


def dispatch_message(message: NotificationMessage, *, channel: str | None = None, ignore_global_disabled: bool = False) -> list[dict]:
    settings = load_notification_settings()
    if not settings["enabled"] and not ignore_global_disabled:
        return []
    channels = [channel] if channel else [name for name, enabled in (
        ("email", settings["smtp_enabled"]), ("webhook", settings["webhook_enabled"]), ("telegram", settings["telegram_enabled"]),
    ) if enabled]
    results: list[dict] = []
    senders = {"email": _send_email, "webhook": _send_webhook, "telegram": _send_telegram}
    for name in channels:
        sender = senders.get(name)
        if not sender:
            continue
        try:
            sender(settings, message)
            detail = "Benachrichtigung erfolgreich versendet"
            status = "success"
        except Exception as exc:  # delivery failures must never change a Borg run result
            detail = _safe_error(exc)
            status = "failed"
        _record_delivery(message, name, status, detail)
        results.append({"channel": name, "status": status, "detail": detail})
    return results


def notify_run_completion(run_id: int) -> list[dict]:
    message = build_run_message(run_id)
    return dispatch_message(message) if message else []


def send_test_notification(channel: str) -> list[dict]:
    settings = load_notification_settings()
    message = build_run_message(0, test=True)
    if not message:
        raise ValueError("Testbenachrichtigung konnte nicht erstellt werden")
    channel_enabled = {
        "email": settings["smtp_enabled"], "webhook": settings["webhook_enabled"], "telegram": settings["telegram_enabled"],
    }.get(channel, False)
    if not channel_enabled:
        raise ValueError("Der gewählte Benachrichtigungskanal ist nicht aktiviert")
    return dispatch_message(message, channel=channel, ignore_global_disabled=True)


def list_deliveries(limit: int = 100) -> list[NotificationDelivery]:
    with SessionLocal() as db:
        return list(db.scalars(select(NotificationDelivery).order_by(NotificationDelivery.id.desc()).limit(max(1, min(limit, 500)))))


def clear_deliveries() -> int:
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(NotificationDelivery)) or 0
        db.execute(delete(NotificationDelivery))
        db.commit()
        return int(count)
