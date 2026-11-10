"""High-fidelity integration mocks for offline and automated verification testing.

Provides deterministic test doubles for:
- MockSTTService: Voice note audio decoding with pre-registered fixtures and fallback.
- MockGmailClient: Gmail API v1 simulator with RFC 2822 MIME payloads and priority fixtures.
- MockCalendarClient: Google Calendar API v3 simulator with interval conflict detection.
- MockWebSearchClient: Deterministic outing, dining, and leisure recommendation provider.
"""

from __future__ import annotations

import base64
import hashlib
import math
import unicodedata
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _normalize_text(text: Optional[str]) -> str:
    """Normalize text removing diacritics and lowercasing."""
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower().strip()


class AudioProcessingError(Exception):
    """Raised when audio decoding or speech recognition fails."""


class SilentAudioException(Exception):
    """Raised when an audio recording contains no audible speech."""


class GmailAPIError(Exception):
    """Simulated error for Gmail API client operations."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class CalendarAPIError(Exception):
    """Simulated error for Google Calendar API client operations."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


# ============================================================================
# 1. MockSTTService
# ============================================================================

class MockSTTService:
    """Deterministic Speech-to-Text service mock for Telegram audio notes."""

    def __init__(self) -> None:
        self._fixtures: Dict[str, str] = {}
        self._mode: Optional[str] = None  # None, "corrupt", "silent"
        self._seed_default_fixtures()

    def _seed_default_fixtures(self) -> None:
        """Seed known hashes for standard test audio payloads."""
        self.register_fixture(b"MOCK_OGG_EXPENSE_45", "Spent 45 dollars on groceries at Trader Joe's")
        self.register_fixture(b"MOCK_OGG_LUNCH_18", "Spent $18.50 on lunch at Chipotle")
        self.register_fixture(b"MOCK_OGG_CALENDAR_QUERY", "What meetings do I have tomorrow?")
        self.register_fixture(b"MOCK_OGG_TASK_REMINDER", "Remind me to submit project report by 5 PM")
        self.register_fixture(b"MOCK_OGG_EMAIL_CHECK", "Check my unread emails and show urgent ones")
        self.register_fixture(b"MOCK_OGG_OUTING_RESEARCH", "Find top-rated Italian restaurants near Downtown")

    def register_fixture(self, audio_bytes: bytes, transcript: str) -> None:
        """Register a deterministic mapping from audio byte hash to transcript."""
        sha256_hash = hashlib.sha256(audio_bytes).hexdigest()
        self._fixtures[sha256_hash] = transcript

    def set_mode(self, mode: Optional[str]) -> None:
        """Set simulation mode: 'corrupt', 'silent', or None."""
        self._mode = mode

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        mime_type: str = "audio/ogg",
    ) -> str:
        """Transcribe audio bytes to natural language text."""
        if self._mode == "corrupt" or audio_bytes.startswith(b"CORRUPT_"):
            raise AudioProcessingError("Could not transcribe voice note. Please re-record or type your request.")

        if self._mode == "silent" or audio_bytes == b"SILENCE" or len(audio_bytes) == 0:
            raise SilentAudioException("Audio contains no audible speech.")

        # 1. Check for explicit text prefix protocol (e.g. MOCK_VOICE:<transcript>)
        try:
            text_candidate = audio_bytes.decode("utf-8", errors="ignore").strip()
            if text_candidate.startswith("MOCK_VOICE:"):
                return text_candidate.split("MOCK_VOICE:", 1)[1].strip()
        except Exception:
            pass

        # 2. Check for SHA-256 fixture match
        sha256_hash = hashlib.sha256(audio_bytes).hexdigest()
        if sha256_hash in self._fixtures:
            return self._fixtures[sha256_hash]

        # 3. Fallback: if audio_bytes is valid UTF-8 text, return it
        try:
            decoded = audio_bytes.decode("utf-8")
            if decoded.isprintable() and len(decoded.strip()) > 0:
                return decoded.strip()
        except UnicodeDecodeError:
            pass

        # 4. Graceful default fallback for arbitrary binary payload
        return "Simulated voice note transcript"

    async def transcribe_async(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        mime_type: str = "audio/ogg",
    ) -> str:
        """Async compatibility wrapper."""
        return self.transcribe(audio_bytes, filename=filename, mime_type=mime_type)


