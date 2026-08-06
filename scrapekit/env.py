"""Env helpers: load .env.local and resolve IMAP settings."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path | str) -> None:
    """Load KEY=VALUE into os.environ if key is missing or blank."""
    p = Path(path)
    if not p.exists():
        return
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().replace("\ufeff", "")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        cur = os.environ.get(key)
        if cur is None or (isinstance(cur, str) and not cur.strip()):
            os.environ[key] = value


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return default


def imap_settings() -> dict:
    """Resolve IMAP credentials (IMAP_* with OUTLOOK_* aliases)."""
    return {
        "account": env_first("IMAP_EMAIL_ACCOUNT", "OUTLOOK_EMAIL_ACCOUNT"),
        "password": env_first("IMAP_EMAIL_PASSWORD", "OUTLOOK_EMAIL_PASSWORD"),
        "server": env_first(
            "IMAP_SERVER", "OUTLOOK_IMAP_SERVER", default="imap.gmail.com"
        ),
        "port": int(
            env_first("IMAP_PORT", "OUTLOOK_IMAP_PORT", default="993") or "993"
        ),
        "mailbox": env_first("IMAP_MAILBOX", "OUTLOOK_MAILBOX", default="INBOX"),
        "max_emails": int(
            env_first("IMAP_MAX_EMAILS", "OUTLOOK_MAX_EMAILS", default="30") or "30"
        ),
    }
