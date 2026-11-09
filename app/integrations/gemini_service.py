"""Gemini AI Service integration using the official google-genai SDK.

Provides LLM fallback reasoning, natural language understanding, conversational chat,
email intelligence, and outing recommendations for Samuel Azuero's autonomous assistant.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.integrations.protocols import IntentResult, IntentType

logger = logging.getLogger(__name__)


_UNSET = object()


class GeminiService:
    """Service interfacing with Google Gemini models via google-genai SDK."""

    def __init__(
        self,
        api_key: Any = _UNSET,
        model_name: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        settings = get_settings()
        if api_key is _UNSET:
            self.api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
        else:
            self.api_key = api_key
        self.model_name = model_name or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
        self._client = client
        self._init_attempted = False

    @property
    def client(self) -> Optional[Any]:
        """Lazy load genai client only when needed."""
        if self._client is not None:
            return self._client
        if not self.api_key or not self.api_key.strip():
            return None
        if not self._init_attempted:
            self._init_attempted = True
            try:
                from google import genai
                self._client = genai.Client(
                    api_key=self.api_key.strip(),
                    http_options={"timeout": 15000},
                )
                logger.info("GeminiClient initialized successfully with model: %s", self.model_name)
            except Exception as e:
                logger.error("Failed to initialize Google GenAI Client: %s", e)
                self._client = None
        return self._client

    def is_available(self) -> bool:
        """Returns True if Gemini API is configured and client is ready."""
        settings = get_settings()
        enabled = settings.enable_llm_fallback or os.environ.get("ENABLE_LLM_FALLBACK", "").lower() in ("1", "true", "yes")
        if not enabled:
            return False
        return self.client is not None

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: Optional[int] = 1000,
        response_mime_type: Optional[str] = None,
    ) -> Optional[str]:
        """Generate text using Gemini."""
        if not self.is_available() or self.client is None:
            return None

        # Models to try in priority order if the specified model encounters a version/quota issue
        models_to_try = [
            self.model_name,
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]
        # Remove duplicates while preserving order
        unique_models = list(dict.fromkeys(models_to_try))

        for model in unique_models:
            try:
                from google.genai import types
                config_kwargs: Dict[str, Any] = {
                    "temperature": temperature,
                }
                if max_output_tokens:
                    config_kwargs["max_output_tokens"] = max_output_tokens
                if system_instruction:
                    config_kwargs["system_instruction"] = system_instruction
                if response_mime_type:
                    config_kwargs["response_mime_type"] = response_mime_type

                config = types.GenerateContentConfig(**config_kwargs)
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                if response and hasattr(response, "text") and response.text:
                    return response.text.strip()
            except Exception as e:
                err_str = str(e)
                logger.warning("Gemini generation error with model %s: %s", model, e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "Quota exceeded" in err_str:
                    break
                continue

        return None

    def chat(
        self,
        message: str,
        user_name: str = "Samuel",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[str]:
        """Conversational response for chat queries and questions."""
        system_instruction = (
            f"Eres 'Jar Jar', el asistente personal inteligente y autónomo de {user_name} Azuero. "
            "Responde en español colombiano, con un tono amable, profesional, conciso y proactivo. "
            "Usa formato Markdown claro cuando sea útil. "
            "La moneda oficial del usuario son los Pesos Colombianos (COP). "
            "Nunca uses dólares a menos que el usuario pregunte explícitamente por conversión de divisas. "
            "Si el usuario pregunta sobre sus correos, finanzas o tareas, indícale amablemente cómo pedirte "
            "que las consulte o gestione."
        )

        prompt_parts: List[str] = []
        if history:
            for item in history[-4:]:
                role = "Usuario" if item.get("role") == "user" else "Asistente"
                prompt_parts.append(f"{role}: {item.get('content', '')}")

        prompt_parts.append(f"Usuario: {message}")
        prompt_parts.append("Asistente:")

        full_prompt = "\n".join(prompt_parts)
        return self.generate_text(prompt=full_prompt, system_instruction=system_instruction, temperature=0.7)

    def parse_intent(
        self,
        text: str,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[IntentResult]:
        """Parse natural language into IntentResult with extracted slots using Gemini."""
        if not self.is_available() or self.client is None:
            return None

        system_instruction = (
            "Eres un analizador de intenciones en lenguaje natural para un asistente personal en Colombia. "
            "Tu tarea es analizar el texto del usuario y retornar EXCLUSIVAMENTE un objeto JSON válido con la siguiente estructura:\n"
            "{\n"
            '  "intent": "<intent_type>",\n'
            '  "confidence": <float entre 0.0 y 1.0>,\n'
            '  "slots": {\n'
            '     ...\n'
            "  },\n"
            '  "is_complete": <true o false>,\n'
            '  "missing_slots": []\n'
            "}\n\n"
            "- 'finance_entry': Registra un gasto o ingreso. Slots: 'amount_cents' (entero en centavos COP. 1 peso = 100 centavos. Ej: 10 mil pesos = 1000000 centavos, 5000 pesos = 500000 centavos), 'transaction_type' ('expense' o 'income'), 'category' ('Food & Dining', 'Transportation', 'Groceries', 'Housing & Utilities', 'Entertainment', 'Health & Wellness', 'Education', 'Shopping', 'Other'), 'description' (cadena).\n"
            "- 'finance_query': Consulta de saldo, balance o gastos acumulados.\n"
            "- 'financial_advice': Pedir consejos financieros, diagnóstico o análisis de gastos ('cómo van mis finanzas este mes', 'en qué gasto más', 'consejo financiero', '¿puedo gastar hoy?').\n"
            "- 'task_create': Crear una tarea, recordatorio o pendiente. Slots: 'title' (string), 'due_date' (ISO string si aplica), 'priority' ('low', 'medium', 'high').\n"
            "- 'task_list': Listar tareas o pendientes.\n"
            "- 'task_complete': Marcar como terminada o hecha una tarea ('ya hice...', 'terminé la tarea...', 'marcar como hecha'). Slots: 'query' (string).\n"
            "- 'task_delete': Eliminar, borrar o cancelar una tarea o recordatorio. Slots: 'query' (string).\n"
            "- 'daily_briefing': Resumen del día, buenos días, cómo va mi día, qué tengo para hoy.\n"
            "- 'calendar_schedule': Agendar un evento o cita. Slots: 'title' (string), 'start_time' (ISO string).\n"
            "- 'calendar_query': Consultar eventos o agenda del día/semana.\n"
            "- 'email_check': Revisar correos, verificar bandeja o correos importantes. Slots: 'account' ('personal', 'unimilitar', o 'all').\n"
            "- 'outing_research': Buscar o recomendar planes para salir, restaurantes o actividades. Slots: 'activity', 'cuisine', 'location'.\n"
            "- 'cancel': Cancelar la operación activa.\n"
            "- 'unknown': Si es una conversación general, pregunta abierta, saludo o no coincide con ninguna acción de las anteriores.\n\n"
            "Retorna ÚNICAMENTE el JSON sin formato markdown ni texto adicional."
        )

        prompt = f"Texto del usuario: \"{text}\""
        if session_context and session_context.get("active_intent"):
            prompt += f"\nContexto activo: intent={session_context.get('active_intent')}, pending_slot={session_context.get('pending_slot')}"

        raw_output = self.generate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.1,
            max_output_tokens=500,
            response_mime_type="application/json",
        )
        if not raw_output:
            return None

        # Clean code fences if present
        clean_json = raw_output.strip()
        if clean_json.startswith("```"):
            clean_json = re.sub(r"^```(?:json)?\s*", "", clean_json)
            clean_json = re.sub(r"\s*```$", "", clean_json)
        clean_json = clean_json.strip()

        try:
            data = json.loads(clean_json)
            intent_str = str(data.get("intent", "unknown")).lower()
            try:
                intent_type = IntentType(intent_str)
            except ValueError:
                intent_type = IntentType.UNKNOWN

            slots = data.get("slots", {})
            confidence = float(data.get("confidence", 0.8))
            is_complete = bool(data.get("is_complete", True))
            missing_slots = data.get("missing_slots", [])

            # Smart normalization for Colombian Pesos (COP) cents (1 COP = 100 cents)
            if intent_type == IntentType.FINANCE_ENTRY and "amount_cents" in slots:
                raw_amount = slots["amount_cents"]
                if isinstance(raw_amount, (int, float)) and raw_amount > 0:
                    if ("mil" in text.lower() or "k" in text.lower()) and raw_amount < 1_000_000:
                        slots["amount_cents"] = int(raw_amount * 100)
                    elif raw_amount < 100_000 and any(w in text.lower() for w in ["pesos", "cop", "gaste", "gasté", "pague", "pagué"]):
                        slots["amount_cents"] = int(raw_amount * 100)

            return IntentResult(
                intent=intent_type,
                confidence=confidence,
                slots=slots,
                is_complete=is_complete,
                missing_slots=missing_slots,
                raw_text=text,
            )
        except Exception as e:
            logger.warning("Failed to parse Gemini intent response JSON: %s. Output was: %s", e, raw_output)
            return None

    def summarize_emails(self, emails: List[Dict[str, Any]]) -> Optional[str]:
        """Generate intelligent summary and triage of emails."""
        if not self.is_available() or self.client is None or not emails:
            return None

        system_instruction = (
            "Eres un asistente ejecutivo de correo. Analiza los siguientes correos y genera un "
            "resumen conciso y organizado en Markdown en español. "
            "Identifica si hay mensajes urgentes o de alta prioridad (fechas límite, notificaciones bancarias, avisos de la universidad), "
            "y destaca las acciones requeridas."
        )

        email_summaries = []
        for i, em in enumerate(emails[:10], start=1):
            subj = em.get("subject", "Sin Asunto")
            sender = em.get("sender", "Desconocido")
            date = em.get("date", "")
            snippet = em.get("snippet", "")[:150]
            email_summaries.append(f"{i}. De: {sender} | Asunto: {subj} | Fecha: {date}\n   Contenido: {snippet}")

        prompt = "Correos en bandeja de entrada:\n" + "\n\n".join(email_summaries)
        return self.generate_text(prompt=prompt, system_instruction=system_instruction, temperature=0.3)

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
        """Transcribe user audio or voice note with Gemini."""
        if not self.is_available() or self.client is None or not audio_bytes:
            return None

        from google.genai import types

        models_to_try = [
            self.model_name,
            "gemini-3.5-flash",
            "gemini-3.5-transcribe",
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
        ]
        unique_models = list(dict.fromkeys(models_to_try))

        for model in unique_models:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                        "Transcribe con máxima precisión lo que dice la persona en este audio en español. "
                        "Devuelve ÚNICAMENTE el texto hablado, sin comillas, sin introducciones y sin comentarios adicionales.",
                    ],
                )
                if response and hasattr(response, "text") and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning("Gemini audio transcription error with model %s: %s", model, e)
                continue

        return None
