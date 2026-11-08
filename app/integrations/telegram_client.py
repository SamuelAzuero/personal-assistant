"""Telegram Bot API client, webhook payload parser, and keyboard builders."""

from dataclasses import dataclass, field
import hmac
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.integrations.protocols import TelegramClientProtocol

logger = logging.getLogger(__name__)


@dataclass
class TelegramVoice:
    """Represents a voice note attached to an incoming message."""

    file_id: str
    file_unique_id: str = ""
    duration: int = 0
    mime_type: str = "audio/ogg"
    file_size: Optional[int] = None


@dataclass
class TelegramMessage:
    """Unified envelope for incoming Telegram text and voice messages."""

    message_id: int
    chat_id: str
    user_id: str
    text: Optional[str] = None
    voice: Optional[TelegramVoice] = None
    date: int = 0
    raw_message: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_voice(self) -> bool:
        return self.voice is not None


@dataclass
class TelegramUpdate:
    """Normalized representation of a Telegram Update payload."""

    update_id: int
    message: Optional[TelegramMessage] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class TelegramClient(TelegramClientProtocol):
    """Client for parsing Telegram webhook payloads and dispatching bot replies."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        secret_token: Optional[str] = None,
        base_url: str = "https://api.telegram.org",
        mock_mode: bool = False,
    ) -> None:
        self.bot_token = bot_token
        self.secret_token = secret_token
        self.base_url = base_url
        self.mock_mode = mock_mode or (not bot_token)
        self.sent_messages: List[Dict[str, Any]] = []

    def validate_secret_token(
        self, header_token: Optional[str], expected_secret: Optional[str] = None
    ) -> bool:
        """Validate incoming secret token using constant-time comparison."""
        expected = expected_secret or self.secret_token
        if not expected:
            return True if not header_token else False
        if not header_token:
            return False
        return hmac.compare_digest(header_token.strip(), expected.strip())

    def parse_update(self, payload: Dict[str, Any]) -> TelegramUpdate:
        """Parse raw webhook JSON payload into a structured TelegramUpdate."""
        update_id = payload.get("update_id", 0)
        msg_dict = payload.get("message") or payload.get("edited_message") or payload.get("channel_post")

        if not msg_dict or not isinstance(msg_dict, dict):
            return TelegramUpdate(update_id=update_id, message=None, raw_payload=payload)

        message_id = msg_dict.get("message_id", 0) if isinstance(msg_dict.get("message_id"), int) else 0
        chat = msg_dict.get("chat") or {}
        if not isinstance(chat, dict):
            chat = {}
        chat_id = str(chat.get("id", ""))
        from_user = msg_dict.get("from") or {}
        if not isinstance(from_user, dict):
            from_user = {}
        user_id = str(from_user.get("id") or chat_id)

        raw_text = msg_dict.get("text") or msg_dict.get("caption")
        text = str(raw_text) if raw_text is not None else None

        voice = None
        v = msg_dict.get("voice")
        if v and isinstance(v, dict):
            voice = TelegramVoice(
                file_id=str(v.get("file_id", "")),
                file_unique_id=str(v.get("file_unique_id", "")),
                duration=int(v.get("duration", 0)),
                mime_type=str(v.get("mime_type", "audio/ogg")),
                file_size=v.get("file_size"),
            )

        envelope = TelegramMessage(
            message_id=message_id,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            voice=voice,
            date=msg_dict.get("date", 0) if isinstance(msg_dict.get("date"), int) else 0,
            raw_message=msg_dict,
        )

        return TelegramUpdate(
            update_id=update_id, message=envelope, raw_payload=payload
        )

    def build_reply_keyboard(
        self,
        keyboard_rows: List[List[str]],
        resize_keyboard: bool = True,
        one_time_keyboard: bool = False,
    ) -> Dict[str, Any]:
        """Construct a standard Telegram ReplyKeyboardMarkup."""
        return {
            "keyboard": [
                [{"text": button_text} for button_text in row]
                for row in keyboard_rows
            ],
            "resize_keyboard": resize_keyboard,
            "one_time_keyboard": one_time_keyboard,
        }

    def build_inline_keyboard(
        self, button_rows: List[List[Dict[str, str]]]
    ) -> Dict[str, Any]:
        """Construct a Telegram InlineKeyboardMarkup."""
        return {"inline_keyboard": button_rows}

    def build_default_quick_keyboard(self, is_spanish: bool = True) -> Dict[str, Any]:
        """Build standard shortcut keyboard for common personal assistant tasks."""
        if is_spanish:
            return self.build_reply_keyboard(
                [
                    ["🌅 Resumen del Día", "📋 Mis Tareas"],
                    ["📊 Mi Saldo", "📬 Ver Correos"],
                ],
                resize_keyboard=True,
            )
        return self.build_reply_keyboard(
            [
                ["🌅 Daily Briefing", "📋 My Tasks"],
                ["📊 Balance", "📬 Check Emails"],
            ],
            resize_keyboard=True,
        )

    def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown",
    ) -> Dict[str, Any]:
        """Send a message to a Telegram chat or queue in mock mode."""
        msg_payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            msg_payload["reply_markup"] = reply_markup

        self.sent_messages.append(msg_payload)

        if self.mock_mode or not self.bot_token:
            logger.info("Mock Telegram message sent to %s: %s", chat_id, text[:60])
            return {"ok": True, "result": msg_payload}

        url = f"{self.base_url}/bot{self.bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=msg_payload)
                if resp.status_code == 400 and parse_mode:
                    # Markdown parsing failed (e.g. unescaped entities in email or text), retry without parse_mode
                    plain_payload = dict(msg_payload)
                    plain_payload.pop("parse_mode", None)
                    resp = client.post(url, json=plain_payload)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error("Failed to send Telegram message to %s: %s", chat_id, e)
            return {"ok": False, "error": str(e), "payload": msg_payload}
