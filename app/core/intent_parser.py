"""Natural language intent parser and slot extractor."""

import logging
import re
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from app.integrations.protocols import (
    IntentParserProtocol,
    IntentResult,
    IntentType,
    TransactionType,
)


# Standard budget category mapping from keywords
CATEGORY_KEYWORD_MAP = {
    "Groceries": [
        "groceries", "grocery", "supermarket", "trader joe's", "walmart",
        "whole foods", "kroger", "safeway", "aldi", "food shopping", "produce",
        "mercado", "supermercado", "éxito", "exito", "carulla", "jumbo",
        "olímpica", "olimpica", "d1", "ara", "zapatoca", "plaza", "frutas",
        "verduras", "carnicería", "panadería", "víveres"
    ],
    "Food & Dining": [
        "coffee", "starbucks", "latte", "espresso", "lunch", "dinner",
        "breakfast", "brunch", "restaurant", "cafe", "pizza", "burger",
        "sushi", "takeout", "fast food", "chipotle", "subway", "snack",
        "beer", "wine", "drinks", "bar",
        "comida", "almuerzo", "cena", "desayuno", "corrientazo", "restaurante",
        "cafetería", "arepa", "empanada", "hamburguesa", "asado", "tinto",
        "cerveza", "tragos", "domicilio", "rappi"
    ],
    "Transportation": [
        "uber", "lyft", "taxi", "cab", "gas", "fuel", "petrol", "subway pass",
        "metro", "bus", "train", "flight", "airline", "parking", "toll",
        "transmilenio", "sitp", "didi", "cabify", "indrive", "gasolina",
        "peaje", "parqueadero", "pasaje", "pasajes", "colectivo", "soat",
        "buseta", "flota", "chiva", "mula", "moto", "carrera"
    ],
    "Housing & Utilities": [
        "rent", "mortgage", "electric", "electricity", "water bill", "utilities",
        "wifi", "internet", "gas bill", "heating", "maintenance", "hoa", "power",
        "arriendo", "alquiler", "administración", "servicios", "luz", "agua",
        "gas", "enel", "codensa", "acueducto", "vanti", "claro", "tigo", "movistar", "etb"
    ],
    "Entertainment": [
        "movie", "cinema", "netflix", "spotify", "hulu", "disney", "concert",
        "game", "steam", "playstation", "xbox", "theater", "festival", "show",
        "entretenimiento", "cine", "concierto", "partido", "fútbol", "fiesta",
        "rumba", "discoteca", "paseo", "viaje", "boletas"
    ],
    "Health & Wellness": [
        "pharmacy", "medicine", "prescription", "doctor", "dentist", "gym",
        "fitness", "therapy", "hospital", "clinic", "vitamins",
        "salud", "droguería", "farmacia", "cruz verde", "la rebaja", "médico",
        "medico", "cita médica", "odontólogo", "dentista", "eps", "gimnasio", "gym"
    ],
    "Shopping": [
        "amazon", "clothes", "shoes", "clothing", "apparel", "electronics",
        "gadget", "furniture", "book", "books", "department store",
        "compras", "ropa", "zapatos", "centro comercial", "falabella",
        "alkosto", "ktronix", "mercadolibre", "celular", "computador"
    ],
    "Income": [
        "salary", "paycheck", "freelance", "dividend", "bonus", "reimbursement",
        "consulting", "stipend", "wages", "interest",
        "sueldo", "salario", "nómina", "nomina", "honorarios", "quincena",
        "prima", "ingreso", "pago"
    ],
}


