"""Email monitoring, RFC 2822 MIME parsing, urgency scoring, and executive digest generation."""

from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional
from app.integrations.gmail_client import GmailClient
from app.integrations.mocks import MockGmailClient


URGENT_SUBJECT_KEYWORDS = [
    "urgent",
    "urgente",
    "immediate attention",
    "atención inmediata",
    "action required",
    "acción requerida",
    "security alert",
    "alerta de seguridad",
    "payment past due",
    "pago vencido",
    "overdue",
    "vencimiento",
    "flight canceled",
    "flight cancelled",
    "flight delay",
    "vuelo cancelado",
    "server outage",
    "critical",
    "crítico",
    "important",
    "importante",
    "emergency",
    "emergencia",
    "deadline",
    "fecha límite",
    "suspension",
    "suspensión",
    "parcial",
    "calificación",
]

URGENT_BODY_KEYWORDS = [
    "immediate action required",
    "acción inmediata requerida",
    "service suspension",
    "suspensión del servicio",
    "past due",
    "pago pendiente",
    "payment immediately",
    "pago inmediato",
    "unauthorized login",
    "inicio de sesión no autorizado",
    "security incident",
    "incidente de seguridad",
    "outage on production",
    "caída del sistema",
    "flight has been delayed",
    "flight has been cancelled",
    "vuelo retrasado",
    "action required by",
    "requiere su atención",
]

PROMOTIONAL_KEYWORDS = [
    "flash sale",
    "sale",
    "discount",
    "descuento",
    "newsletter",
    "boletín",
    "% off",
    "% de descuento",
    "special offer",
    "oferta especial",
    "deal of the day",
    "exclusive offer",
    "oferta exclusiva",
    "shop now",
    "compra ahora",
    "coupon",
    "cupón",
    "promo",
    "promoción",
    "liquidación",
]


