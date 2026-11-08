"""Unit tests for Gemini AI integration and fallback reasoning."""

import json
from unittest.mock import MagicMock, patch
import pytest

from app.integrations.gemini_service import GeminiService
from app.integrations.protocols import IntentType
from app.core.intent_parser import IntentParser
from app.core.router import ToolRouter


class MockContentResponse:
    def __init__(self, text: str):
        self.text = text


def test_gemini_service_unavailable_by_default():
    """Verify GeminiService reports unavailable when no API key is set."""
    service = GeminiService(api_key=None)
    assert not service.is_available()
    assert service.generate_text("Hola") is None
    assert service.parse_intent("Hola") is None


def test_gemini_service_generate_text_with_mock():
    """Verify GeminiService generates text with mocked client."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockContentResponse("Hola Samuel, ¿en qué te puedo ayudar?")

    service = GeminiService(api_key="test_api_key", client=mock_client)
    with patch.dict("os.environ", {"ENABLE_LLM_FALLBACK": "true"}):
        assert service.is_available()
        response = service.generate_text("Hola")
        assert response == "Hola Samuel, ¿en qué te puedo ayudar?"
        assert mock_client.models.generate_content.called


def test_gemini_service_parse_intent_with_mock():
    """Verify GeminiService parses intent slots from JSON response."""
    intent_json = json.dumps({
        "intent": "finance_entry",
        "confidence": 0.95,
        "slots": {
            "amount_cents": 1500000,
            "transaction_type": "expense",
            "category": "Food & Dining",
            "description": "almuerzo ejecutivo"
        },
        "is_complete": True,
        "missing_slots": []
    })

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockContentResponse(f"```json\n{intent_json}\n```")

    service = GeminiService(api_key="test_api_key", client=mock_client)
    with patch.dict("os.environ", {"ENABLE_LLM_FALLBACK": "true"}):
        res = service.parse_intent("Pagué quince mil por un ejecutivo hoy")
        assert res is not None
        assert res.intent == IntentType.FINANCE_ENTRY
        assert res.confidence == 0.95
        assert res.slots["amount_cents"] == 1500000
        assert res.slots["category"] == "Food & Dining"


def test_gemini_service_chat_response():
    """Verify chat formatting and generation."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockContentResponse("¡Hola Samuel! Estoy listo para ayudarte con tus cuentas y tareas.")

    service = GeminiService(api_key="test_api_key", client=mock_client)
    with patch.dict("os.environ", {"ENABLE_LLM_FALLBACK": "true"}):
        reply = service.chat("¿Cómo estás?")
        assert reply == "¡Hola Samuel! Estoy listo para ayudarte con tus cuentas y tareas."


def test_intent_parser_fallback_to_gemini():
    """Verify IntentParser delegates to Gemini when regex cannot determine intent."""
    intent_json = json.dumps({
        "intent": "task_create",
        "confidence": 0.9,
        "slots": {
            "title": "renovar pasaporte",
            "priority": "high"
        },
        "is_complete": True,
        "missing_slots": []
    })

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockContentResponse(intent_json)
    gemini_svc = GeminiService(api_key="test_api_key", client=mock_client)

    with patch.dict("os.environ", {"ENABLE_LLM_FALLBACK": "true"}):
        parser = IntentParser(gemini_service=gemini_svc)
        # Ambiguous phrase that regex parser doesn't cover
        result = parser.parse("No se me puede pasar por nada del mundo renovar pasaporte")
        assert result.intent == IntentType.TASK_CREATE
        assert result.slots["title"] == "renovar pasaporte"


def test_tool_router_chat_with_gemini():
    """Verify ToolRouter generates natural chat response via Gemini for unknown general queries."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MockContentResponse("El interés compuesto es el interés calculado sobre el capital inicial más los intereses acumulados.")
    gemini_svc = GeminiService(api_key="test_api_key", client=mock_client)

    with patch.dict("os.environ", {"ENABLE_LLM_FALLBACK": "true"}):
        router = ToolRouter(gemini_service=gemini_svc)
        from app.integrations.protocols import IntentResult
        res = router.dispatch("user_123", IntentResult(intent=IntentType.UNKNOWN, confidence=0.1, raw_text="¿Qué es el interés compuesto?"))
        assert "interés compuesto" in res