class IntentParser(IntentParserProtocol):
    """Rule-based and heuristic NLP intent parser with slot extraction."""

    def __init__(
        self,
        reference_time: Optional[datetime] = None,
        gemini_service: Optional[Any] = None,
    ) -> None:
        self._reference_time = reference_time
        self.gemini_service = gemini_service

    @property
    def reference_time(self) -> datetime:
        """Return reference time if explicitly set, else current time in America/Bogota."""
        if self._reference_time is not None:
            return self._reference_time
        try:
            import zoneinfo
            return datetime.now(zoneinfo.ZoneInfo("America/Bogota"))
        except Exception:
            return datetime.now()

    @reference_time.setter
    def reference_time(self, val: Optional[datetime]) -> None:
        self._reference_time = val

    @property
    def effective_gemini_service(self) -> Optional[Any]:
        """Lazy load or return Gemini service instance."""
        if self.gemini_service is not None:
            return self.gemini_service
        try:
            from app.integrations.gemini_service import GeminiService
            self.gemini_service = GeminiService()
            return self.gemini_service
        except Exception:
            return None

    def parse(
        self, text: str, session_context: Optional[Dict[str, Any]] = None
    ) -> IntentResult:
        """Parse natural language string into structured IntentResult."""
        cleaned = text.strip()
        # Strip leading emojis commonly sent from Telegram shortcut buttons (e.g. 📊, 📋, 📬, ❌)
        clean_no_emoji = re.sub(r"^[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\s]+", "", cleaned).strip()
        lower_text = clean_no_emoji.lower() if clean_no_emoji else cleaned.lower()

        # 1. Check for cancel intent first
        if self._is_cancel(lower_text):
            return IntentResult(
                intent=IntentType.CANCEL,
                confidence=1.0,
                slots={},
                is_complete=True,
                missing_slots=[],
                raw_text=cleaned,
            )

        # 2. Check for multi-turn follow-up if session_context has pending intent
        if session_context and session_context.get("active_intent"):
            active_intent_val = session_context["active_intent"]
            active_intent = (
                active_intent_val
                if isinstance(active_intent_val, IntentType)
                else IntentType(str(active_intent_val))
            )

            # Check if user is obviously switching to a totally different high-confidence intent
            switched_intent = self._detect_clear_switch(lower_text)
            if not switched_intent:
                resolved = self._resolve_follow_up(
                    cleaned, lower_text, active_intent, session_context
                )
                if resolved is not None:
                    return resolved

        # 2b. Daily briefing (morning update / daily overview)
        daily_briefing = self._parse_daily_briefing(cleaned, lower_text)
        if daily_briefing:
            return daily_briefing

        # 3. Explicit Task creation / Reminder (check before finance to avoid "expense report" collision)
        task_create = self._parse_task_create(cleaned, lower_text)
        if task_create:
            return task_create

        # 3b. Task Complete (e.g. "ya hice...", "completé...", "marcar como hecha")
        task_complete = self._parse_task_complete(cleaned, lower_text)
        if task_complete:
            return task_complete

        # 4. Task List queries
        task_list = self._parse_task_list(cleaned, lower_text)
        if task_list:
            return task_list

        # 4b. Task Delete queries
        task_delete = self._parse_task_delete(cleaned, lower_text)
        if task_delete:
            return task_delete

        # 5. Calendar Query (check before calendar schedule so "what is on my schedule" is treated as query)
        calendar_query = self._parse_calendar_query(cleaned, lower_text)
        if calendar_query:
            return calendar_query

        # 6. Calendar Schedule
        calendar_schedule = self._parse_calendar_schedule(cleaned, lower_text)
        if calendar_schedule:
            return calendar_schedule

        # 7. Finance Entry (Expense or Income)
        finance_entry = self._parse_finance_entry(cleaned, lower_text)
        if finance_entry:
            return finance_entry

        # 8a. Financial Advice & Diagnosis
        fin_advice = self._parse_financial_advice(cleaned, lower_text)
        if fin_advice:
            return fin_advice

        # 8b. Finance Query
        finance_query = self._parse_finance_query(cleaned, lower_text)
        if finance_query:
            return finance_query

        # 9. Email Check
        email_check = self._parse_email_check(cleaned, lower_text)
        if email_check:
            return email_check

        # 10. Outing Research
        outing_research = self._parse_outing_research(cleaned, lower_text)
        if outing_research:
            return outing_research

        # 11. LLM Fallback (Gemini) if enabled and available
        svc = self.effective_gemini_service
        if svc and svc.is_available():
            try:
                llm_result = svc.parse_intent(cleaned, session_context=session_context)
                if llm_result and llm_result.intent != IntentType.UNKNOWN:
                    return llm_result
            except Exception as e:
                logger.warning("Error running Gemini fallback intent parsing: %s", e)

        # 12. Unknown / Fallback
        return IntentResult(
            intent=IntentType.UNKNOWN,
            confidence=0.1,
            slots={},
            is_complete=True,
            missing_slots=[],
            raw_text=cleaned,
        )

    # -------------------------------------------------------------------------
    # Helper & Detection Methods
    # -------------------------------------------------------------------------

    def _is_cancel(self, text: str) -> bool:
        cancel_patterns = [
            r"^/cancel\b",
            r"^cancel\b",
            r"^cancelar\b",
            r"^cancela\b",
            r"^abort\b",
            r"^stop\b",
            r"^salir\b",
            r"^detener\b",
            r"^parar\b",
            r"^nevermind\b",
            r"^never mind\b",
            r"^olvídalo\b",
            r"^olvidalo\b",
            r"^quit\b",
            r"^exit\b",
        ]
        return any(re.search(pat, text) for pat in cancel_patterns)

    def _detect_clear_switch(self, text: str) -> bool:
        """Determine if the user wants to break out of follow-up into a new command."""
        switch_indicators = [
            "what is my balance", "check balance", "check my emails",
            "show my tasks", "schedule meeting", "find restaurants",
            "show my schedule", "what is on my schedule", "check schedule",
            "cuál es mi saldo", "cual es mi saldo", "mi saldo", "mis correos",
            "revisar correos", "mis tareas", "agendar", "buscar restaurantes",
            "/start", "/help", "help", "ayuda"
        ]
        return any(ind in text for ind in switch_indicators)

    def _resolve_follow_up(
        self,
        cleaned: str,
        lower: str,
        active_intent: IntentType,
        session_context: Dict[str, Any],
    ) -> Optional[IntentResult]:
        """Resolve missing slots in a multi-turn conversation."""
        pending_slots = dict(session_context.get("slots", {}))
        missing_slots = list(session_context.get("missing_slots", []))

        if active_intent == IntentType.FINANCE_ENTRY:
            amount_cents = self._extract_amount_cents(cleaned)
            if amount_cents is not None and "amount" in missing_slots:
                pending_slots["amount_cents"] = amount_cents
                missing_slots.remove("amount")

            desc_cand = self._extract_finance_description(cleaned, cleaned.lower())
            if not desc_cand and amount_cents is None:
                desc_cand = cleaned.strip()

            if desc_cand:
                curr_desc = str(pending_slots.get("description", "")).lower()
                is_placeholder = any(p in curr_desc for p in ["log an", "want to", "expense", "transaction", ""])
                if "description" in missing_slots or is_placeholder:
                    pending_slots["description"] = desc_cand
                    pending_slots["category"] = self._infer_category(desc_cand)
                    if "description" in missing_slots:
                        missing_slots.remove("description")

            is_complete = len(missing_slots) == 0
            return IntentResult(
                intent=active_intent,
                confidence=0.95,
                slots=pending_slots,
                is_complete=is_complete,
                missing_slots=missing_slots,
                raw_text=cleaned,
            )

        if active_intent == IntentType.CALENDAR_SCHEDULE:
            time_cand = self._extract_datetime(cleaned)
            if time_cand and "start_time" in missing_slots:
                pending_slots["start_time"] = time_cand
                if "end_time" not in pending_slots:
                    pending_slots["end_time"] = time_cand + timedelta(hours=1)
                missing_slots.remove("start_time")

            title_cand = None
            if "meeting with" in cleaned.lower():
                m_with = re.search(
                    r"(meeting with .+?)(?:\s+(?:at|on|in|tomorrow|today)\b|$)",
                    cleaned,
                    re.IGNORECASE,
                )
                if m_with:
                    title_cand = m_with.group(1).strip()
            elif not time_cand:
                title_cand = cleaned

            if title_cand:
                curr_title = str(pending_slots.get("title", "")).strip().lower()
                if "title" in missing_slots or curr_title in ("meeting", "event", "new event", ""):
                    pending_slots["title"] = title_cand
                    if "title" in missing_slots:
                        missing_slots.remove("title")

            is_complete = len(missing_slots) == 0
            return IntentResult(
                intent=active_intent,
                confidence=0.95,
                slots=pending_slots,
                is_complete=is_complete,
                missing_slots=missing_slots,
                raw_text=cleaned,
            )

        if active_intent == IntentType.TASK_CREATE:
            if "title" in missing_slots:
                pending_slots["title"] = cleaned
                missing_slots.remove("title")
                due_date = self._extract_datetime(cleaned)
                if due_date:
                    pending_slots["due_date"] = due_date

            is_complete = len(missing_slots) == 0
            return IntentResult(
                intent=active_intent,
                confidence=0.95,
                slots=pending_slots,
                is_complete=is_complete,
                missing_slots=missing_slots,
                raw_text=cleaned,
            )

        return None

    # -------------------------------------------------------------------------
    # Intent Extractors
    # -------------------------------------------------------------------------

    def _parse_task_create(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect to-do item and reminder creation."""
        trigger_patterns = [
            r"^remind me to\s+(.+)$",
            r"^recuérdame\s+(?:que\s+|a\s+)?(.+)$",
            r"^recuerdame\s+(?:que\s+|a\s+)?(.+)$",
            r"^recordarme\s+(?:que\s+|a\s+)?(.+)$",
            r"^add task[:\s]+(.+)$",
            r"^create task[:\s]+(.+)$",
            r"^new task[:\s]+(.+)$",
            r"^crear tarea[:\s]+(.+)$",
            r"^nueva tarea[:\s]+(.+)$",
            r"^agregar tarea[:\s]+(.+)$",
            r"^anotar[:\s]+(.+)$",
            r"^anota[:\s]+(.+)$",
            r"^todo[:\s]+(.+)$",
            r"^to-do[:\s]+(.+)$",
            r"^tarea[:\s]+(.+)$",
            r"^remember to\s+(.+)$",
            r"^put (.+) on my (todo|task) list$",
            r"^poner (.+) en mi lista de tareas$",
        ]

        task_text = None
        for pat in trigger_patterns:
            m = re.search(pat, lower)
            if m:
                task_text = m.group(1).strip()
                break

        if not task_text:
            return None

        # Extract priority if specified
        priority = "medium"
        for p in ["urgent", "urgente", "high", "alta", "low", "baja"]:
            if re.search(rf"\b{p}\s+priority\b|\bpriority\s*[:=]?\s*{p}\b|\bprioridad\s*[:=]?\s*{p}\b|\b{p}\b", task_text):
                if p in ("urgent", "urgente"):
                    priority = "urgent"
                elif p in ("high", "alta"):
                    priority = "high"
                elif p in ("low", "baja"):
                    priority = "low"
                task_text = re.sub(rf"\b{p}\s+priority\b|\bpriority\s*[:=]?\s*{p}\b|\bprioridad\s*[:=]?\s*{p}\b", "", task_text).strip()
                break

        # Extract due date if specified
        due_date = self._extract_datetime(task_text)

        # Clean title by stripping datetime references and conversational prefixes
        clean_title = task_text
        # 1. Strip leading time expressions (e.g. "mañana a las 10am", "el viernes", "hoy", "en 10 minutos")
        clean_title = re.sub(
            r"^(?:para\s+)?(?:mañana|manana|hoy|tomorrow|today|el\s+(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|\d{1,2}))\s*(?:a\s+las\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm|de\s+la\s+mañana|de\s+la\s+tarde|de\s+la\s+noche))?\s*)?",
            "",
            clean_title,
            flags=re.IGNORECASE,
        ).strip()
        clean_title = re.sub(r"^(?:in \d+\s*(?:hours?|minutes?|mins?)|en \d+\s*(?:horas?|minutos?|mins?))\s*", "", clean_title, flags=re.IGNORECASE).strip()
        clean_title = re.sub(r"^(?:a las\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm|de la mañana|de la tarde|de la noche))?|at\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?)\s*", "", clean_title, flags=re.IGNORECASE).strip()
        clean_title = re.sub(r"^(?:que tengo que|tengo que|de|por favor)\s+", "", clean_title, flags=re.IGNORECASE).strip()

        # 2. Strip trailing time expressions (e.g. "... mañana a las 10am", "... a las 8pm", "... en 10 minutos")
        clean_title = re.sub(
            r"\s+(?:(?:para\s+)?(?:mañana|manana|hoy|tomorrow|today|el\s+(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo))\s+)?(?:a\s+las\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm|de\s+la\s+mañana|de\s+la\s+tarde|de\s+la\s+noche))?|at\s+\d{1,2}(?::\d{2})?(?:\s*(?:am|pm))?)\s*[\.]*$",
            "",
            clean_title,
            flags=re.IGNORECASE,
        ).strip()
        clean_title = re.sub(
            r"\s+(?:para\s+)?(?:mañana|manana|hoy|tomorrow|today|el\s+(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo))\s*[\.]*$",
            "",
            clean_title,
            flags=re.IGNORECASE,
        ).strip()
        clean_title = re.sub(
            r"\s+(?:in \d+\s*(?:hours?|minutes?|mins?)|en \d+\s*(?:horas?|minutos?|mins?))\s*[\.]*$",
            "",
            clean_title,
            flags=re.IGNORECASE,
        ).strip()
        clean_title = clean_title.rstrip(".").strip()

        # 3. If title is empty or unparsed, check Gemini fallback
        if not clean_title and self.effective_gemini_service and self.effective_gemini_service.is_available():
            try:
                gemini_res = self.effective_gemini_service.parse_intent(raw)
                if gemini_res and gemini_res.intent == IntentType.TASK_CREATE and gemini_res.slots.get("title"):
                    return gemini_res
            except Exception as ge:
                logger.warning("Gemini task parse fallback error: %s", ge)

        missing = []
        if not clean_title:
            missing.append("title")

        slots: Dict[str, Any] = {
            "title": clean_title,
            "priority": priority,
        }
        if due_date:
            slots["due_date"] = due_date

        return IntentResult(
            intent=IntentType.TASK_CREATE,
            confidence=0.90,
            slots=slots,
            is_complete=len(missing) == 0,
            missing_slots=missing,
            raw_text=raw,
        )

    def _parse_task_list(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect task list queries."""
        list_patterns = [
            r"\b(show|list|view|get|check)\s+(?:(?:my|all|completed|pending|active)\s+)*(to-?dos?|tasks?|reminders?)\b",
            r"\b(mostrar|ver|listar|mis)\s+(?:(?:mis|todas las|las|completadas|pendientes)\s+)*(tareas|pendientes|recordatorios|to-?dos?)\b",
            r"^(my\s+)?(to-?dos?|tasks?|reminders?)$",
            r"^(mis\s+)?(tareas|pendientes|recordatorios)$",
            r"\bwhat are my (tasks|to-?dos|reminders)\b",
            r"\bwhat do i have to do\b",
            r"\bqué tengo pendiente\b",
            r"\bque tengo pendiente\b",
            r"\bcuáles son mis tareas\b",
            r"\bcuales son mis tareas\b",
        ]
        if not any(re.search(p, lower) for p in list_patterns):
            return None

        status = "pending"
        if "completed" in lower or "done" in lower or "completadas" in lower or "hechas" in lower:
            status = "completed"
        elif "all" in lower or "todas" in lower:
            status = "all"

        return IntentResult(
            intent=IntentType.TASK_LIST,
            confidence=0.92,
            slots={"status": status},
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_daily_briefing(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect morning update or daily briefing requests."""
        triggers = [
            r"^(buenos días|buenos dias|buen día|buen dia)\b",
            r"\b(cómo va mi día|como va mi dia|resumen del día|resumen del dia|resumen de hoy|qué tengo para hoy|que tengo para hoy|qué tengo hoy|que tengo hoy|cómo está mi día|como esta mi dia)\b",
            r"\b(daily briefing|morning briefing|morning update|briefing de hoy|briefing del día)\b",
            r"^resumen de hoy$",
            r"^cómo va mi día$",
            r"^buenos días$",
        ]
        if any(lower.startswith(w) for w in ["gasté", "pagué", "compré", "recuérdame", "recordarme", "crear tarea"]):
            return None

        if any(re.search(p, lower) for p in triggers):
            return IntentResult(
                intent=IntentType.DAILY_BRIEFING,
                confidence=0.95,
                slots={},
                is_complete=True,
                missing_slots=[],
                raw_text=raw,
            )
        return None

    def _parse_task_complete(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect task completion requests (e.g. 'ya hice...', 'marcar como hecha', 'completé')."""
        complete_triggers = [
            r"\b(ya hice|ya terminé|ya termine|completé|complete|terminé|termine|marcar como hecha|marcar como completada|marcar hecha|tarea hecha|completar tarea|completar)\b",
            r"^done\b",
            r"^complete task\b",
            r"^mark as done\b",
        ]
        if not any(re.search(p, lower) for p in complete_triggers):
            return None

        m = re.search(r"(?:ya hice|ya terminé|ya termine|completé|complete|terminé|termine|marcar como hecha|marcar como completada|marcar hecha|tarea hecha|completar tarea|completar|complete task|mark as done)\s+(?:la\s+|el\s+|mi\s+|tarea\s+|de\s+)?(.+)$", lower)
        query = m.group(1).strip() if m else None
        if query in ("de", "para", "el", "la", "las", "los", "hoy", "por favor", "que tengo"):
            query = None

        slots: Dict[str, Any] = {}
        if query:
            slots["query"] = query
            slots["title"] = query

        return IntentResult(
            intent=IntentType.TASK_COMPLETE,
            confidence=0.92,
            slots=slots,
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_task_delete(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect task deletion commands."""
        delete_patterns = [
            r"\b(elimina|eliminar|borra|borrar|quitar|quítale|quitale|quita|quítame|quitame|cancelar|cancela)\s+(?:el|la|mi|las|de|le|los)?\s*(?:task|tasks|tarea|tareas|pendiente|pendientes|recordatorio|recordatorios)\b",
            r"^delete task\b",
            r"^remove task\b",
            r"^eliminar tarea\b",
            r"^borrar tarea\b",
            r"^elimina el task\b",
            r"\bquitarle tareas\b",
            r"\bquitar tareas\b",
            r"\bborrar tareas\b",
            r"\beliminar tareas\b",
            r"\bquitar tarea\b",
        ]
        if not any(re.search(p, lower) for p in delete_patterns):
            return None

        m = re.search(r"(?:elimina|eliminar|borra|borrar|quitar|quítale|quitale|quita|quítame|quitame|cancelar|cancela|delete task|remove task)\s+(?:el|la|mi|las|de|le|los)?\s*(?:task|tasks|tarea|tareas|pendiente|pendientes|recordatorio|recordatorios)?\s*(?:de\s+|para\s+)?(.+)$", lower)
        title = m.group(1).strip() if m else None
        if title in ("de", "para", "el", "la", "las", "los", "hoy", "por favor", "que tengo"):
            title = None
        slots: Dict[str, Any] = {}
        if title:
            slots["title"] = title
            slots["query"] = title
        return IntentResult(
            intent=IntentType.TASK_DELETE,
            confidence=0.92,
            slots=slots,
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_calendar_query(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect calendar query and availability checks."""
        query_patterns = [
            r"\bam i free\b",
            r"\bis (there|my) (anything|schedule)\b",
            (
                r"\bwhat('?s| is| are)\s+(?:on\s+)?"
                r"(?:(?:my|the|today'?s|tomorrow'?s)\s+)*(?:calendar|schedule|agenda|meetings?|events?)\b"
            ),
            (
                r"\bwhat\s+(?:do\s+i\s+have|is)\s+"
                r"(?:scheduled|on\s+my\s+schedule|on\s+my\s+calendar|on\s+the\s+schedule)\b"
            ),
            r"\bwhat\s+does\s+my\s+schedule\s+look\s+like\b",
            r"\bwhat\s+(?:meetings?|events?)\s+(?:do\s+i\s+have|are\s+there)\b",
            (
                r"\b(show|view|list|check|display|get|see|read|tell\s+me)\s+(?:me\s+)?"
                r"(?:(?:my|the|today'?s|tomorrow'?s)\s+)*(?:calendar|schedule|agenda|events?|meetings?|appointments?)\b"
            ),
            r"\bdo i have (?:any\s+)?(?:meetings?|events?|plans?|appointments?|anything scheduled)\b",
            (
                r"\bany\s+(?:meetings?|events?|plans?|appointments?)\s*"
                r"(?:today|tomorrow|scheduled|for\s+today|for\s+tomorrow|this\s+week)?\b"
            ),
            r"^(?:my\s+)?(?:calendar|schedule|agenda)(?:\s+(?:for\s+)?(?:today|tomorrow|this\s+week))?$",
            r"^(?:today'?s|tomorrow'?s)\s+(?:calendar|schedule|agenda)$",
            r"^(?:what\s+is\s+)?schedule\s+for\s+(?:today|tomorrow|[a-z]+)$",
            r"\b(qué|que) tengo (hoy|mañana|agendado|programado)\b",
            r"\b(qué|que) tengo (?:en mi agenda|en mi calendario|hoy|mañana|agendado|programado)\b",
            r"\b(qué|que) tengo\b.*?\b(agenda|calendario|reunión|reuniones|cita|citas|hoy|mañana)\b",
            r"\b(cuál|cual) es mi (agenda|horario|calendario)\b",
            r"\b(mostrar|ver|revisar|revisa)\s+(?:mi\s+)?(agenda|calendario|reuniones|eventos)\b",
            r"\bestoy libre\b",
            r"\btengo (alguna reunión|reuniones|eventos|citas)\b",
            r"^(mi\s+)?(agenda|calendario)$",
        ]
        if not any(re.search(p, lower) for p in query_patterns):
            return None

        start_time = self._extract_datetime(raw) or self.reference_time
        end_time = start_time + timedelta(days=1)

        return IntentResult(
            intent=IntentType.CALENDAR_QUERY,
            confidence=0.90,
            slots={"start_time": start_time, "end_time": end_time},
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_calendar_schedule(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect calendar event creation requests."""
        # 1. Strictly exclude question/query patterns asking about schedule or availability
        query_indicators = [
            r"\bwhat('?s| is| are)\b",
            r"\bam i free\b",
            r"\bdo i have\b",
            r"\bshow\b",
            r"\bview\b",
            r"\bcheck\s+(?:me\s+)?(?:my\s+|the\s+)?(?:schedule|calendar)\b",
            r"\blist\s+(?:me\s+)?(?:my\s+|the\s+)?(?:schedule|calendar|events|meetings)\b",
            r"\bany\s+(?:meetings?|events?|plans?)\b",
            r"^(?:my\s+)?schedule(?:\s+(?:for\s+)?(?:today|tomorrow|this\s+week))?$",
            r"^(?:today'?s|tomorrow'?s)\s+schedule$",
            r"^schedule\s+for\s+(?:today|tomorrow|[a-z]+)$",
            r"\b(qué|que) tengo\b",
            r"\b(cuál|cual) es mi\b",
            r"\bestoy libre\b",
        ]
        if any(re.search(qi, lower) for qi in query_indicators):
            return None

        # 2. Check for action triggers
        triggers = [
            "schedule a", "schedule an", "schedule the", "schedule meeting",
            "schedule call", "schedule lunch", "schedule dinner", "schedule appointment",
            "schedule session", "book", "set up a meeting", "create event",
            "calendar appointment", "add to calendar",
            "agendar", "programar reunión", "programar reunion", "programar cita",
            "programar evento", "crear evento", "reservar", "reunión con", "reunion con",
            "cita con"
        ]
        has_trigger = any(t in lower for t in triggers)
        is_action_schedule = bool(re.search(r"^(?:please\s+)?schedule\s+[a-zA-Z]", lower)) or bool(re.search(r"^(?:por favor\s+)?(?:agendar|programar)\s+[a-zA-Z]", lower))
        is_meeting_format = bool(re.search(r"\b(meeting|reunión|reunion|cita) with\b|\breunión con\b|\breunion con\b|\bcita con\b", lower))

        if not (has_trigger or is_action_schedule or is_meeting_format):
            return None

        # Extract title
        title = None
        m_title = re.search(
            r"(?:schedule|book|create event|agendar|programar|crear evento|reservar)\s+(?:a\s+|an\s+|un\s+|una\s+)?(.+?)(?:\s+(?:at|on|in|tomorrow|today|next|this|a las|el|para|mañana|hoy)\b|$)",
            raw,
            re.IGNORECASE,
        )
        if m_title and m_title.group(1).strip():
            title = m_title.group(1).strip()
        elif "meeting with" in lower:
            m_with = re.search(
                r"(meeting with [^at|on|in]+?)(?:\s+(?:at|on|in|tomorrow|today)\b|$)",
                raw,
                re.IGNORECASE,
            )
            if m_with:
                title = m_with.group(1).strip()
        elif "reunión con" in lower or "reunion con" in lower or "cita con" in lower:
            m_with = re.search(
                r"((?:reunión|reunion|cita) con [^a las|el|para|mañana|hoy]+?)(?:\s+(?:a las|el|para|mañana|hoy)\b|$)",
                raw,
                re.IGNORECASE,
            )
            if m_with:
                title = m_with.group(1).strip()

        start_time = self._extract_datetime(raw)
        missing: List[str] = []
        slots: Dict[str, Any] = {}

        if title:
            slots["title"] = title
        else:
            missing.append("title")

        if start_time:
            slots["start_time"] = start_time
            slots["end_time"] = start_time + timedelta(hours=1)
        else:
            missing.append("start_time")

        # Extract location if present
        loc_m = re.search(
            r"\b(?:at|in)\s+([A-Z][a-zA-Z0-9\s]+(?:Room|Office|Starbucks|Cafe|Center|Hall|Building)?)\b",
            raw,
        )
        if loc_m and not self._extract_datetime(loc_m.group(0)):
            slots["location"] = loc_m.group(1).strip()
        else:
            slots["location"] = ""

        is_complete = len(missing) == 0
        return IntentResult(
            intent=IntentType.CALENDAR_SCHEDULE,
            confidence=0.88,
            slots=slots,
            is_complete=is_complete,
            missing_slots=missing,
            raw_text=raw,
        )

    def _parse_finance_entry(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract finance transactions (expense or income)."""
        # Exclude commands that are tasks or reminders
        if lower.startswith("add task") or lower.startswith("remind me to") or lower.startswith("todo") or lower.startswith("crear tarea") or lower.startswith("recuérdame") or lower.startswith("recuerdame"):
            return None

        income_words = [
            "received", "got paid", "salary", "deposit", "earned", "income",
            "dividend", "bonus", "reimbursement", "paycheck",
            "ingreso", "ingresos", "me pagaron", "recibí", "recibi", "gané", "gane",
            "sueldo", "salario", "nómina", "nomina", "honorarios", "quincena", "prima"
        ]
        expense_words = [
            "spent", "pay", "paid", "bought", "purchase", "purchased",
            "expense", "cost", "fee", "charged",
            "gasté", "gaste", "pagué", "pague", "compré", "compre", "consumí", "consumi",
            "costó", "costo", "me costó", "pago", "compra"
        ]

        has_income = any(re.search(rf"\b{w}\b", lower) for w in income_words)
        has_expense = any(re.search(rf"\b{w}\b", lower) for w in expense_words)

        amount_cents = self._extract_amount_cents(raw)

        # Check for explicit patterns like "Lunch $15", "$45 on groceries", "Coffee $5", "Almuerzo $50.000", "Taxi 25 mil"
        price_regex = (
            r"(?:[\$€£]\s*(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d{1,2})?|"
            r"(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*(?:dollars|bucks|usd|cop|pesos|mil|k|millones|millón))"
        )
        price_pattern = re.search(price_regex, lower)

        if not (has_income or has_expense or (amount_cents and price_pattern)):
            return None

        # Determine transaction type
        t_type = TransactionType.INCOME if has_income else TransactionType.EXPENSE

        # Extract description and category
        desc = self._extract_finance_description(raw, lower)
        category = self._infer_category(desc or raw) if desc else "Other"
        if t_type == TransactionType.INCOME and category == "Other":
            category = "Income"

        slots: Dict[str, Any] = {
            "transaction_type": t_type.value,
            "category": category,
        }
        missing_slots: List[str] = []

        if amount_cents is not None:
            slots["amount_cents"] = amount_cents
        else:
            missing_slots.append("amount")

        if desc:
            slots["description"] = desc
        else:
            missing_slots.append("description")

        is_complete = len(missing_slots) == 0
        confidence = 0.90 if is_complete else 0.75

        return IntentResult(
            intent=IntentType.FINANCE_ENTRY,
            confidence=confidence,
            slots=slots,
            is_complete=is_complete,
            missing_slots=missing_slots,
            raw_text=raw,
        )

    def _parse_financial_advice(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect requests for financial advice, spending diagnosis, or budget recommendations."""
        triggers = [
            r"\b(consejo financiero|consejos financieros|consejo de gastos|consejo sobre mis gastos)\b",
            r"\b(diagnóstico financiero|diagnostico financiero|cómo van mis finanzas este mes|analiza mis finanzas|analizar mis finanzas|diagnóstico de mis gastos)\b",
            r"\b(en qué estoy gastando más|en que estoy gastando mas|en qué he gastado más|en que he gastado mas)\b",
            r"\b(puedo gastar hoy|puedo gastar este fin de semana|puedo gastar dinero|¿puedo gastar\?)\b",
            r"\b(cómo puedo ahorrar|como puedo ahorrar|recomiéndame sobre mis finanzas|recomendación financiera)\b",
        ]
        if any(re.search(p, lower) for p in triggers):
            return IntentResult(
                intent=IntentType.FINANCIAL_ADVICE,
                confidence=0.92,
                slots={},
                is_complete=True,
                missing_slots=[],
                raw_text=raw,
            )
        return None

    def _parse_finance_query(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect balance queries, spending summaries, and category breakdowns."""
        # Must not be a record/entry command
        if re.search(r"\b(spent|paid|bought|received|earned|deposit|gasté|gaste|pagué|pague|compré|compre|recibí|recibi)\b", lower):
            return None

        balance_words = [
            "balance", "how much money do i have", "current balance", "account balance",
            "saldo", "cuál es mi saldo", "cual es mi saldo", "cuanto tengo", "cuánto tengo",
            "cuánto dinero tengo", "cuanto dinero tengo", "mi saldo", "estado de cuenta", "balance general"
        ]
        summary_words = [
            "financial summary", "spending summary", "how much did i spend",
            "total spending", "total expense",
            "resumen financiero", "resumen de gastos", "cómo van mis finanzas", "como van mis finanzas",
            "mis finanzas", "cuánto he gastado", "cuanto he gastado", "total gastos"
        ]
        breakdown_words = [
            "breakdown", "category breakdown", "spending by category",
            "where did my money go", "expenses by category",
            "desglose", "en qué gasté", "en que gaste", "gastos por categoría", "gastos por categoria",
            "categorías de gasto", "categorias de gasto", "distribución de gastos"
        ]

        query_type = None
        if any(w in lower for w in breakdown_words):
            query_type = "breakdown"
        elif any(w in lower for w in balance_words):
            query_type = "balance"
        elif any(w in lower for w in summary_words) or ("spending" in lower and "show" in lower):
            query_type = "summary"
        elif re.search(r"\b(show|view|check|mostrar|ver|revisar|revisa)\s+(my\s+|mis\s+)?(expenses|spending|finances|gastos|finanzas)\b", lower):
            query_type = "summary"

        if not query_type:
            return None

        # Extract optional month
        month = None
        now_dt = datetime.now(timezone.utc)
        if "this month" in lower or "current month" in lower or "este mes" in lower:
            month = now_dt.strftime("%Y-%m")
        elif "last month" in lower or "mes pasado" in lower or "el mes anterior" in lower:
            first_day = now_dt.replace(day=1)
            prev_month = first_day - timedelta(days=1)
            month = prev_month.strftime("%Y-%m")
        else:
            m_match = re.search(r"\b(\d{4}-\d{2})\b", lower)
            if m_match:
                month = m_match.group(1)

        slots = {"query_type": query_type}
        if month:
            slots["month"] = month

        return IntentResult(
            intent=IntentType.FINANCE_QUERY,
            confidence=0.92,
            slots=slots,
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_email_check(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect email queries, digest requests, and unread checks."""
        email_keywords = ["email", "emails", "inbox", "gmail", "mail", "correo", "correos", "bandeja", "mensajes"]
        action_keywords = [
            "check", "show", "unread", "digest", "summary", "any", "read", "list", "get",
            "revisar", "revisa", "ver", "leer", "mostrar", "resumen", "hay", "tengo", "cuáles", "cuales",
            "qué", "que", "llegaron", "llegó", "llego", "recibidos", "nuevos",
            "cuál", "cual", "último", "ultimo", "ultimos", "últimos"
        ]

        has_email = any(re.search(rf"\b{w}\b", lower) for w in email_keywords)
        has_action = any(re.search(rf"\b{w}\b", lower) for w in action_keywords)

        if not (has_email and has_action):
            return None

        urgent_only = bool(re.search(r"\b(urgent|important|critical|priority|urgente|urgentes|importante|importantes|prioritario)\b", lower))
        limit = 5
        if any(w in lower for w in ["último", "ultimo", "latest", "last"]):
            limit = 1
        else:
            limit_match = re.search(r"\b(\d+)\s*(emails|messages|correos|mensajes)?\b", lower)
            if limit_match and int(limit_match.group(1)) <= 50:
                limit = int(limit_match.group(1))

        account = None
        if "personal" in lower:
            account = "personal"
        elif any(w in lower for w in ["unimilitar", "universidad", "institucional"]):
            account = "unimilitar"

        slots: Dict[str, Any] = {"urgent_only": urgent_only, "limit": limit}
        if account:
            slots["account"] = account

        return IntentResult(
            intent=IntentType.EMAIL_CHECK,
            confidence=0.90,
            slots=slots,
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_outing_research(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect recommendations for dining, outings, and leisure."""
        triggers = [
            "recommend", "suggest", "find", "places to eat", "good restaurants",
            "outing", "things to do", "activities", "weekend plans",
            "recomendar", "recomienda", "recomiéndame", "recomiendame", "buscar planes",
            "planes para salir", "sitios para comer", "buenos restaurantes", "lugares para visitar",
            "qué hacer en", "que hacer en", "actividades en", "planes en"
        ]
        if not any(t in lower for t in triggers):
            return None

        # Exclude task creation or finance commands
        if lower.startswith("remind me to") or lower.startswith("add task") or lower.startswith("recuérdame") or lower.startswith("crear tarea"):
            return None

        # Detect cuisine
        cuisines = [
            "italian", "mexican", "japanese", "chinese", "thai", "sushi",
            "pizza", "indian", "french", "burger", "vegan", "coffee",
            "italiana", "mexicana", "japonesa", "china", "hamburguesa", "asado", "café", "postres", "criolla", "colombiana"
        ]
        cuisine = None
        for c in cuisines:
            if c in lower:
                cuisine = c.capitalize()
                break

        # Detect activity type
        activities = [
            "outdoor", "hiking", "museum", "bowling", "cinema",
            "park", "nightlife", "bar",
            "parque", "museo", "cine", "caminata", "senderismo", "rumba", "discoteca", "teatro"
        ]
        activity = None
        for a in activities:
            if a in lower:
                activity = a.capitalize()
                break

        # Detect location
        location = None
        loc_m = re.search(r"\b(?:in|near|around|en|cerca de|por)\s+([A-Za-z0-9\s]+?)(?:\s+(?:for|this|on|para|el|este)|$)", raw)
        if loc_m:
            location = loc_m.group(1).strip()
        elif "nearby" in lower:
            location = "nearby"
        elif "cerca" in lower:
            location = "cerca"

        return IntentResult(
            intent=IntentType.OUTING_RESEARCH,
            confidence=0.88,
            slots={
                "query": raw,
                "cuisine": cuisine,
                "activity": activity,
                "location": location or "nearby",
            },
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    # -------------------------------------------------------------------------
    # Value Extractors
    # -------------------------------------------------------------------------

    def _extract_amount_cents(self, text: str) -> Optional[int]:
        """Extract monetary amount and convert to integer cents (supporting COP & standard currencies)."""
        # 1. Colombian colloquial: "X millones" or "X millón" (e.g. 2 millones -> 2,000,000)
        m_millon = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:millones|millón|millon)\b", text, re.IGNORECASE)
        if m_millon:
            try:
                val = float(m_millon.group(1).replace(",", "."))
                return int(round(val * 1_000_000 * 100))
            except ValueError:
                pass

        # 2. Colombian colloquial: "X mil" or "Xk" (e.g. 50 mil -> 50,000; 25k -> 25,000)
        m_mil = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:mil|k)\b", text, re.IGNORECASE)
        if m_mil:
            try:
                val = float(m_mil.group(1).replace(",", "."))
                return int(round(val * 1_000 * 100))
            except ValueError:
                pass

        # 3. Colombian thousands format with dots: e.g. "50.000", "$50.000", "1.250.000"
        m_colombia_dots = re.search(r"(?:[\$€£]|cop)?\s*(\d{1,3}(?:\.\d{3})+)(?:,\d{2})?\b", text, re.IGNORECASE)
        if m_colombia_dots:
            raw_dots = m_colombia_dots.group(1).replace(".", "")
            try:
                val_int = int(raw_dots)
                if val_int > 0:
                    return val_int * 100
            except ValueError:
                pass

        # 4. Standard currency formats: "$45", "$45.00", "45 dollars", "45.50"
        patterns = [
            r"[\$€£]\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)",
            r"\b((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\s*(?:dollars|bucks|usd|eur|cop|pesos|cents)\b",
            (
                r"\b(?:spent|paid|received|deposit|earned|got paid|gasté|gaste|pagué|pague|compré|compre|recibí|recibi|por)\s+[\$€£]?\s*"
                r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\b"
            ),
            r"\b(\d+\.\d{2})\b",
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                val_str = match.group(1).replace(",", "")
                try:
                    dec = Decimal(val_str)
                    if dec > 0:
                        return int(round(dec * 100))
                except (InvalidOperation, ValueError):
                    continue

        plain_m = re.fullmatch(r"^\s*(\d+(?:\.\d{1,2})?)\s*$", text.strip())
        if plain_m:
            try:
                dec = Decimal(plain_m.group(1))
                if dec > 0:
                    return int(round(dec * 100))
            except (InvalidOperation, ValueError):
                pass

        return None

    def _extract_finance_description(self, raw: str, lower: str) -> Optional[str]:
        """Extract note or description of a financial transaction."""
        cleaned = re.sub(r"[\$€£]\s*(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d{1,2})?", "", raw)
        cleaned = re.sub(r"\b(\d+(?:[.,]\d+)?)\s*(?:millones|millón|millon|mil|k)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\b(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s*(?:dollars|bucks|usd|eur|cop|pesos)?\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(spent|paid|bought|purchase|purchased|expense:|expense|cost|"
            r"received|got paid|deposit|earned|income:?|for|on|"
            r"gasté|gaste|pagué|pague|compré|compre|consumí|consumi|costó|costo|me costó|pago|compra|"
            r"ingreso de|ingreso|ingresos|me pagaron|recibí|recibi|gané|gane|sueldo|salario|"
            r"en|de|por|para|un|una|el|la|los|las|hoy|ayer|ahora|ahorita|"
            r"i want to log an|i want to log|want to log|log an|log|record an|record|add an|add)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"[:,\-]", " ", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned.lower() in ("an", "a", "the", "to", "my", "i want to", "i want", "want", "de", "en", "por", "para"):
            return None
        return cleaned if cleaned else None

    def _infer_category(self, text: str) -> str:
        """Categorize transaction from description using predefined taxonomy."""
        lower = text.lower()
        for cat, keywords in CATEGORY_KEYWORD_MAP.items():
            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", lower):
                    return cat
        return "Other"

    def _extract_datetime(self, text: str) -> Optional[datetime]:
        """Extract date and time from relative expressions."""
        lower = text.lower()
        base_date = self.reference_time.date()

        if "tomorrow" in lower or "mañana" in lower or "manana" in lower:
            target_date = base_date + timedelta(days=1)
        elif "today" in lower or "hoy" in lower:
            target_date = base_date
        elif "next monday" in lower or "próximo lunes" in lower or "el lunes" in lower:
            days_ahead = (0 - base_date.weekday() + 7) % 7 or 7
            target_date = base_date + timedelta(days=days_ahead)
        elif "friday" in lower or "viernes" in lower:
            days_ahead = (4 - base_date.weekday() + 7) % 7 or 7
            target_date = base_date + timedelta(days=days_ahead)
        else:
            target_date = base_date

        delta_m = re.search(r"\b(?:in|en)\s+(\d+)\s*(hours?|horas?|minutes?|minutos?|mins?)\b", lower)
        if delta_m:
            num = int(delta_m.group(1))
            unit = delta_m.group(2)
            if "hour" in unit or "hora" in unit:
                return self.reference_time + timedelta(hours=num)
            elif "min" in unit:
                return self.reference_time + timedelta(minutes=num)

        time_m = re.search(r"\b(?:a las\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|de la tarde|de la mañana|de la noche)?\b", lower)
        if time_m:
            hour = int(time_m.group(1))
            minute = int(time_m.group(2)) if time_m.group(2) else 0
            meridiem = time_m.group(3)

            if meridiem in ("pm", "de la tarde", "de la noche") and hour < 12:
                hour += 12
            elif meridiem in ("am", "de la mañana") and hour == 12:
                hour = 0

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return datetime.combine(target_date, time(hour=hour, minute=minute))

        if "tomorrow" in lower or "mañana" in lower or "manana" in lower:
            return datetime.combine(target_date, time(hour=9, minute=0))

        return None
