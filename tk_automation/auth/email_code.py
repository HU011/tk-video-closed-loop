from __future__ import annotations

import email
import imaplib
import os
import re
import time
from dataclasses import dataclass
from email.message import Message


@dataclass(frozen=True)
class EmailCodeConfig:
    host: str
    port: int
    username: str
    password: str
    mailbox: str = "INBOX"
    sender_filter: str = ""
    subject_filter: str = ""
    code_regex: str = r"\b(\d{4,8})\b"

    @classmethod
    def from_env(cls) -> "EmailCodeConfig":
        return cls(
            host=os.environ.get("TK_EMAIL_HOST", ""),
            port=int(os.environ.get("TK_EMAIL_PORT", "993")),
            username=os.environ.get("TK_EMAIL_USER", ""),
            password=os.environ.get("TK_EMAIL_PASSWORD", ""),
            mailbox=os.environ.get("TK_EMAIL_MAILBOX", "INBOX"),
            sender_filter=os.environ.get("TK_EMAIL_SENDER_FILTER", ""),
            subject_filter=os.environ.get("TK_EMAIL_SUBJECT_FILTER", ""),
            code_regex=os.environ.get("TK_EMAIL_CODE_REGEX", r"\b(\d{4,8})\b"),
        )


class EmailCodeReader:
    def __init__(self, config: EmailCodeConfig) -> None:
        self.config = config

    def fetch_latest_code(self) -> str:
        self._validate()
        with imaplib.IMAP4_SSL(self.config.host, self.config.port) as client:
            client.login(self.config.username, self.config.password)
            client.select(self.config.mailbox)
            status, payload = client.search(None, "ALL")
            if status != "OK" or not payload:
                return ""
            ids = payload[0].split()
            for message_id in reversed(ids[-50:]):
                status, data = client.fetch(message_id, "(RFC822)")
                if status != "OK" or not data:
                    continue
                msg = email.message_from_bytes(data[0][1])
                if not self._matches(msg):
                    continue
                code = self._extract_code(self._message_text(msg))
                if code:
                    return code
        return ""

    def wait_for_code(self, timeout_seconds: int = 180, interval_seconds: int = 5) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() <= deadline:
            code = self.fetch_latest_code()
            if code:
                return code
            time.sleep(interval_seconds)
        return ""

    def _validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("TK_EMAIL_HOST", self.config.host),
                ("TK_EMAIL_USER", self.config.username),
                ("TK_EMAIL_PASSWORD", self.config.password),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing email code config: " + ", ".join(missing))

    def _matches(self, msg: Message) -> bool:
        sender = str(msg.get("From", ""))
        subject = str(msg.get("Subject", ""))
        if self.config.sender_filter and self.config.sender_filter.lower() not in sender.lower():
            return False
        if self.config.subject_filter and self.config.subject_filter.lower() not in subject.lower():
            return False
        return True

    def _message_text(self, msg: Message) -> str:
        parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                if part.get_content_type() not in {"text/plain", "text/html"}:
                    continue
                payload = part.get_payload(decode=True)
                if payload:
                    parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(msg.get_content_charset() or "utf-8", errors="replace"))
        return "\n".join(parts)

    def _extract_code(self, text: str) -> str:
        match = re.search(self.config.code_regex, text)
        return match.group(1) if match else ""