# ============================================================================
# 2. MockGmailClient
# ============================================================================

class MockGmailClient:
    """High-fidelity mock of Google Gmail API v1."""

    def __init__(self) -> None:
        self.messages: Dict[str, Dict[str, Any]] = {}
        self._simulate_rate_limit: bool = False
        self._simulate_unauthorized: bool = False
        self.reset_fixtures()

    def reset_fixtures(self) -> None:
        """Reset messages to standard synthetic catalog."""
        self.messages.clear()
        self._seed_default_messages()

    def set_simulate_rate_limit(self, enabled: bool) -> None:
        self._simulate_rate_limit = enabled

    def set_simulate_unauthorized(self, enabled: bool) -> None:
        self._simulate_unauthorized = enabled

    def _seed_default_messages(self) -> None:
        """Seed realistic synthetic email fixtures."""
        self.add_message(
            msg_id="msg_urgent_bill_001",
            sender="billing@aws.amazon.com",
            to="user@example.com",
            subject="URGENT: Your AWS bill of $420.50 is past due. Immediate action required.",
            date="Wed, 04 Nov 2026 10:15:00 +0000",
            body="URGENT: Your AWS account has a past due balance of $420.50. Immediate action required to prevent service suspension. Please review attached invoice and make payment immediately.",
            headers={"X-Priority": "1"},
            labels=["UNREAD", "INBOX"],
        )

        self.add_message(
            msg_id="msg_security_alert_002",
            sender="security@google.com",
            to="user@example.com",
            subject="Critical security alert: Unauthorized login detected on your account",
            date="Wed, 04 Nov 2026 09:30:00 +0000",
            body="A sign-in attempt from an unrecognized IP address in Tokyo, Japan was blocked. If this was not you, please secure your account immediately.",
            headers={"X-Priority": "1"},
            labels=["UNREAD", "INBOX"],
        )

        self.add_message(
            msg_id="msg_work_roadmap_003",
            sender="alice@company.com",
            to="user@example.com",
            subject="Project Roadmap Update for Q4",
            date="Wed, 04 Nov 2026 08:00:00 +0000",
            body="Hi team, please review the attached contract and project roadmap by Friday 3 PM so we can finalize headcount allocations.",
            headers={},
            labels=["UNREAD", "INBOX"],
        )

        self.add_message(
            msg_id="msg_flight_delay_004",
            sender="airline@updates.com",
            to="user@example.com",
            subject="URGENT: Flight 204 delayed to 4:00 PM",
            date="Wed, 04 Nov 2026 11:00:00 +0000",
            body="Important travel update: Your flight 204 to San Francisco has been delayed to 4:00 PM. Please proceed to Gate B12.",
            headers={"X-Priority": "2"},
            labels=["UNREAD", "INBOX"],
        )

        self.add_message(
            msg_id="msg_newsletter_promo_005",
            sender="newsletter@weeklytech.io",
            to="user@example.com",
            subject="Weekly Tech Digest: Python 3.13 Innovations",
            date="Tue, 03 Nov 2026 14:00:00 +0000",
            body="Here are the top articles of the week covering AI agents, Python concurrency, and cloud architectures.",
            headers={"List-Unsubscribe": "<mailto:unsub@weeklytech.io>", "Precedence": "bulk"},
            labels=["UNREAD", "INBOX"],
        )

        self.add_message(
            msg_id="msg_promo_fake_urgent_006",
            sender="sales@shoewarehouse.com",
            to="user@example.com",
            subject="URGENT FLASH SALE: 90% OFF SHOES TODAY ONLY!",
            date="Wed, 04 Nov 2026 07:00:00 +0000",
            body="Don't miss our flash sale! 90% off all athletic footwear while supplies last. Click to claim your coupon.",
            headers={"List-Unsubscribe": "<mailto:unsub@shoewarehouse.com>", "Precedence": "bulk"},
            labels=["UNREAD", "INBOX"],
        )

    def add_message(
        self,
        msg_id: str,
        sender: str,
        to: str,
        subject: str,
        date: str,
        body: str,
        headers: Optional[Dict[str, str]] = None,
        labels: Optional[List[str]] = None,
    ) -> str:
        """Add a synthetic message with RFC 2822 payload format."""
        header_list = [
            {"name": "From", "value": sender},
            {"name": "To", "value": to},
            {"name": "Subject", "value": subject},
            {"name": "Date", "value": date},
        ]
        if headers:
            for k, v in headers.items():
                header_list.append({"name": k, "value": v})

        b64_data = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii")
        snippet = body[:120] + "..." if len(body) > 120 else body

        msg_payload = {
            "id": msg_id,
            "threadId": f"thread_{msg_id}",
            "labelIds": labels if labels is not None else ["UNREAD", "INBOX"],
            "snippet": snippet,
            "payload": {
                "headers": header_list,
                "body": {
                    "size": len(body),
                    "data": b64_data,
                },
            },
        }
        self.messages[msg_id] = msg_payload
        return msg_id

    def list_unread(self, user_id: str = "default_user", max_results: int = 10) -> List[Dict[str, Any]]:
        """List unread messages in Gmail API format."""
        if self._simulate_rate_limit:
            raise GmailAPIError("Gmail API rate limit exceeded (HTTP 429 Too Many Requests).", status_code=429)
        if self._simulate_unauthorized:
            raise GmailAPIError("Gmail OAuth2 access token expired (HTTP 401 Unauthorized).", status_code=401)

        unread_refs = []
        for msg_id, msg in self.messages.items():
            if "UNREAD" in msg.get("labelIds", []):
                unread_refs.append({"id": msg_id, "threadId": msg.get("threadId", msg_id)})
            if len(unread_refs) >= max_results:
                break
        return unread_refs

    def get_message(self, user_id: str, message_id: str) -> Dict[str, Any]:
        """Fetch message detail in Gmail API format."""
        if self._simulate_rate_limit:
            raise GmailAPIError("Gmail API rate limit exceeded (HTTP 429).", status_code=429)
        if self._simulate_unauthorized:
            raise GmailAPIError("Gmail OAuth2 access token expired (HTTP 401).", status_code=401)

        if message_id not in self.messages:
            raise GmailAPIError(f"Message not found: {message_id}", status_code=404)
        return self.messages[message_id]

    def modify_labels(
        self,
        user_id: str,
        message_id: str,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Add or remove labels from a message."""
        if message_id not in self.messages:
            raise GmailAPIError(f"Message not found: {message_id}", status_code=404)

        labels = set(self.messages[message_id].get("labelIds", []))
        if add_labels:
            labels.update(add_labels)
        if remove_labels:
            labels.difference_update(remove_labels)

        self.messages[message_id]["labelIds"] = list(labels)
        return self.messages[message_id]


# ============================================================================
# 3. MockCalendarClient
# ============================================================================

class MockCalendarClient:
    """High-fidelity mock of Google Calendar API v3 with interval conflict detection."""

    def __init__(self) -> None:
        # Maps user_id -> List of event dicts
        self.events: Dict[str, List[Dict[str, Any]]] = {}
        self._seed_default_events()

    def _seed_default_events(self) -> None:
        """Seed default calendar events."""
        user_id = "default_user"
        self.events[user_id] = []
        self.create_event(
            user_id=user_id,
            title="Team Sync",
            start_time=datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc),
            location="Room 3B",
            description="Weekly status sync",
        )
        self.create_event(
            user_id=user_id,
            title="Quarterly Strategy Call",
            start_time=datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc),
            end_time=datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc),
            location="Zoom",
            description="Q4 strategic review",
        )

    def _normalize_dt(self, dt: datetime) -> datetime:
        """Ensure datetime has timezone (default UTC)."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def list_events(
        self,
        user_id: str,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List events in Google Calendar v3 format ordered by start time."""
        user_events = self.events.get(user_id, [])
        filtered = []

        t_min = self._normalize_dt(time_min) if time_min else None
        t_max = self._normalize_dt(time_max) if time_max else None

        for ev in user_events:
            ev_start = datetime.fromisoformat(ev["start"]["dateTime"])
            ev_end = datetime.fromisoformat(ev["end"]["dateTime"])

            if t_min and ev_end <= t_min:
                continue
            if t_max and ev_start >= t_max:
                continue
            filtered.append(ev)

        filtered.sort(key=lambda x: x["start"]["dateTime"])
        return filtered

    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: str = "",
        description: str = "",
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new calendar event."""
        s = self._normalize_dt(start_time)
        e = self._normalize_dt(end_time)

        if e <= s:
            raise ValueError("Event end time cannot be before or equal to start time.")

        if user_id not in self.events:
            self.events[user_id] = []

        eid = event_id or f"cal_evt_{len(self.events[user_id]) + 1}_{int(s.timestamp())}"
        new_event = {
            "id": eid,
            "summary": title,
            "title": title,
            "location": location,
            "description": description,
            "start": {"dateTime": s.isoformat()},
            "end": {"dateTime": e.isoformat()},
            "created": datetime.now(timezone.utc).isoformat(),
        }
        self.events[user_id].append(new_event)
        return new_event

    def delete_event(self, user_id: str, event_id: str) -> bool:
        """Delete an event by ID."""
        user_events = self.events.get(user_id, [])
        for i, ev in enumerate(user_events):
            if ev["id"] == event_id:
                del user_events[i]
                return True
        return False

    def check_conflicts(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
        exclude_event_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Strict interval conflict check: max(s1, s2) < min(e1, e2)."""
        s = self._normalize_dt(start_time)
        e = self._normalize_dt(end_time)

        if e <= s:
            raise ValueError("Event end time cannot be before or equal to start time.")

        conflicts = []
        user_events = self.events.get(user_id, [])

        for ev in user_events:
            if exclude_event_id and ev["id"] == exclude_event_id:
                continue

            ev_start = datetime.fromisoformat(ev["start"]["dateTime"])
            ev_end = datetime.fromisoformat(ev["end"]["dateTime"])

            # Strict interval overlap condition
            if max(s, ev_start) < min(e, ev_end):
                conflicts.append(ev)

        return conflicts


# ============================================================================
# 4. MockWebSearchClient
# ============================================================================

class MockWebSearchClient:
    """Deterministic web search client for outing, dining, and activity research."""

    def __init__(self) -> None:
        self._places: List[Dict[str, Any]] = self._init_database()

    def _init_database(self) -> List[Dict[str, Any]]:
        """Initialize curated catalog of places and activities."""
        catalog = [
            # Baseline US Dining: Italian
            {
                "name": "Trattoria Stella",
                "category": "Italian",
                "cuisine": "Italian",
                "rating": 4.8,
                "price_tier": "$$",
                "price_level": "$$",
                "address": "401 Pine St, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6105,
                "longitude": -122.3395,
                "summary": "Authentic handmade pasta and cozy romantic ambiance in Downtown.",
                "description": "Authentic handmade pasta and cozy romantic ambiance in Downtown.",
                "amenities": ["italian", "pasta", "downtown", "romantic", "outdoor seating"],
                "tags": ["italian", "pasta", "downtown", "romantic"],
                "opening_hours": "5:00 PM - 10:00 PM",
            },
            {
                "name": "Luigi's Trattoria",
                "category": "Italian",
                "cuisine": "Italian",
                "rating": 4.8,
                "price_tier": "$$",
                "address": "124 Pine St, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6101,
                "longitude": -122.3421,
                "description": "Authentic wood-fired pastas, hand-tossed pizzas, and classic tiramisu in a cozy candlelit atmosphere.",
                "amenities": ["outdoor seating", "wine bar", "reservations"],
                "opening_hours": "5:00 PM - 10:00 PM",
            },
            {
                "name": "Pasta Fresca",
                "category": "Italian",
                "cuisine": "Italian",
                "rating": 4.6,
                "price_tier": "$$",
                "address": "405 Pike St, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6112,
                "longitude": -122.3375,
                "description": "Daily handcrafted pasta ribbons with rich truffle sauces and natural wines.",
                "amenities": ["takeout", "romantic", "vegetarian options"],
                "opening_hours": "11:30 AM - 9:30 PM",
            },
            {
                "name": "Osteria Bella",
                "category": "Italian",
                "cuisine": "Italian",
                "rating": 4.9,
                "price_tier": "$$$",
                "address": "812 1st Ave, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6044,
                "longitude": -122.3358,
                "description": "Upscale Northern Italian culinary tasting menus with sommelier wine pairings.",
                "amenities": ["valet parking", "private dining", "fine dining"],
                "opening_hours": "5:30 PM - 11:00 PM",
            },
            # Dining: Japanese / Sushi
            {
                "name": "Sushi Kashiba",
                "category": "Japanese",
                "cuisine": "Sushi",
                "rating": 4.9,
                "price_tier": "$$$$",
                "address": "86 Pine St, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6098,
                "longitude": -122.3432,
                "description": "World-renowned omakase sushi experience overlooking the water, curated by legendary master chefs.",
                "amenities": ["omakase bar", "waterfront view", "reservations recommended"],
                "opening_hours": "5:00 PM - 10:00 PM",
            },
            {
                "name": "Tokyo Bistro",
                "category": "Japanese",
                "cuisine": "Sushi",
                "rating": 4.5,
                "price_tier": "$$",
                "address": "310 University St, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6079,
                "longitude": -122.3347,
                "description": "Fresh sashimi rolls, crispy chicken karaage, and authentic ramen bowls.",
                "amenities": ["quick service", "casual", "takeout"],
                "opening_hours": "11:00 AM - 9:00 PM",
            },
            # Dining: Mexican
            {
                "name": "Taqueria El Sol",
                "category": "Mexican",
                "cuisine": "Mexican",
                "rating": 4.7,
                "price_tier": "$",
                "address": "902 4th Ave, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6062,
                "longitude": -122.3321,
                "description": "Street-style birria tacos, house-made horchata, and vibrant roasted salsa bar.",
                "amenities": ["casual", "fast casual", "spicy options"],
                "opening_hours": "10:30 AM - 10:00 PM",
            },
            # Dining: French / Midtown
            {
                "name": "Bistro Pierre",
                "category": "French",
                "cuisine": "French",
                "rating": 4.7,
                "price_tier": "$$",
                "price_level": "$$",
                "address": "1200 5th Ave, Midtown",
                "location": "Midtown",
                "sector": "Midtown",
                "latitude": 47.6085,
                "longitude": -122.3335,
                "summary": "Classic Parisian fare, steak frites, and extensive wine list in Midtown.",
                "description": "Classic Parisian fare, steak frites, and extensive wine list in Midtown.",
                "amenities": ["french", "bistro", "midtown", "wine", "outdoor seating"],
                "tags": ["french", "bistro", "midtown", "wine"],
                "opening_hours": "11:30 AM - 10:00 PM",
            },
            # Dining: Coffee / Cafe
            {
                "name": "Bean & Leaf Coffee Roasters",
                "category": "Cafe",
                "cuisine": "Coffee",
                "rating": 4.7,
                "price_tier": "$",
                "address": "520 Olive Way, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6133,
                "longitude": -122.3364,
                "description": "Specialty single-origin espresso drinks, artisan pastries, and blazing-fast high-speed wifi.",
                "amenities": ["wifi", "work friendly", "vegan pastries"],
                "opening_hours": "6:30 AM - 6:00 PM",
            },
            # Outdoor & Activities
            {
                "name": "Downtown Waterfront Promenade",
                "category": "Outdoor",
                "cuisine": "Activity",
                "rating": 4.8,
                "price_tier": "Free",
                "address": "Pier 62, Alaskan Way, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6075,
                "longitude": -122.3429,
                "description": "Scenic waterfront walking trail with panoramic mountain and bay views, public art, and breeze.",
                "amenities": ["wheelchair accessible", "family friendly", "dog friendly"],
                "opening_hours": "6:00 AM - 11:00 PM",
            },
            {
                "name": "Olympic Sculpture Park",
                "category": "Cultural",
                "cuisine": "Activity",
                "rating": 4.7,
                "price_tier": "Free",
                "address": "2901 Western Ave, Seattle",
                "location": "Seattle",
                "sector": "Seattle",
                "latitude": 47.6166,
                "longitude": -122.3553,
                "description": "Nine-acre open-air museum featuring monumental outdoor sculptures along Puget Sound.",
                "amenities": ["beach access", "free admission", "photography"],
                "opening_hours": "Sunrise - Sunset",
            },
            {
                "name": "Seattle Modern Art Museum",
                "category": "Cultural",
                "cuisine": "Museum",
                "rating": 4.6,
                "price_tier": "$$",
                "address": "1300 1st Ave, Downtown",
                "location": "Downtown",
                "sector": "Downtown",
                "latitude": 47.6073,
                "longitude": -122.3382,
                "description": "Inspiring global modern art installations, rotating contemporary exhibits, and guided tours.",
                "amenities": ["audio guide", "cafe", "gift shop"],
                "opening_hours": "10:00 AM - 5:00 PM",
            },
            # Authentic Colombian Establishments (Requirement R4 / Milestone M13)
            {
                "name": "Criterión",
                "category": "dining",
                "cuisine": "Contemporary",
                "rating": 4.9,
                "price_tier": "$$$$",
                "address": "Calle 69A # 5-75, Zona G, Bogotá",
                "location": "Zona G",
                "sector": "Zona G",
                "latitude": 4.6521,
                "longitude": -74.0558,
                "description": "Alta cocina de autor de los hermanos Rausch en el corazón de la Zona G.",
                "amenities": ["reservas", "valet parking", "carta de vinos"],
                "opening_hours": "12:00 PM - 11:00 PM",
            },
            {
                "name": "El Chato",
                "category": "dining",
                "cuisine": "Colombiana Contemporánea",
                "rating": 4.9,
                "price_tier": "$$$",
                "address": "Calle 65 # 4-76, Chapinero Alto, Bogotá",
                "location": "Chapinero",
                "sector": "Chapinero",
                "latitude": 4.6489,
                "longitude": -74.0592,
                "description": "Bistró de autor premiado internacionalmente con ingredientes colombianos locales.",
                "amenities": ["reservas", "terraza", "cócteles de autor"],
                "opening_hours": "12:00 PM - 11:00 PM",
            },
            {
                "name": "Abasto",
                "category": "dining",
                "cuisine": "Colombiana Artesanal",
                "rating": 4.7,
                "price_tier": "$$",
                "address": "Carrera 6 # 119B-52, Usaquén, Bogotá",
                "location": "Usaquén",
                "sector": "Usaquén",
                "latitude": 4.6961,
                "longitude": -74.0305,
                "description": "Cocina de campo y mercado artesanal con productos de origen en Usaquén.",
                "amenities": ["wifi", "desayuno", "café de origen"],
                "opening_hours": "8:00 AM - 10:00 PM",
            },
            {
                "name": "La Puerta Falsa",
                "category": "dining",
                "cuisine": "Tradicional Santafereña",
                "rating": 4.8,
                "price_tier": "$",
                "address": "Calle 11 # 6-50, La Candelaria, Bogotá",
                "location": "La Candelaria",
                "sector": "La Candelaria",
                "latitude": 4.5983,
                "longitude": -74.0754,
                "description": "El restaurante más antiguo de Bogotá, famoso por su tamal, chocolate y ajiaco.",
                "amenities": ["tradicional", "para llevar"],
                "opening_hours": "7:00 AM - 8:00 PM",
            },
            {
                "name": "Andrés D.C.",
                "category": "dining",
                "cuisine": "Colombiana & Parrilla",
                "rating": 4.8,
                "price_tier": "$$$",
                "address": "Calle 82 # 12-21, El Retiro, Bogotá",
                "location": "Chapinero",
                "sector": "Chapinero",
                "latitude": 4.6668,
                "longitude": -74.0552,
                "description": "Restaurante y fiesta emblemática en 4 pisos temáticos inspirados en la Divina Comedia.",
                "amenities": ["música en vivo", "parrilla", "cócteles", "reservas"],
                "opening_hours": "12:00 PM - 2:00 AM",
            },
            {
                "name": "Cervecería Parque 93",
                "category": "nightlife",
                "cuisine": "Gastropub",
                "rating": 4.6,
                "price_tier": "$$",
                "address": "Carrera 11A # 93-42, Parque 93, Bogotá",
                "location": "Parque 93",
                "sector": "Parque 93",
                "latitude": 4.6765,
                "longitude": -74.0483,
                "description": "Cervezas artesanales colombianas y comida de taberna frente al Parque de la 93.",
                "amenities": ["wifi", "terraza pet-friendly", "cerveza artesanal"],
                "opening_hours": "12:00 PM - 1:00 AM",
            },
            {
                "name": "Carmen Medellín",
                "category": "dining",
                "cuisine": "Colombiana Contemporánea",
                "rating": 4.9,
                "price_tier": "$$$$",
                "address": "Carrera 36 # 10A-27, El Poblado, Medellín",
                "location": "El Poblado",
                "sector": "El Poblado",
                "latitude": 6.2088,
                "longitude": -75.5683,
                "description": "Cocina de autor moderna con ingredientes de la biodiversidad colombiana.",
                "amenities": ["reservas", "terraza", "maridaje"],
                "opening_hours": "12:00 PM - 10:30 PM",
            },
            {
                "name": "Mondongo's Laureles",
                "category": "dining",
                "cuisine": "Tradicional Paisa",
                "rating": 4.7,
                "price_tier": "$$",
                "address": "Circular 73 # 38-16, Laureles, Medellín",
                "location": "Laureles",
                "sector": "Laureles",
                "latitude": 6.2442,
                "longitude": -75.5906,
                "description": "Ícono de la comida típica antioqueña, famoso por su mondongo y bandeja paisa.",
                "amenities": ["familiar", "porciones generosas", "parqueadero"],
                "opening_hours": "11:30 AM - 9:00 PM",
            },
        ]

        for p in catalog:
            q_str = f"{p['name']}, {p.get('address', '')}"
            p["maps_url"] = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(q_str)}"

        return catalog

    def search(
        self,
        query: str,
        location: Optional[str] = None,
        category: Optional[str] = None,
        budget: Optional[str] = None,
        coordinates: Optional[Tuple[float, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Deterministic search matching query terms across place records."""
        q_lower = query.lower() if query else ""

        # Handle zero-result boundary test query specifically
        if "antarctic" in q_lower or "sahara" in q_lower:
            return []

        if coordinates:
            lat, lon = coordinates
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise ValueError(
                    f"Coordinates ({lat}, {lon}) out of valid range: lat in [-90, 90], lon in [-180, 180]."
                )

        clean_loc = _normalize_text(location) if location else ""

        results = []
        for place in self._places:
            text_corpus = (
                f"{place['name']} {place['category']} {place['cuisine']} {place['location']} "
                f"{place.get('sector', '')} {place['address']} {place['description']} "
                f"{' '.join(place.get('amenities', []))}"
            ).lower()
            text_norm = _normalize_text(text_corpus)

            matches_coords = False
            if coordinates:
                v_lat = place.get("latitude")
                v_lon = place.get("longitude")
                if v_lat is not None and v_lon is not None:
                    lat, lon = coordinates
                    dist_km = math.sqrt((lat - v_lat) ** 2 + (lon - v_lon) ** 2) * 111.0
                    if dist_km < 8.0:
                        matches_coords = True

            matches_loc = False
            if clean_loc:
                p_loc = _normalize_text(place.get("location", ""))
                p_sec = _normalize_text(place.get("sector", ""))
                p_addr = _normalize_text(place.get("address", ""))
                if (
                    clean_loc in p_loc
                    or p_loc in clean_loc
                    or clean_loc in p_sec
                    or p_sec in clean_loc
                    or clean_loc in p_addr
                ):
                    matches_loc = True

            matches_q = False
            for word in q_lower.split():
                norm_w = _normalize_text(word)
                if len(norm_w) > 2 and (norm_w in text_norm or norm_w in clean_loc):
                    matches_q = True
                    break

            matches_cat = False
            if category:
                cat_lower = category.lower()
                if (
                    cat_lower in place["category"].lower()
                    or cat_lower in place["cuisine"].lower()
                    or category.capitalize() == place.get("category")
                    or category.capitalize() == place.get("cuisine")
                ):
                    matches_cat = True

            if coordinates:
                if matches_coords:
                    results.append(place)
            else:
                if matches_loc:
                    results.append(place)
                elif not clean_loc and (matches_q or matches_cat):
                    results.append(place)

        # If a specific location or coordinates was requested and yielded nothing, return []
        if (location or coordinates) and not results:
            return []

        # If no specific location/coords were provided and no results found, return general top places
        if not results:
            for place in self._places:
                if any(
                    kw in place["category"].lower() or kw in place["cuisine"].lower()
                    for kw in ["italian", "sushi", "cafe", "outdoor"]
                ):
                    results.append(place)
                if len(results) >= 3:
                    break

        out = []
        for p in results[:5]:
            item = dict(p)
            if "maps_url" not in item or not item["maps_url"]:
                query_str = f"{item['name']}, {item.get('address', '')}"
                item["maps_url"] = (
                    f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(query_str)}"
                )
            out.append(item)

        return out
