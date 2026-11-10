"""Natural language intent parser and slot extractor."""

import logging
import re
import unicodedata
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from app.integrations.protocols import (
    IntentParserProtocol,
    IntentResult,
    IntentType,
    TransactionType,
)

logger = logging.getLogger(__name__)


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

COLOMBIAN_ACCOUNTS = {
    "efectivo": "Efectivo",
    "nequi": "Nequi",
    "nu": "Nu",
    "daviplata": "Daviplata",
    "bancolombia": "Bancolombia",
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

        # 6b. Colombian Banking, Debts & Subscriptions (before standard finance entry)
        acc_transfer = self._parse_account_transfer(cleaned, lower_text)
        if acc_transfer:
            return acc_transfer

        debt_settle = self._parse_debt_settle(cleaned, lower_text)
        if debt_settle:
            return debt_settle

        debt_record = self._parse_debt_record(cleaned, lower_text)
        if debt_record:
            return debt_record

        debt_query = self._parse_debt_query(cleaned, lower_text)
        if debt_query:
            return debt_query

        sub_record = self._parse_subscription_record(cleaned, lower_text)
        if sub_record:
            return sub_record

        upcoming_query = self._parse_upcoming_payments_query(cleaned, lower_text)
        if upcoming_query:
            return upcoming_query

        acc_query = self._parse_account_query(cleaned, lower_text)
        if acc_query:
            return acc_query

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
            "mis cuentas", "transferir", "mis deudas", "suscripciones", "vencimientos",
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

        if active_intent == IntentType.ACCOUNT_TRANSFER:
            amt = self._extract_amount_cents(cleaned)
            if amt and "amount" in missing_slots:
                pending_slots["amount_cents"] = amt
                pending_slots["amount"] = amt / 100.0
                missing_slots.remove("amount")

            for acc_k, acc_name in COLOMBIAN_ACCOUNTS.items():
                if acc_k in lower:
                    if "from_account" in missing_slots and "to_account" not in missing_slots:
                        pending_slots["from_account"] = acc_name
                        pending_slots["source_account"] = acc_name
                        missing_slots.remove("from_account")
                    elif "to_account" in missing_slots:
                        pending_slots["to_account"] = acc_name
                        pending_slots["destination_account"] = acc_name
                        missing_slots.remove("to_account")
                    elif "from_account" in missing_slots:
                        pending_slots["from_account"] = acc_name
                        pending_slots["source_account"] = acc_name
                        missing_slots.remove("from_account")

            is_complete = len(missing_slots) == 0
            return IntentResult(
                intent=active_intent,
                confidence=0.95,
                slots=pending_slots,
                is_complete=is_complete,
                missing_slots=missing_slots,
                raw_text=cleaned,
            )

        if active_intent == IntentType.DEBT_RECORD:
            amt = self._extract_amount_cents(cleaned)
            if amt and "amount" in missing_slots:
                pending_slots["amount_cents"] = amt
                pending_slots["amount"] = amt / 100.0
                missing_slots.remove("amount")
            if "counterparty" in missing_slots and not amt:
                name_cand = cleaned.strip().split()[0].capitalize()
                pending_slots["counterparty"] = name_cand
                missing_slots.remove("counterparty")

            is_complete = len(missing_slots) == 0
            return IntentResult(
                intent=active_intent,
                confidence=0.95,
                slots=pending_slots,
                is_complete=is_complete,
                missing_slots=missing_slots,
                raw_text=cleaned,
            )

        if active_intent == IntentType.DEBT_SETTLE:
            amt = self._extract_amount_cents(cleaned)
            if amt and "amount" in missing_slots:
                pending_slots["amount_cents"] = amt
                pending_slots["amount"] = amt / 100.0
                missing_slots.remove("amount")
            if "counterparty" in missing_slots and not amt:
                name_cand = cleaned.strip().split()[0].capitalize()
                pending_slots["counterparty"] = name_cand
                missing_slots.remove("counterparty")

            is_complete = len(missing_slots) == 0
            return IntentResult(
                intent=active_intent,
                confidence=0.95,
                slots=pending_slots,
                is_complete=is_complete,
                missing_slots=missing_slots,
                raw_text=cleaned,
            )

        if active_intent == IntentType.SUBSCRIPTION_RECORD:
            amt = self._extract_amount_cents(cleaned)
            if amt and "amount" in missing_slots:
                pending_slots["amount_cents"] = amt
                pending_slots["amount"] = amt / 100.0
                missing_slots.remove("amount")
            if "name" in missing_slots and not amt:
                pending_slots["name"] = cleaned.strip().title()
                pending_slots["service_name"] = pending_slots["name"]
                missing_slots.remove("name")

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

    # -------------------------------------------------------------------------
    # Colombian Banking, Debt & Subscription Parser Methods (R1-R4)
    # -------------------------------------------------------------------------

    def _parse_account_transfer(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract inter-account transfers (e.g. pasé 100 mil de Bancolombia a Nequi)."""
        transfer_verb_match = re.search(
            r"\b(pas[eé]|pasar|pasa|transfer[ií]|transferir|transfiere|mand[eé]|mandar|manda|retir[eé]|retirar|retira|saqu[eé]|sacar|saca|mover|mov[ií]|mueve|transferencia|traslad[eé]|traslado|trasladar)\b",
            lower,
        )
        if not transfer_verb_match:
            return None

        has_acc = any(bool(re.search(rf"\b{acc}\b", lower)) for acc in COLOMBIAN_ACCOUNTS)
        has_direction = bool(re.search(r"\b(?:de|desde)\b.+\b(?:a|hacia|en)\b", lower))
        is_withdrawal = any(w in transfer_verb_match.group(1) for w in ("retir", "saqu", "saca"))

        if not (has_acc or has_direction or is_withdrawal):
            return None

        # Exclude debt settlements: "le pagué ... a ..."
        if re.search(r"\ble\s+pagu[eé]\b|\bme\s+pag[oó]\b|\bsald[eé]\b", lower):
            return None

        amount_cents = self._extract_amount_cents(raw)

        from_acc = None
        to_acc = None

        from_match = re.search(r"\b(?:de|desde|from)\s+([a-záéíóú0-9_]+)", lower)
        if from_match:
            cand = from_match.group(1).strip()
            if cand in COLOMBIAN_ACCOUNTS:
                from_acc = COLOMBIAN_ACCOUNTS[cand]
            elif cand not in ("mi", "mis", "un", "una", "el", "la"):
                from_acc = cand.capitalize()

        to_match = re.search(r"\b(?:a|hacia|para|to)\s+([a-záéíóú0-9_]+)", lower)
        if to_match:
            cand = to_match.group(1).strip()
            if cand in COLOMBIAN_ACCOUNTS:
                to_acc = COLOMBIAN_ACCOUNTS[cand]
            elif cand not in ("mi", "mis", "un", "una", "el", "la", "pagar"):
                to_acc = cand.capitalize()

        matched_verb = transfer_verb_match.group(1)
        is_saque = any(w in matched_verb for w in ("saqu", "saca"))

        if is_withdrawal and not to_acc:
            if is_saque and from_acc and from_acc != "Efectivo":
                to_acc = "Efectivo"
            else:
                return None

        slots: Dict[str, Any] = {}
        missing_slots: List[str] = []

        if amount_cents is not None:
            slots["amount_cents"] = amount_cents
            slots["amount"] = amount_cents / 100.0
        else:
            missing_slots.append("amount")

        if from_acc:
            slots["from_account"] = from_acc
            slots["source_account"] = from_acc
        else:
            missing_slots.append("from_account")

        if to_acc:
            slots["to_account"] = to_acc
            slots["destination_account"] = to_acc
        else:
            missing_slots.append("to_account")

        is_complete = len(missing_slots) == 0
        confidence = 0.95 if is_complete else 0.80

        return IntentResult(
            intent=IntentType.ACCOUNT_TRANSFER,
            confidence=confidence,
            slots=slots,
            is_complete=is_complete,
            missing_slots=missing_slots,
            raw_text=raw,
        )

    def _parse_debt_settle(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract full or partial debt settlements (e.g. le pagué 20 mil a Juan, pagar 2 cuotas)."""
        word_to_num = {
            "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4,
            "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
            "doce": 12, "veinticuatro": 24,
        }

        # Check for installment payment (e.g. "pagar 2 cuotas de la deuda de Juan con Bancolombia", "abono 1 cuota a Daviplata")
        m_cuotas_pay = re.search(
            r"\b(?:pagar|pagu[eé]|abonar|abono|abonando|pagando)\s+(?:(\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+)?cuotas?\b",
            lower,
        )
        if m_cuotas_pay:
            num_str = m_cuotas_pay.group(1)
            if num_str:
                cuotas_to_pay = int(num_str) if num_str.isdigit() else word_to_num.get(num_str.lower(), 1)
            else:
                cuotas_to_pay = 1

            # Extract account
            account = None
            for acc_k, acc_name in COLOMBIAN_ACCOUNTS.items():
                if re.search(rf"\b(?:desde|en|por|con|a)\s+{acc_k}\b", lower) or re.search(rf"\b{acc_k}\b", lower):
                    account = acc_name
                    break

            # Extract counterparty (excluding accounts and helper words)
            counterparty = None
            m_cp = re.search(
                r"\b(?:de\s+la\s+deuda\s+(?:de|con)\s+|deuda\s+(?:de|con)\s+|con\s+|de\s+|a\s+)([A-ZÁÉÍÓÚa-záéíóú]+)",
                raw,
                re.IGNORECASE,
            )
            if m_cp:
                cand = m_cp.group(1).strip()
                if cand.lower() not in (
                    "un", "una", "el", "la", "los", "las", "mi", "mis", "deuda", "plata", "cuota", "cuotas",
                    "nequi", "nu", "daviplata", "bancolombia", "efectivo"
                ):
                    counterparty = cand.capitalize()

            slots: Dict[str, Any] = {
                "is_installment_payment": True,
                "installments_to_pay": cuotas_to_pay,
            }
            if counterparty:
                slots["counterparty"] = counterparty
            if account:
                slots["account"] = account
                slots["account_name"] = account

            amount_cents = self._extract_amount_cents(raw)
            if amount_cents is not None:
                slots["amount_cents"] = amount_cents
                slots["amount"] = amount_cents / 100.0

            return IntentResult(
                intent=IntentType.DEBT_SETTLE,
                confidence=0.95,
                slots=slots,
                is_complete=True,
                missing_slots=[],
                raw_text=raw,
            )

        settle_pats = [
            r"\ble\s+pagu[eé]\s+(?:[\$0-9k\.\,\s]+(?:mil|k|pesos|millones)?\s+)?a\s+([A-ZÁÉÍÓÚa-záéíóú]+)",
            r"\b([A-ZÁÉÍÓÚa-záéíóú]+)\s+(?:ya\s+)?me\s+pag[oó]",
            r"\b(?:sald[eé]|saldar|liquidar|cancelar)\s+(?:la\s+)?deuda\s+(?:con|de)\s+([A-ZÁÉÍÓÚa-záéíóú]+)",
            r"\bpagar\s+deuda\s+(?:a|de|con)\s+([A-ZÁÉÍÓÚa-záéíóú]+)",
        ]

        counterparty = None
        for pat in settle_pats:
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                if cand.lower() not in ("un", "una", "el", "la", "los", "las", "mi", "mis", "deuda", "plata"):
                    counterparty = cand.capitalize()
                    break

        if not counterparty:
            m2 = re.search(r"\ble\s+pagu[eé]\s+a\s+([A-ZÁÉÍÓÚa-záéíóú]+)", raw, re.IGNORECASE)
            if m2:
                cand = m2.group(1).strip()
                if cand.lower() not in ("un", "una", "el", "la"):
                    counterparty = cand.capitalize()

        if not counterparty:
            return None

        amount_cents = self._extract_amount_cents(raw)

        account = None
        for acc_k, acc_name in COLOMBIAN_ACCOUNTS.items():
            if re.search(rf"\b(?:desde|en|por|con)\s+{acc_k}\b", lower):
                account = acc_name
                break

        slots = {
            "counterparty": counterparty,
        }
        if amount_cents is not None:
            slots["amount_cents"] = amount_cents
            slots["amount"] = amount_cents / 100.0
        if account:
            slots["account"] = account
            slots["account_name"] = account

        return IntentResult(
            intent=IntentType.DEBT_SETTLE,
            confidence=0.95,
            slots=slots,
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_debt_record(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract debts and loans (e.g. le presté 50k a Juan, Juan me debe 50k, le debo 30 mil)."""
        is_receivable = bool(
            re.search(
                r"\b(le\s+prest[eé]|prest[eé]|prestar|prestamos|di\s+prestado|le\s+di\s+prestado|me\s+debe|me\s+deben)\b",
                lower,
            )
        )
        is_debt = bool(
            re.search(
                r"\b(me\s+prest[oó]|me\s+prestaron|le\s+debo|debo\b|deuda\b.*?con|tengo\s+una\s+deuda|pr[eé]stamo\s+de)\b",
                lower,
            )
        )

        if not (is_receivable or is_debt):
            return None

        # Exclude explicit questions like "a quién le debo?", "¿quién me debe?", "mis deudas" -> DEBT_QUERY
        if re.search(r"\b(a\s+qui[eé]n|qui[eé]n|cu[aá]nto|mis\s+deudas|deudas\s+pendientes)\b", lower) and not re.search(r"\b\d+\b", lower):
            return None

        debt_type = "receivable" if is_receivable else "debt"
        counterparty = None

        if is_receivable:
            m_front = re.search(r"([A-ZÁÉÍÓÚa-záéíóú]+)\s+me\s+debe\b", raw, re.IGNORECASE)
            if m_front:
                cand = m_front.group(1).strip()
                if cand.lower() not in ("él", "el", "ella", "alguien", "hoy", "ayer", "ya", "quién", "quien"):
                    counterparty = cand.capitalize()
            if not counterparty:
                m_back = re.search(r"\bme\s+debe\s+([A-ZÁÉÍÓÚa-záéíóú]+)", raw, re.IGNORECASE)
                if m_back:
                    cand = m_back.group(1).strip()
                    if cand.lower() not in (
                        "un", "una", "el", "la", "los", "las", "mi", "mis",
                        "nequi", "nu", "daviplata", "bancolombia", "efectivo", "plata", "dinero"
                    ):
                        counterparty = cand.capitalize()
            if not counterparty:
                for m in re.finditer(r"\b(?:a|para)\s+([A-ZÁÉÍÓÚa-záéíóú]+)", raw):
                    cand = m.group(1).strip()
                    if cand.lower() not in (
                        "un", "una", "el", "la", "los", "las", "mi", "mis",
                        "nequi", "nu", "daviplata", "bancolombia", "efectivo",
                        "cuota", "cuotas"
                    ):
                        counterparty = cand.capitalize()
                        break
        else:
            m1 = re.search(r"([A-ZÁÉÍÓÚa-záéíóú]+)\s+me\s+prest[oó]", raw, re.IGNORECASE)
            if m1:
                cand = m1.group(1).strip()
                if cand.lower() not in ("ayer", "hoy", "ya", "él", "el", "ella"):
                    counterparty = cand.capitalize()
            if not counterparty:
                for m_con in re.finditer(r"\b(?:con|a)\s+([A-ZÁÉÍÓÚa-záéíóú]+)", raw, re.IGNORECASE):
                    cand = m_con.group(1).strip()
                    if cand.lower() not in (
                        "un", "una", "el", "la", "los", "las", "mi", "mis",
                        "nequi", "nu", "daviplata", "bancolombia", "efectivo", "plata", "dinero",
                        "cuota", "cuotas"
                    ):
                        counterparty = cand.capitalize()
                        break
            if not counterparty:
                m2 = re.search(
                    r"\b(?:le\s+debo|debo)\s+(?:[\$0-9k\.\,\s]+(?:mil|k|pesos|millones)?\s+)?a\s+([A-ZÁÉÍÓÚa-záéíóú]+)",
                    raw,
                    re.IGNORECASE,
                )
                if m2:
                    cand = m2.group(1).strip()
                    if cand.lower() not in ("un", "una", "el", "la", "cuota", "cuotas"):
                        counterparty = cand.capitalize()
            if not counterparty:
                m3 = re.search(
                    r"\bpr[eé]stamo\s+de\s+(?:[\$0-9k\.\,\s]+(?:mil|k|pesos|millones)?\s+)?(?:de\s+)?([A-ZÁÉÍÓÚa-záéíóú]+)",
                    raw,
                    re.IGNORECASE,
                )
                if m3:
                    cand = m3.group(1).strip()
                    if cand.lower() not in ("un", "una", "el", "la", "bancolombia", "nequi", "nu", "cuota", "cuotas"):
                        counterparty = cand.capitalize()

        amount_cents = self._extract_amount_cents(raw)

        account = None
        for acc_k, acc_name in COLOMBIAN_ACCOUNTS.items():
            if re.search(rf"\b(?:desde|de|en|por)\s+{acc_k}\b", lower):
                account = acc_name
                break

        reason = "préstamo"
        reason_match = re.search(
            r"\b(?:para|por)\s+(?:el|la|los|las)?\s*([a-záéíóú0-9\s]+?)(?:,|\.|\s+me\s+paga|\s+paga|\s+desde|\s+en|\s+hasta|\s+para\s+el|$)",
            lower,
        )
        if reason_match:
            cand_reason = reason_match.group(1).strip()
            clean_reason = re.sub(r"^(?:el|la|los|las)\s+", "", cand_reason).strip()
            if clean_reason and clean_reason not in (
                counterparty.lower() if counterparty else "",
                "nequi", "nu", "bancolombia", "daviplata", "efectivo", "el"
            ):
                # Only assign as reason if it does not resolve as a date expression or cuotas
                if not self._extract_datetime(clean_reason) and not re.search(r"\b\d+\s+cuotas?\b", clean_reason):
                    reason = clean_reason

        if re.search(r"\b\d+\s+cuotas?\b", reason):
            reason = "préstamo"

        due_date = None
        # Explicit payment / deadline markers: "me paga (el)?", "paga (el)?", "vence (el)?", "hasta el"
        due_match = re.search(
            r"\b(?:me\s+paga|paga|vence|hasta\s+el)\s+(?:el\s+)?([a-záéíóú0-9\s]+?)(?:,|\.|$)",
            lower,
        )
        if due_match:
            due_str = due_match.group(1).strip()
            resolved_dt = self._extract_datetime(due_str)
            if resolved_dt:
                due_date = resolved_dt.isoformat()
            else:
                due_date = due_str
        else:
            # Fallback: "para el <date>" or "para <date>" only if it resolves to a valid date
            para_date_match = re.search(
                r"\b(?:para\s+el|para)\s+([a-záéíóú0-9\s]+?)(?:,|\.|$)",
                lower,
            )
            if para_date_match:
                cand_due = para_date_match.group(1).strip()
                resolved_dt = self._extract_datetime(cand_due)
                if resolved_dt:
                    due_date = resolved_dt.isoformat()

        slots: Dict[str, Any] = {
            "type": debt_type,
            "debt_type": "payable" if debt_type == "debt" else debt_type,
            "raw_debt_type": debt_type,
            "reason": reason,
            "notes": reason,
        }

        # Check for installment terms (e.g. "en 6 cuotas", "a 12 cuotas", "6 cuotas mensuales")
        m_cuotas = re.search(
            r"\b(?:en|a)\s+(\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|doce|veinticuatro)\s+cuotas?\b|\b(\d+)\s+cuotas?\b",
            lower,
        )
        if m_cuotas:
            word_to_num = {
                "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4,
                "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
                "doce": 12, "veinticuatro": 24,
            }
            c_val = m_cuotas.group(1) or m_cuotas.group(2)
            c_num = int(c_val) if c_val.isdigit() else word_to_num.get(c_val.lower(), 1)
            slots["is_installment"] = True
            slots["total_installments"] = c_num
            slots["remaining_installments"] = c_num
            if re.search(r"\bquincenal(?:es)?\b", lower):
                freq = "biweekly"
            elif re.search(r"\bsemanal(?:es)?\b", lower):
                freq = "weekly"
            elif re.search(r"\banual(?:es)?\b", lower):
                freq = "yearly"
            else:
                freq = "monthly"
            slots["payment_frequency"] = freq
            if amount_cents:
                slots["installment_amount_cents"] = amount_cents // c_num
                slots["installment_amount"] = round((amount_cents // c_num) / 100.0, 2)

        missing_slots: List[str] = []

        if counterparty:
            slots["counterparty"] = counterparty
        else:
            missing_slots.append("counterparty")

        if amount_cents is not None:
            slots["amount_cents"] = amount_cents
            slots["amount"] = amount_cents / 100.0
        else:
            missing_slots.append("amount")

        if account:
            slots["account"] = account
            slots["account_name"] = account

        if due_date:
            slots["due_date"] = due_date

        is_complete = len(missing_slots) == 0
        confidence = 0.95 if is_complete else 0.75

        return IntentResult(
            intent=IntentType.DEBT_RECORD,
            confidence=confidence,
            slots=slots,
            is_complete=is_complete,
            missing_slots=missing_slots,
            raw_text=raw,
        )

    def _parse_debt_query(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract queries for debts and loans."""
        if not re.search(r"\b(deuda|deudas|debo|debe|deben|prestado|cobros|cobro)\b", lower):
            return None

        is_specific_debt = bool(
            re.search(r"\b(a\s+qui[eé]n\s+le\s+debo|cu[aá]nto\s+debo|lo\s+que\s+debo|le\s+debo)\b", lower)
        )
        is_specific_rec = bool(
            re.search(r"\b(qui[eé]n\s+me\s+debe|cu[aá]nto\s+me\s+deben|cobros\s+pendientes|quien\s+me\s+debe|lo\s+que\s+me\s+deben)\b", lower)
        )

        query_type = "all"
        if is_specific_debt and not is_specific_rec:
            query_type = "payable"
        elif is_specific_rec and not is_specific_debt:
            query_type = "receivable"

        counterparty = None
        m_cp = re.search(r"\b(?:debe|deuda\s+de)\s+([A-ZÁÉÍÓÚa-záéíóú]+)", raw)
        if m_cp:
            cand = m_cp.group(1).strip()
            if cand.lower() not in ("plata", "dinero", "un", "una", "el", "la"):
                counterparty = cand.capitalize()

        return IntentResult(
            intent=IntentType.DEBT_QUERY,
            confidence=0.95,
            slots={
                "query_type": query_type,
                "debt_type": query_type,
                "counterparty": counterparty,
            },
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_subscription_record(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract recurring subscription creations."""
        if not re.search(r"\b(suscripci[oó]n|suscripciones|subscripci[oó]n|subscription)\b", lower):
            return None

        name = None
        m_name = re.search(
            r"\b(?:suscripci[oó]n|subscription)\s+(?:de|a)?\s*([A-Za-z0-9\+\.\s]+?)(?:\s+\d|\s+por\s+\d|\s+mensual|\s+los\s+\d|\s+desde|\s+en\s+nu|\s+en\s+bancolombia|$)",
            raw,
            re.IGNORECASE,
        )
        if m_name:
            cand = m_name.group(1).strip()
            if cand.lower() not in ("nueva", "un", "una", "el", "la", "mi"):
                name = cand.title()

        amount_cents = self._extract_amount_cents(raw)

        billing_day = None
        m_day = re.search(r"\b(?:los|el|d[ií]a)\s+([0-9]{1,2})\b", lower)
        if m_day:
            try:
                day_num = int(m_day.group(1))
                if 1 <= day_num <= 31:
                    billing_day = day_num
            except ValueError:
                pass

        if not billing_day:
            billing_day = self.reference_time.day

        account = None
        for acc_k, acc_name in COLOMBIAN_ACCOUNTS.items():
            if re.search(rf"\b(?:desde|en|por|con)\s+{acc_k}\b", lower):
                account = acc_name
                break

        slots: Dict[str, Any] = {
            "billing_cycle": "monthly",
            "billing_day": billing_day,
            "category": "Entertainment",
        }
        missing_slots: List[str] = []

        if name:
            slots["name"] = name
            slots["service_name"] = name
        else:
            missing_slots.append("name")

        if amount_cents is not None:
            slots["amount_cents"] = amount_cents
            slots["amount"] = amount_cents / 100.0
        else:
            missing_slots.append("amount")

        if account:
            slots["account"] = account
            slots["account_name"] = account

        is_complete = len(missing_slots) == 0
        return IntentResult(
            intent=IntentType.SUBSCRIPTION_RECORD,
            confidence=0.95 if is_complete else 0.75,
            slots=slots,
            is_complete=is_complete,
            missing_slots=missing_slots,
            raw_text=raw,
        )

    def _parse_upcoming_payments_query(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract queries for impending payments and subscriptions."""
        pats = [
            r"\b(pagos?\s+pendientes?|vencimientos?|pr[oó]ximos?\s+pagos?|calendario\s+de\s+pagos?)\b",
            r"\bqu[eé]\s+(?:pagos\s+tengo\s+pendientes|tengo\s+que\s+pagar|vence\s+pronto|vencimientos)\b",
            r"\bcu[aá]ndo\s+vencen?\b",
        ]
        if not any(re.search(pat, lower) for pat in pats):
            return None

        days_ahead = 7 if re.search(r"\b(esta\s+semana|semana)\b", lower) else 30

        return IntentResult(
            intent=IntentType.UPCOMING_PAYMENTS_QUERY,
            confidence=0.95,
            slots={"days_ahead": days_ahead},
            is_complete=True,
            missing_slots=[],
            raw_text=raw,
        )

    def _parse_account_query(self, raw: str, lower: str) -> Optional[IntentResult]:
        """Detect and extract account balance inquiries or explicit balance updates."""
        has_known_bank = any(bool(re.search(rf"\b{k}\b", lower)) for k in COLOMBIAN_ACCOUNTS)
        has_explicit_accounts = bool(re.search(r"\b(mis\s+cuentas|cuentas\s+bancarias|cuentas|patrimonio)\b", lower))

        # Do not hijack general balance queries (e.g. 'cuál es mi saldo actual') unless specific bank or explicit accounts mentioned
        if not (has_known_bank or has_explicit_accounts):
            return None

        if re.search(r"\b(gastos?|ingresos?|resumen|categor[ií]as?)\b", lower) and not has_known_bank:
            return None

        amount_cents = self._extract_amount_cents(raw)

        # Do NOT hijack deposit, expense, debt or transfer actions that should be handled as financial transactions or debts
        deposit_or_expense_verbs = bool(re.search(
            r"\b(a[ñn]adir|agregar|meter|consignar|consign[eé]|cargar|cargu[eé]|abono|abonar|dep[oó]sito|"
            r"gast[eé]|pagu[eé]|compr[eé]|prest[eé]|debo|deuda|"
            r"retir[eé]|retirar|retira|retiro|quit[eé]|quitar|quita|quiten|sacar|saqu[eé]|saca)\b",
            lower
        ))
        if deposit_or_expense_verbs and amount_cents is not None:
            return None

        matched = []
        for acc_k, acc_name in COLOMBIAN_ACCOUNTS.items():
            if re.search(rf"\b{acc_k}\b", lower):
                matched.append(acc_name)

        is_query_phrase = bool(re.search(r"\b(cu[aá]nto|cu[aá]nta|qu[eé]\s+saldo|c[oó]mo\s+est[aá]|ver|consultar|mostrar)\b", lower))

        # Check if user is declaring an initial or current balance:
        # e.g. "tengo 200 mil en nu", "mi saldo en nequi es 500.000", "en efectivo tengo 50k", "poner saldo de nu en 300k"
        is_setting = bool(re.search(r"\b(tengo|saldo\s+en|mi\s+saldo\s+en|tengo\s+en|en\s+[a-z]+\s+tengo|poner\s+saldo|actualizar\s+saldo|saldo\s+es|saldo\s+de)\b", lower))
        if is_setting and amount_cents is not None and not is_query_phrase and matched:
            target_acc = matched[0]
            return IntentResult(
                intent=IntentType.ACCOUNT_QUERY,
                confidence=0.95,
                slots={
                    "action": "set_balance",
                    "account_name": target_acc,
                    "account_names": [target_acc],
                    "accounts": [target_acc],
                    "amount_cents": amount_cents,
                    "amount": amount_cents / 100.0,
                    "all_accounts": False,
                },
                is_complete=True,
                missing_slots=[],
                raw_text=raw,
            )

        all_accounts = len(matched) == 0 or "mis cuentas" in lower or "total" in lower or "patrimonio" in lower or "todas" in lower

        return IntentResult(
            intent=IntentType.ACCOUNT_QUERY,
            confidence=0.95,
            slots={
                "action": "query",
                "account_names": matched,
                "accounts": matched,
                "all_accounts": all_accounts,
            },
            is_complete=True,
            missing_slots=[],
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
            "sueldo", "salario", "nómina", "nomina", "honorarios", "quincena", "prima",
            "añadir", "anadir", "agregar", "meter", "consignar", "consigné", "consigne",
            "cargar", "cargué", "cargue", "abono", "abonar", "depósito", "deposito", "entró", "entro"
        ]
        withdrawal_words = [
            "retirar", "retiré", "retire", "retira", "retiro",
            "quitar", "quité", "quite", "quita", "quiten",
            "sacar", "saqué", "saque", "saca",
        ]
        deposit_words = [
            "añadir", "anadir", "agregar", "meter", "consignar", "consigné", "consigne",
            "cargar", "cargué", "cargue", "abono", "abonar", "depósito", "deposito", "entró", "entro"
        ]
        expense_words = [
            "spent", "pay", "paid", "bought", "purchase", "purchased",
            "expense", "cost", "fee", "charged",
            "gasté", "gaste", "pagué", "pague", "compré", "compre", "consumí", "consumi",
            "costó", "costo", "me costó", "pago", "compra",
        ] + withdrawal_words

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

        # Extract linked account if mentioned
        account_name = None
        for acc_k, acc_v in COLOMBIAN_ACCOUNTS.items():
            if re.search(rf"\b{acc_k}\b", lower):
                account_name = acc_v
                break

        # Extract description and category
        desc = self._extract_finance_description(raw, lower)
        cleaned_desc_lower = desc.lower().strip() if desc else ""
        if not desc or cleaned_desc_lower in (
            "mi cuenta de nequi", "cuenta de nequi", "nequi", "nu", "bancolombia", "daviplata", "efectivo",
            "a mi cuenta", "cuenta", "mi cuenta", "a bancolombia", "a nequi", "a nu", "a daviplata", "a efectivo",
            "de bancolombia", "de nequi", "de nu", "de daviplata", "de efectivo"
        ) or (cleaned_desc_lower.startswith(("a ", "de ")) and account_name and account_name.lower() in cleaned_desc_lower):
            if account_name:
                desc = (
                    f"Depósito en {account_name}"
                    if t_type == TransactionType.INCOME
                    else f"Retiro de {account_name}"
                )
            else:
                desc = None

        category = self._infer_category(desc or raw) if desc else "Other"
        if t_type == TransactionType.INCOME and category == "Other":
            category = "Income"
        elif t_type == TransactionType.EXPENSE and any(w in lower for w in withdrawal_words) and category == "Other":
            category = "Cash" if account_name == "Efectivo" else "Other"

        is_deposit = any(re.search(rf"\b{w}\b", lower) for w in deposit_words)
        is_withdraw = any(re.search(rf"\b{w}\b", lower) for w in withdrawal_words)
        action = "deposit" if is_deposit or t_type == TransactionType.INCOME else (
            "withdraw" if is_withdraw else "expense"
        )

        slots: Dict[str, Any] = {
            "transaction_type": t_type.value,
            "action": action,
            "category": category,
        }
        if account_name:
            slots["account_name"] = account_name
            slots["account"] = account_name

        missing_slots: List[str] = []

        if amount_cents is not None:
            slots["amount_cents"] = amount_cents
            slots["amount"] = amount_cents / 100.0
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
            "qué hacer en", "que hacer en", "actividades en", "planes en",
            "restaurantes en", "restaurantes", "restaurante", "lugares para cenar", "lugares para comer",
            "lugares para almorzar", "sitios para cenar", "sitios para almorzar", "dónde cenar", "donde cenar",
            "dónde comer", "donde comer", "dónde almorzar", "donde almorzar", "cenar en", "comer en",
            "almorzar en", "buscar restaurantes", "sitios en", "lugares en", "dónde salir", "donde salir",
            "cenar", "almorzar"
        ]
        if not any(t in lower for t in triggers):
            return None

        # Exclude task creation or finance commands
        if (
            lower.startswith("remind me to")
            or lower.startswith("add task")
            or lower.startswith("recuérdame")
            or lower.startswith("recuerdame")
            or lower.startswith("crear tarea")
        ):
            return None

        # Detect cuisine
        cuisines = [
            "italian", "mexican", "japanese", "chinese", "thai", "sushi",
            "pizza", "indian", "french", "burger", "vegan", "coffee",
            "italiana", "mexicana", "japonesa", "china", "hamburguesa", "asado",
            "café", "postres", "criolla", "colombiana", "parrilla"
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

        # Detect location (Unicode-aware regex)
        location = None
        loc_m = re.search(
            r"\b(?:in|near|around|en|cerca de|por)\s+([A-Za-z0-9\sáéíóúñÁÉÍÓÚÑüÜ\.\-]+?)(?:\s+(?:for|this|on|para|el|este)|$)",
            raw,
            re.IGNORECASE,
        )
        if loc_m:
            candidate = loc_m.group(1).strip()
            if candidate.lower() not in ("el", "la", "los", "las", "un", "una", "este", "esta", "mi"):
                location = candidate

        colombian_sector_canonical = {
            "chapinero": "Chapinero",
            "usaquen": "Usaquén",
            "usaquén": "Usaquén",
            "parque 93": "Parque 93",
            "zona g": "Zona G",
            "zona t": "Zona T",
            "la candelaria": "La Candelaria",
            "candelaria": "La Candelaria",
            "el poblado": "El Poblado",
            "poblado": "El Poblado",
            "laureles": "Laureles",
            "bogota": "Bogotá",
            "bogotá": "Bogotá",
            "medellin": "Medellín",
            "medellín": "Medellín",
            "cartagena": "Cartagena",
            "cali": "Cali",
            "la macarena": "La Macarena",
            "macarena": "La Macarena",
            "chico": "Chicó",
            "chicó": "Chicó",
            "santa barbara": "Santa Bárbara",
            "santa bárbara": "Santa Bárbara",
            "cedritos": "Cedritos",
            "salitre": "Salitre",
            "teusaquillo": "Teusaquillo",
            "rosales": "Rosales",
        }

        # Check if candidate location or raw text matches canonical Colombian sectors
        norm_raw = "".join(c for c in unicodedata.normalize("NFD", raw) if unicodedata.category(c) != "Mn").lower()
        if location:
            norm_loc = "".join(
                c for c in unicodedata.normalize("NFD", location) if unicodedata.category(c) != "Mn"
            ).lower()
            if norm_loc in colombian_sector_canonical:
                location = colombian_sector_canonical[norm_loc]

        if not location or location in ("nearby", "cerca"):
            for sec_key, sec_val in colombian_sector_canonical.items():
                norm_sec = "".join(
                    c for c in unicodedata.normalize("NFD", sec_key) if unicodedata.category(c) != "Mn"
                ).lower()
                if re.search(rf"\b{re.escape(norm_sec)}\b", norm_raw):
                    location = sec_val
                    break

        if not location:
            if "nearby" in lower:
                location = "nearby"
            elif "cerca" in lower:
                location = "cerca"

        return IntentResult(
            intent=IntentType.OUTING_RESEARCH,
            confidence=0.92,
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

        # 2. Colombian colloquial: "X mil", "Xk", or "X lucas" (e.g. 50 mil -> 50,000; 25k -> 25,000; 100 lucas -> 100,000)
        m_mil = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:mil|k|lucas)\b", text, re.IGNORECASE)
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

        # 5. Raw 4+ digit integers (e.g. "25000" in "transferir de Daviplata a Nequi 25000")
        m_raw_num = re.search(r"\b(\d{4,9})\b", text)
        if m_raw_num:
            try:
                val_int = int(m_raw_num.group(1))
                if val_int >= 1000 and val_int not in range(2020, 2035):
                    return val_int * 100
            except ValueError:
                pass

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
            r"añadir a mi cuenta de|añadir a mi cuenta|añadir a|añadir|anadir|agregar a|agregar|meter a|meter|consignar en|consignar a|consignar|consigné en|consigné|consigne|cargar a|cargar|cargué|cargue|abono a|abono|abonar|"
            r"retirar de mi cuenta de|retirar de mi cuenta|retirar de|retirar|retiré de|retiré|retire|retiro de|retiro|"
            r"quitar de mi cuenta de|quitar de mi cuenta|quitar de|quitar|quité de|quité|quite|quita de|quita|"
            r"sacar de mi cuenta de|sacar de mi cuenta|sacar de|sacar|saqué de|saqué|saque|saca de|saca|"
            r"en|de|por|para|un|una|el|la|los|las|hoy|ayer|ahora|ahorita|mi\s+cuenta\s+de|cuenta\s+de|mi\s+cuenta|cuenta|"
            r"i want to log an|i want to log|want to log|log an|log|record an|record|add an|add)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"[:,\-]", " ", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned.lower() in ("an", "a", "the", "to", "my", "i want to", "i want", "want", "de", "en", "por", "para", "nequi", "nu", "daviplata", "bancolombia", "efectivo"):
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
        """Extract date and time from relative expressions and weekdays."""
        lower = text.lower()
        base_date = self.reference_time.date()

        # 1. Check for explicit ISO format string
        iso_m = re.search(r"\b(\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2})?)?)\b", text)
        if iso_m:
            try:
                cleaned_iso = iso_m.group(1).replace(" ", "T")
                return datetime.fromisoformat(cleaned_iso)
            except ValueError:
                pass

        weekdays_map = {
            "lunes": 0, "monday": 0,
            "martes": 1, "tuesday": 1,
            "miércoles": 2, "miercoles": 2, "wednesday": 2,
            "jueves": 3, "thursday": 3,
            "viernes": 4, "friday": 4,
            "sábado": 5, "sabado": 5, "saturday": 5,
            "domingo": 6, "sunday": 6,
        }

        target_date = None
        has_relative_date = False

        if "tomorrow" in lower or "mañana" in lower or "manana" in lower:
            target_date = base_date + timedelta(days=1)
            has_relative_date = True
        elif "today" in lower or "hoy" in lower:
            target_date = base_date
            has_relative_date = True
        else:
            for day_name, day_num in weekdays_map.items():
                if re.search(rf"\b{day_name}\b", lower):
                    days_ahead = (day_num - base_date.weekday() + 7) % 7 or 7
                    target_date = base_date + timedelta(days=days_ahead)
                    has_relative_date = True
                    break

        if target_date is None:
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

        if has_relative_date:
            return datetime.combine(target_date, time(hour=9, minute=0))

        return None
