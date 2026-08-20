"""
football_bot/publisher.py
==========================
Sends messages to Telegram channels.
Supports inline keyboard buttons (for subscribe CTAs on free channel posts).
"""

import requests
import time
import json
import logging
from config import TELEGRAM_BOT_TOKEN, FREE_CHANNEL_ID

logger = logging.getLogger(__name__)

BASE_URL    = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
MAX_MSG_LEN = 4096


# ─── Core send ────────────────────────────────────────────────────────────────

def _send(chat_id: str, text: str, parse_mode: str = "HTML",
          reply_markup: dict = None) -> bool:
    """Send one message chunk, optionally with an inline keyboard."""
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        r    = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=15)
        data = r.json()
        if not data.get("ok"):
            logger.error(f"Telegram error: {data.get('description')}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram request failed: {e}")
        return False


def _send_with_button(chat_id: str, text: str, keyboard: dict) -> bool:
    """
    Send a message with an inline keyboard attached.
    If the message is too long, splits it — button only goes on the last chunk.
    """
    if len(text) <= MAX_MSG_LEN:
        return _send(chat_id, text, reply_markup=keyboard)

    # Split into chunks
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_MSG_LEN:
            chunks.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        chunks.append(current)

    success = True
    for i, chunk in enumerate(chunks):
        # Only attach button to the last chunk
        kb = keyboard if i == len(chunks) - 1 else None
        if not _send(chat_id, chunk, reply_markup=kb):
            success = False
        time.sleep(1.5)
    return success


# ─── Public functions ─────────────────────────────────────────────────────────

def post_to_free(message: str, keyboard: dict = None) -> bool:
    """
    Post a message to the free channel.
    If keyboard is provided it's attached as an inline button.
    """
    logger.info("Posting to FREE channel...")
    if keyboard:
        return _send_with_button(FREE_CHANNEL_ID, message, keyboard)
    # Plain message (e.g. daily header)
    if len(message) <= MAX_MSG_LEN:
        return _send(FREE_CHANNEL_ID, message)
    # Long plain message — split, no button
    chunks = []
    current = ""
    for line in message.split("\n"):
        if len(current) + len(line) + 1 > MAX_MSG_LEN:
            chunks.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        chunks.append(current)
    success = True
    for chunk in chunks:
        if not _send(FREE_CHANNEL_ID, chunk):
            success = False
        time.sleep(1.5)
    return success