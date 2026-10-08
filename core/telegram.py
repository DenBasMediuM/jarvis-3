"""Отправка сообщений в Telegram Bot API."""

from __future__ import annotations

from typing import Any

import httpx

from core.config import settings

TG_MAX_MESSAGE = 4096


def telegram_configured() -> bool:
    token = (settings.telegram_bot_token or "").strip()
    chat = (settings.telegram_chat_id or "").strip()
    return bool(token and chat)


async def send_telegram_message(
    text: str,
    *,
    chat_id: str | None = None,
    parse_mode: str | None = None,
) -> dict[str, Any]:
    token = (settings.telegram_bot_token or "").strip()
    chat = (chat_id or settings.telegram_chat_id or "").strip()
    if not token or not chat:
        raise RuntimeError(
            "Telegram не настроен: укажите JARVIS_TELEGRAM_BOT_TOKEN и "
            "JARVIS_TELEGRAM_CHAT_ID в файле .env"
        )
    body = text if len(text) <= TG_MAX_MESSAGE else text[: TG_MAX_MESSAGE - 1] + "…"
    payload: dict[str, Any] = {
        "chat_id": chat,
        "text": body,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, json=payload)
        data = res.json() if res.content else {}
        if res.status_code >= 400 or not data.get("ok"):
            desc = data.get("description") or res.text or res.status_code
            raise RuntimeError(f"Telegram API: {desc}")
        return data


async def send_telegram_messages(
    messages: list[str] | list[dict[str, Any]],
    *,
    pause_s: float = 0.35,
    default_parse_mode: str | None = None,
) -> int:
    """Отправить список сообщений по одному. Возвращает число отправленных.

    Элемент — строка или dict с ключами text / parse_mode.
    """
    import asyncio

    sent = 0
    for i, msg in enumerate(messages):
        parse_mode = default_parse_mode
        if isinstance(msg, dict):
            text = str(msg.get("text") or "").strip()
            pm = msg.get("parse_mode")
            if pm:
                parse_mode = str(pm)
            elif pm == "":
                parse_mode = None
        else:
            text = str(msg or "").strip()
        if not text:
            continue
        await send_telegram_message(text, parse_mode=parse_mode)
        sent += 1
        if i < len(messages) - 1 and pause_s > 0:
            await asyncio.sleep(pause_s)
    return sent
