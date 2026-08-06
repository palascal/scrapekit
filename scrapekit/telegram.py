"""Telegram notifications — pass token/chat or fall back to env."""

from __future__ import annotations

import os

import requests


def send_telegram_message(
    message: str,
    *,
    token: str | None = None,
    chat_id: str | None = None,
) -> None:
    bot = (token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    chat = (chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not bot or not chat:
        print("ℹ️ Telegram non configuré (TELEGRAM_*), notification ignorée.")
        return
    url = f"https://api.telegram.org/bot{bot}/sendMessage"
    data = {
        "chat_id": chat,
        "text": message,
        "parse_mode": "HTML",
    }
    requests.post(url, data=data, timeout=20)
