"""Gmail API client adapter with seamless offline mock fallback."""

from __future__ import annotations

import base64
import email
from email.header import decode_header
import imaplib
import logging
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.integrations.mocks import MockGmailClient

logger = logging.getLogger(__name__)


def _decode_mime_header(header_val: Any) -> str:
    """Decode RFC 2047 MIME encoded-word header strings."""
    if not header_val:
        return ""
    try:
        decoded_parts = decode_header(str(header_val))
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(str(part))
        return "".join(result)
    except Exception:
        return str(header_val)


class GmailClient:
    """Gmail API / IMAP client adapter interfacing with live Google IMAP/OAuth or MockGmailClient."""

    def __init__(
        self,
        mock_client: Optional[MockGmailClient] = None,
        credentials_path: Optional[str] = None,
    ) -> None:
        self.mock_client = mock_client or MockGmailClient()
        self.credentials_path = credentials_path
        self._cached_real_messages: Dict[str, Dict[str, Any]] = {}

    def _get_imap_connection(self, target_account: Optional[str] = None) -> Optional[imaplib.IMAP4_SSL]:
        """Attempt to establish an authenticated IMAP SSL connection if credentials exist."""
        import os
        if "PYTEST_CURRENT_TEST" in os.environ:
            return None

        settings = get_settings()
        if settings.mock_services and not (settings.gmail_app_password or settings.secondary_gmail_app_password):
            return None

        account_candidates: List[tuple[str, str]] = []

        primary_pw = settings.gmail_app_password

        if target_account and "@" in target_account:
            if target_account == settings.gmail_user_email and primary_pw:
                account_candidates.append((settings.gmail_user_email, primary_pw))
            elif target_account == settings.secondary_gmail_user_email and (settings.secondary_gmail_app_password or primary_pw):
                account_candidates.append((settings.secondary_gmail_user_email, settings.secondary_gmail_app_password or primary_pw))
        elif target_account == "personal" and settings.gmail_user_email and primary_pw:
            account_candidates.append((settings.gmail_user_email, primary_pw))
        elif target_account in ("unimilitar", "institucional") and settings.secondary_gmail_user_email:
            pw = settings.secondary_gmail_app_password or primary_pw
            if pw:
                account_candidates.append((settings.secondary_gmail_user_email, pw))
        else:
            # Default lookup order: personal first if password configured, otherwise institutional
            if settings.gmail_user_email and primary_pw:
                account_candidates.append((settings.gmail_user_email, primary_pw))
            if settings.secondary_gmail_user_email:
                pw = settings.secondary_gmail_app_password or primary_pw
                if pw and not any(acc == settings.secondary_gmail_user_email for acc, _ in account_candidates):
                    account_candidates.append((settings.secondary_gmail_user_email, pw))

        for email_user, raw_pw in account_candidates:
            clean_pass = raw_pw.replace(" ", "")
            try:
                imap = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=8)
                imap.login(email_user, clean_pass)
                return imap
            except Exception as e:
                logger.warning(f"Could not connect to live Gmail IMAP ({email_user}): {e}")

        return None

    def _parse_rfc822_message(self, message_id: str, raw_email: bytes) -> Dict[str, Any]:
        """Convert raw RFC 822 bytes into normalized Gmail API payload format."""
        msg = email.message_from_bytes(raw_email)
        subject = _decode_mime_header(msg.get("Subject", "(Sin Asunto)"))
        sender = _decode_mime_header(msg.get("From", "Desconocido"))
        date_str = str(msg.get("Date", "") or "")

        body_text = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    payload_bytes = part.get_payload(decode=True)
                    if payload_bytes:
                        body_text = payload_bytes.decode(part.get_content_charset() or "utf-8", errors="replace")
                        break
        else:
            payload_bytes = msg.get_payload(decode=True)
            if payload_bytes:
                body_text = payload_bytes.decode(msg.get_content_charset() or "utf-8", errors="replace")

        encoded_body = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ascii")
        snippet = body_text.strip().replace("\n", " ")[:120]

        return {
            "id": message_id,
            "threadId": message_id,
            "snippet": snippet,
            "labelIds": ["UNREAD", "INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": subject},
                    {"name": "From", "value": sender},
                    {"name": "Date", "value": date_str},
                ],
                "body": {"data": encoded_body},
            },
        }

    def list_unread(
        self,
        user_id: str = "default_user",
        max_results: int = 10,
        account: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List unread messages for a given user via live IMAP or mock fallback."""
        settings = get_settings()

        # If account is 'all' and we have both credentials, query both
        if account == "all" and settings.gmail_app_password and settings.secondary_gmail_app_password:
            personal_items = self.list_unread(user_id=user_id, max_results=max_results, account="personal")
            for it in personal_items:
                it["account"] = settings.gmail_user_email
            uni_items = self.list_unread(user_id=user_id, max_results=max_results, account="unimilitar")
            for it in uni_items:
                it["account"] = settings.secondary_gmail_user_email
            combined = personal_items + uni_items
            return combined[:max_results]

        imap = self._get_imap_connection(target_account=account)
        if not imap:
            return self.mock_client.list_unread(user_id=user_id, max_results=max_results)

        try:
            imap.select("INBOX", readonly=True)
            status, response = imap.search(None, "UNSEEN")
            if status != "OK" or not response or not response[0]:
                imap.logout()
                return []

            msg_ids = response[0].split()
            # Most recent first
            msg_ids = msg_ids[::-1][:max_results]

            results = []
            for m_id in msg_ids:
                m_str = m_id.decode("utf-8")
                # Prefix with account identifier to avoid collision in cache if querying multiple
                prefixed_id = f"{account or 'default'}_{m_str}"
                results.append({"id": prefixed_id, "threadId": prefixed_id, "raw_id": m_str})
                try:
                    f_status, data = imap.fetch(m_id, "(RFC822)")
                    if f_status == "OK" and data and data[0]:
                        self._cached_real_messages[prefixed_id] = self._parse_rfc822_message(prefixed_id, data[0][1])
                except Exception as ex:
                    logger.debug("Could not prefetch msg %s: %s", m_str, ex)

            imap.logout()
            return results
        except Exception as e:
            logger.warning(f"Error listing unread messages from IMAP: {e}")
            try:
                imap.logout()
            except Exception:
                pass
            return self.mock_client.list_unread(user_id=user_id, max_results=max_results)

    def get_message(self, user_id: str, message_id: str) -> Dict[str, Any]:
        """Fetch detailed RFC 2822 payload for a specific message."""
        if message_id in self._cached_real_messages:
            return self._cached_real_messages[message_id]

        imap = self._get_imap_connection()
        if not imap:
            return self.mock_client.get_message(user_id=user_id, message_id=message_id)

        try:
            imap.select("INBOX", readonly=True)
            status, data = imap.fetch(message_id.encode("utf-8"), "(RFC822)")
            if status != "OK" or not data or not data[0]:
                imap.logout()
                return self.mock_client.get_message(user_id=user_id, message_id=message_id)

            parsed = self._parse_rfc822_message(message_id, data[0][1])
            self._cached_real_messages[message_id] = parsed
            imap.logout()
            return parsed
        except Exception as e:
            logger.warning(f"Error fetching message {message_id} from IMAP: {e}")
            try:
                imap.logout()
            except Exception:
                pass
            return self.mock_client.get_message(user_id=user_id, message_id=message_id)

    def modify_labels(
        self,
        user_id: str,
        message_id: str,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Add or remove labels on a message (e.g. marking as read)."""
        return self.mock_client.modify_labels(
            user_id=user_id,
            message_id=message_id,
            add_labels=add_labels,
            remove_labels=remove_labels,
        )
