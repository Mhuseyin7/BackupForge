"""Outbound notifications intentionally carry no source credentials or artifact contents."""
from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import NotificationDelivery, NotificationTarget
from .security import decrypt_json

ALLOWED_EVENTS = {"backup.completed", "backup.failed", "verification.failed", "retention.failed", "destination.unavailable"}


def _post(url: str, body: dict) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("notification URL must use https")
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError("notification endpoint rejected delivery")


def dispatch(event: str, detail: dict) -> None:
    if event not in ALLOWED_EVENTS:
        return
    with SessionLocal() as session:
        targets = list(session.scalars(select(NotificationTarget).where(NotificationTarget.enabled.is_(True))))
        for target in targets:
            if target.events and event not in target.events:
                continue
            try:
                config = decrypt_json(target.encrypted_config, settings().encryption_key())
                payload = {"event": event, "service": "BackupForge", "detail": detail}
                if target.kind in {"webhook", "discord"}:
                    _post(config["url"], {"content": f"BackupForge: {event}"} if target.kind == "discord" else payload)
                elif target.kind == "telegram":
                    _post(f"https://api.telegram.org/bot{config['bot_token']}/sendMessage", {"chat_id": config["chat_id"], "text": f"BackupForge: {event}"})
                elif target.kind == "email":
                    message = EmailMessage()
                    message["Subject"] = f"BackupForge: {event}"
                    message["From"], message["To"] = config["from"], config["to"]
                    message.set_content(json.dumps(payload, indent=2))
                    with smtplib.SMTP_SSL(config["host"], int(config.get("port", 465)), timeout=10) as smtp:
                        smtp.login(config["username"], config["password"])
                        smtp.send_message(message)
                else:
                    raise ValueError("unsupported notification kind")
                session.add(NotificationDelivery(target_id=target.id, event=event, status="DELIVERED"))
            except Exception as exc:
                # Deliberately record only exception class; URLs and tokens are sensitive.
                session.add(NotificationDelivery(target_id=target.id, event=event, status="FAILED", detail=type(exc).__name__))
        session.commit()