class EmailService:
    """Service for polling Gmail, decoding MIME payloads, scoring urgency, and building digests."""

    def __init__(self, client: Optional[GmailClient] = None) -> None:
        self.client = client or GmailClient()

    def _decode_body(self, payload: Dict[str, Any]) -> str:
        """Decode base64 RFC 2822 body payload with length limit and error safety."""
        # Check direct body data
        body_obj = payload.get("body", {})
        data_str = body_obj.get("data", "")

        # If data is empty, check parts
        if not data_str and "parts" in payload:
            for part in payload["parts"]:
                part_body = part.get("body", {})
                if "data" in part_body and part_body["data"]:
                    data_str = part_body["data"]
                    break

        if not data_str:
            return ""

        # Safe base64 decoding with padding fix
        try:
            # Fix urlsafe and padding
            clean_data = data_str.replace("-", "+").replace("_", "/")
            missing_padding = len(clean_data) % 4
            if missing_padding:
                clean_data += "=" * (4 - missing_padding)

            raw_bytes = base64.b64decode(clean_data)
            text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            # Fallback
            text = "(Corrupted or binary body payload)"

        # Truncate large body to first 50KB to preserve memory limits (T2-R3-03)
        MAX_BODY_CHARS = 50_000
        if len(text) > MAX_BODY_CHARS:
            text = text[:MAX_BODY_CHARS] + "\n...[Body truncated for display]"

        return text

    def _extract_headers(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Extract key headers from Gmail payload into a normalized dict."""
        headers_dict: Dict[str, str] = {}
        for h in payload.get("headers", []):
            name = h.get("name", "").strip()
            value = h.get("value", "").strip()
            if name:
                headers_dict[name] = value
        return headers_dict

    def _extract_action_items(self, text: str) -> List[str]:
        """Extract actionable statements from email text."""
        actions = []
        patterns = [
            r"(?:please\s+review[^\.\n]+)",
            r"(?:action\s+required[^\.\n]+)",
            r"(?:please\s+pay[^\.\n]+)",
            r"(?:payment\s+(?:is\s+)?due[^\.\n]+)",
            r"(?:deadline[^\.\n]+)",
            r"(?:please\s+confirm[^\.\n]+)",
            r"(?:proceed\s+to\s+gate[^\.\n]+)",
        ]
        for pat in patterns:
            matches = re.findall(pat, text, flags=re.IGNORECASE)
            for m in matches:
                clean_m = m.strip()
                if clean_m and clean_m not in actions:
                    actions.append(clean_m)
        return actions[:3]

    def _compute_urgency_score_and_category(
        self,
        headers: Dict[str, str],
        subject: str,
        body: str,
    ) -> tuple[int, bool, str]:
        """Compute urgency score (0-100), urgent flag, and category."""
        subject_lower = subject.lower()
        body_lower = body.lower()
        score = 0

        # Check Subject urgency keywords
        for kw in URGENT_SUBJECT_KEYWORDS:
            if kw in subject_lower:
                score += 35
                break

        # Check Body urgency keywords
        for kw in URGENT_BODY_KEYWORDS:
            if kw in body_lower:
                score += 25
                break

        # Check Priority headers
        x_prio = headers.get("X-Priority", "").strip()
        if x_prio in {"1", "High"}:
            score += 25
        elif x_prio == "2":
            score += 15

        # Check billing/past due signals
        if "past due" in subject_lower or "past due" in body_lower or "bill" in subject_lower:
            score += 20

        # Check security signals
        if "security alert" in subject_lower or "unauthorized" in body_lower:
            score += 30

        # De-escalation heuristics for marketing/promotional emails
        has_unsubscribe = "List-Unsubscribe" in headers
        has_precedence_bulk = headers.get("Precedence", "").lower() == "bulk"
        is_promo = any(kw in subject_lower or kw in body_lower for kw in PROMOTIONAL_KEYWORDS)

        if has_unsubscribe or has_precedence_bulk or is_promo:
            # Significant de-escalation for marketing noise (T2-R3-04)
            score = max(0, score - 50)

        # Clamp score to 0..100
        final_score = max(0, min(100, score))
        is_urgent = final_score >= 70

        # Categorization
        if "security" in subject_lower or "outage" in subject_lower or "flight" in subject_lower:
            category = "ALERT"
        elif "bill" in subject_lower or "invoice" in subject_lower or "past due" in subject_lower:
            category = "BILL"
        elif has_unsubscribe or has_precedence_bulk or is_promo:
            category = "NEWSLETTER"
        elif any(kw in subject_lower for kw in ["roadmap", "project", "review", "contract", "meeting"]):
            category = "WORK"
        else:
            category = "PERSONAL"

        return final_score, is_urgent, category

    def poll_unread(
        self,
        user_id: str = "default_user",
        account: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse all unread emails for a user into normalized items."""
        try:
            unread_refs = self.client.list_unread(user_id=user_id, account=account)
        except TypeError:
            unread_refs = self.client.list_unread(user_id=user_id)

        parsed_items: List[Dict[str, Any]] = []

        for ref in unread_refs:
            msg_id = ref["id"]
            raw_msg = self.client.get_message(user_id=user_id, message_id=msg_id)
            payload = raw_msg.get("payload", {})
            headers = self._extract_headers(payload)

            # Extract subject, sender, date with safe defaults (T2-R3-02)
            subject = headers.get("Subject", "(No Subject)").strip() or "(No Subject)"
            sender = headers.get("From", "Unknown").strip() or "Unknown"
            date_str = headers.get("Date", "").strip()
            snippet = raw_msg.get("snippet", "").strip()

            body = self._decode_body(payload)
            if not snippet and body:
                snippet = body[:120].strip()

            score, is_urgent, category = self._compute_urgency_score_and_category(
                headers=headers,
                subject=subject,
                body=body or snippet,
            )

            actions = self._extract_action_items(body or snippet)

            parsed_items.append({
                "id": msg_id,
                "message_id": msg_id,
                "sender": sender,
                "from": sender,
                "subject": subject,
                "date": date_str,
                "snippet": snippet,
                "body": body,
                "urgency_score": score,
                "is_urgent": is_urgent,
                "category": category,
                "actions": actions,
                "headers": headers,
                "account": ref.get("account"),
            })

        return parsed_items

    def generate_digest(
        self,
        user_id: str = "default_user",
        account: Optional[str] = None,
        use_gemini: bool = True,
    ) -> Dict[str, Any]:
        """Build executive bulleted email digest highlighting urgent actions."""
        items = self.poll_unread(user_id=user_id, account=account)

        # Handle empty inbox (T2-R3-01)
        if not items:
            return {
                "urgent_count": 0,
                "total_unread": 0,
                "items": [],
                "summary_text": "You're all caught up! No unread emails in your inbox.",
                "urgent_items": [],
                "work_items": [],
                "newsletter_items": [],
                "gemini_summary": None,
            }

        urgent_items = [it for it in items if it["is_urgent"]]
        work_items = [it for it in items if it["category"] in {"WORK", "PERSONAL", "BILL"} and not it["is_urgent"]]
        newsletter_items = [it for it in items if it["category"] == "NEWSLETTER" and not it["is_urgent"]]

        # Build bulleted markdown briefing
        lines = [
            f"📧 **Email Digest** ({len(items)} unread, {len(urgent_items)} urgent)\n"
        ]

        if urgent_items:
            lines.append("🚨 **High Priority / Urgent**:")
            for item in urgent_items:
                lines.append(f"• **{item['subject']}** (From: {item['sender']})")
                if item["actions"]:
                    for act in item["actions"]:
                        lines.append(f"  - Action: {act}")
                elif item["snippet"]:
                    lines.append(f"  - {item['snippet']}")
            lines.append("")

        if work_items:
            lines.append("📋 **Actionable & Direct Correspondence**:")
            for item in work_items:
                lines.append(f"• **{item['subject']}** (From: {item['sender']})")
                if item["actions"]:
                    for act in item["actions"]:
                        lines.append(f"  - Action: {act}")
                elif item["snippet"]:
                    lines.append(f"  - {item['snippet']}")
            lines.append("")

        if newsletter_items:
            lines.append("📰 **Newsletters / Low Priority**:")
            for item in newsletter_items:
                lines.append(f"• {item['subject']} (From: {item['sender']})")
            lines.append("")

        summary_text = "\n".join(lines).strip()

        gemini_summary = None
        if use_gemini:
            try:
                import os
                if "PYTEST_CURRENT_TEST" not in os.environ:
                    from app.integrations.gemini_service import GeminiService
                    gem_svc = GeminiService()
                    if gem_svc.is_available:
                        gemini_summary = gem_svc.summarize_emails(items[:8])
            except Exception:
                pass

        return {
            "urgent_count": len(urgent_items),
            "total_unread": len(items),
            "items": items,
            "summary_text": summary_text,
            "urgent_items": urgent_items,
            "work_items": work_items,
            "newsletter_items": newsletter_items,
            "gemini_summary": gemini_summary,
        }

    def format_proactive_alert(self, email_item: Dict[str, Any]) -> str:
        """Format a single high-priority email into an immediate proactive alert message."""
        sender = email_item.get("sender", "Unknown")
        subject = email_item.get("subject", "(No Subject)")
        snippet = email_item.get("snippet", "")
        actions = email_item.get("actions", [])

        lines = [
            "🚨 **URGENT EMAIL ALERT**",
            f"**From**: {sender}",
            f"**Subject**: {subject}",
        ]
        if actions:
            lines.append(f"**Required Action**: {actions[0]}")
        elif snippet:
            lines.append(f"**Details**: {snippet}")

        return "\n".join(lines)
