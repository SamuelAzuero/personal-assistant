"""Multi-turn conversational session manager with slot buffer and user isolation."""

from dataclasses import dataclass, field
from datetime import datetime
import threading
from typing import Any, Dict, List, Optional

from app.integrations.protocols import IntentResult, IntentType


@dataclass
class ConversationTurn:
    """Single turn in conversational history."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class UserSession:
    """Conversational state buffer for a specific user."""
    user_id: str
    active_intent: Optional[IntentType] = None
    slots: Dict[str, Any] = field(default_factory=dict)
    missing_slots: List[str] = field(default_factory=list)
    turn_count: int = 0
    history: List[ConversationTurn] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_in_flow(self) -> bool:
        """Returns True if the session has an active multi-turn slot filling flow."""
        return self.active_intent is not None and len(self.missing_slots) > 0

    @property
    def has_pending_clarification(self) -> bool:
        """Alias property for is_in_flow for multi-turn clarification state."""
        return self.is_in_flow()

    def to_context_dict(self) -> Dict[str, Any]:
        """Exports session state for IntentParser context."""
        return {
            "active_intent": self.active_intent,
            "slots": dict(self.slots),
            "missing_slots": list(self.missing_slots),
            "turn_count": self.turn_count,
        }


class SessionManager:
    """Thread-safe session manager maintaining isolated user dialogue buffers."""

    def __init__(self, max_history_per_user: int = 50, ttl_seconds: int = 1800) -> None:
        self._sessions: Dict[str, UserSession] = {}
        self._lock = threading.Lock()
        self.max_history_per_user = max_history_per_user
        self.ttl_seconds = ttl_seconds

    def get_session(self, user_id: str) -> UserSession:
        """Retrieves existing session or creates a new isolated session for user."""
        with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = UserSession(user_id=user_id)
            session = self._sessions[user_id]
            if self.ttl_seconds > 0 and session.updated_at:
                now = datetime.utcnow() if session.updated_at.tzinfo is None else datetime.now(session.updated_at.tzinfo)
                elapsed = (now - session.updated_at).total_seconds()
                if elapsed > self.ttl_seconds:
                    session.active_intent = None
                    session.slots.clear()
                    session.missing_slots.clear()
                    session.turn_count = 0
            return session

    def clear_session(self, user_id: str) -> None:
        """Resets active intent and pending slots while preserving message history."""
        with self._lock:
            if user_id in self._sessions:
                session = self._sessions[user_id]
                session.active_intent = None
                session.slots.clear()
                session.missing_slots.clear()
                session.updated_at = datetime.utcnow()

    def reset_user(self, user_id: str) -> None:
        """Completely purges user session and history."""
        with self._lock:
            self._sessions.pop(user_id, None)

    def add_message(self, user_id: str, role: str, content: str) -> None:
        """Appends a message to user history."""
        with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = UserSession(user_id=user_id)
            session = self._sessions[user_id]
            session.history.append(ConversationTurn(role=role, content=content))
            if len(session.history) > self.max_history_per_user:
                session.history.pop(0)
            session.updated_at = datetime.utcnow()

    def get_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves the recent conversation history for a user."""
        with self._lock:
            if user_id not in self._sessions:
                return []
            history_slice = self._sessions[user_id].history[-limit:]
            return [
                {
                    "role": turn.role,
                    "content": turn.content,
                    "timestamp": turn.timestamp.isoformat(),
                }
                for turn in history_slice
            ]

    def update_with_intent(
        self, user_id: str, intent_result: IntentResult
    ) -> Optional[str]:
        """
        Updates session buffer from parsed IntentResult.
        If intent requires missing slots, updates state and returns clarification prompt.
        If intent is complete or cancelled, clears state and returns None or cancel message.
        """
        with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = UserSession(user_id=user_id)
            session = self._sessions[user_id]
            session.updated_at = datetime.utcnow()

            # Handle cancellation
            if intent_result.intent == IntentType.CANCEL:
                session.active_intent = None
                session.slots.clear()
                session.missing_slots.clear()
                return "❌ Operation canceled. What else can I help you with?"

            # If complete, clear pending flow state
            if intent_result.is_complete:
                session.active_intent = None
                session.slots.clear()
                session.missing_slots.clear()
                return None

            # Incomplete: save state and generate clarification prompt
            session.active_intent = intent_result.intent
            session.slots = dict(intent_result.slots)
            session.missing_slots = list(intent_result.missing_slots)
            session.turn_count += 1

            return self._build_clarification_prompt(
                intent_result.intent, intent_result.missing_slots, session.slots
            )

    def _build_clarification_prompt(
        self, intent: IntentType, missing_slots: List[str], current_slots: Dict[str, Any]
    ) -> str:
        """Generates friendly, context-aware clarification questions for missing slots."""
        if intent == IntentType.FINANCE_ENTRY:
            if "amount" in missing_slots:
                desc = current_slots.get("description", "this transaction")
                return f"How much did you spend or receive for **{desc}**? (e.g., `$45.00`)"
            if "description" in missing_slots:
                amt = current_slots.get("amount_cents", 0) / 100
                return f"What was this **${amt:,.2f}** transaction for? (e.g., groceries, lunch, coffee)"

        if intent == IntentType.CALENDAR_SCHEDULE:
            if "title" in missing_slots:
                return "What is the title or subject of this calendar event?"
            if "start_time" in missing_slots:
                title = current_slots.get("title", "event")
                return f"When would you like to schedule **{title}**? (e.g., tomorrow at 3pm)"

        if intent == IntentType.TASK_CREATE:
            if "title" in missing_slots:
                return "What task or reminder would you like me to remember?"

        return f"Could you please specify: {', '.join(missing_slots)}?"
