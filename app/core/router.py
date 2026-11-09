"""Tool router coordinating domain service execution and markdown response formatting."""

import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.integrations.protocols import (
    CalendarServiceProtocol,
    EmailServiceProtocol,
    FinanceServiceProtocol,
    IntentResult,
    IntentType,
    SearchServiceProtocol,
    TaskServiceProtocol,
    TransactionType,
)


class ToolRouter:
    """Dispatches parsed user intents to corresponding domain services."""

    def __init__(
        self,
        finance_service: Optional[FinanceServiceProtocol] = None,
        email_service: Optional[EmailServiceProtocol] = None,
        calendar_service: Optional[CalendarServiceProtocol] = None,
        task_service: Optional[TaskServiceProtocol] = None,
        search_service: Optional[SearchServiceProtocol] = None,
        gemini_service: Optional[Any] = None,
        account_service: Optional[Any] = None,
        debt_service: Optional[Any] = None,
        subscription_service: Optional[Any] = None,
    ) -> None:
        self.finance_service = finance_service
        self.email_service = email_service
        self.calendar_service = calendar_service
        self.task_service = task_service
        self.search_service = search_service
        self.gemini_service = gemini_service
        self.account_service = account_service
        self.debt_service = debt_service
        self.subscription_service = subscription_service

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

    @property
    def effective_account_service(self) -> Any:
        """Lazy load or return AccountService instance."""
        if self.account_service is not None:
            return self.account_service
        from app.services.account_service import AccountService
        db_mgr = None
        if self.finance_service and hasattr(self.finance_service, "repo"):
            db_mgr = getattr(self.finance_service.repo, "db", None) or getattr(self.finance_service.repo, "db_manager", None)
        self.account_service = AccountService(db_manager=db_mgr)
        return self.account_service

    @property
    def effective_debt_service(self) -> Any:
        """Lazy load or return DebtService instance."""
        if self.debt_service is not None:
            return self.debt_service
        from app.services.debt_service import DebtService
        db_mgr = None
        if self.finance_service and hasattr(self.finance_service, "repo"):
            db_mgr = getattr(self.finance_service.repo, "db", None) or getattr(self.finance_service.repo, "db_manager", None)
        self.debt_service = DebtService(db_manager=db_mgr, account_service=self.effective_account_service)
        return self.debt_service

    @property
    def effective_subscription_service(self) -> Any:
        """Lazy load or return SubscriptionService instance."""
        if self.subscription_service is not None:
            return self.subscription_service
        from app.services.subscription_service import SubscriptionService
        db_mgr = None
        if self.finance_service and hasattr(self.finance_service, "repo"):
            db_mgr = getattr(self.finance_service.repo, "db", None) or getattr(self.finance_service.repo, "db_manager", None)
        self.subscription_service = SubscriptionService(db_manager=db_mgr)
        return self.subscription_service

    def _is_spanish(self, text: str) -> bool:
        """Detect if input contains Spanish vocabulary."""
        if not text:
            return False
        clean = text.strip()
        if any(w in clean for w in ("Resumen del Día", "Mi Saldo", "Mis Tareas", "Ver Correos", "Consejo Financiero")):
            return True
        if clean in ("📊 Balance", "📋 My Tasks", "📬 Check Emails", "❌ /cancel", "balance"):
            from app.config import get_settings
            return get_settings().currency_code == "COP"

        lower = clean.lower()
        spanish_keywords = [
            "gasté", "gaste", "pagué", "pague", "compré", "compre", "ingreso", "ingresos",
            "saldo", "cuál", "cual", "cuánto", "cuanto", "dinero", "finanzas",
            "correo", "correos", "revisa", "revisar", "leer", "bandeja", "urgente",
            "tarea", "tareas", "pendiente", "pendientes", "recuérdame", "recuerdame", "anotar",
            "agenda", "agendar", "reunión", "reunion", "cita", "evento", "horario",
            "planes", "salir", "restaurante", "comer", "sitios", "café", "ocio",
            "cancelar", "cancela", "elimina", "eliminar", "borra", "borrar", "quitar", "quítale", "quitale", "quítame", "quitame", "salir", "ayuda", "hola", "mil", "pesos", "cop", "millones",
            "hoy", "mañana", "manana", "mes", "semana", "buseta", "flota", "pasaje", "pasajes",
            "buenos", "buen", "días", "dias", "día", "dia", "hice", "terminé", "termine", "completé", "complete", "hecha", "hecho", "consejo", "financiero", "financiera", "consejos", "puedo",
            "presté", "preste", "prestó", "presto", "prestado", "debo", "deuda", "deudas", "suscripción", "suscripcion", "suscripciones", "transferencia", "transferí", "transferi", "retiré", "retire", "nequi", "daviplata", "bancolombia", "vencimientos", "cobros"
        ]
        return any(re.search(rf"\b{re.escape(w)}\b", lower) for w in spanish_keywords)

    def dispatch(self, user_id: str, intent_result: IntentResult) -> str:
        """Execute domain action for intent and return conversational Markdown."""
        is_spanish = self._is_spanish(intent_result.raw_text)

        if not intent_result.is_complete:
            missing = ", ".join(intent_result.missing_slots)
            if is_spanish:
                return f"⚠️ Faltan datos requeridos: **{missing}**. Por favor indícalos para continuar."
            return f"⚠️ Missing required details: **{missing}**. Please provide them to continue."

        handler_map = {
            IntentType.FINANCE_ENTRY: self._handle_finance_entry,
            IntentType.FINANCE_QUERY: self._handle_finance_query,
            IntentType.FINANCIAL_ADVICE: self._handle_financial_advice,
            IntentType.EMAIL_CHECK: self._handle_email_check,
            IntentType.CALENDAR_SCHEDULE: self._handle_calendar_schedule,
            IntentType.CALENDAR_QUERY: self._handle_calendar_query,
            IntentType.TASK_CREATE: self._handle_task_create,
            IntentType.TASK_LIST: self._handle_task_list,
            IntentType.TASK_COMPLETE: self._handle_task_complete,
            IntentType.TASK_DELETE: self._handle_task_delete,
            IntentType.DAILY_BRIEFING: self._handle_daily_briefing,
            IntentType.OUTING_RESEARCH: self._handle_outing_research,
            IntentType.ACCOUNT_TRANSFER: self._handle_account_transfer,
            IntentType.ACCOUNT_QUERY: self._handle_account_query,
            IntentType.DEBT_RECORD: self._handle_debt_record,
            IntentType.DEBT_SETTLE: self._handle_debt_settle,
            IntentType.DEBT_QUERY: self._handle_debt_query,
            IntentType.SUBSCRIPTION_RECORD: self._handle_subscription_record,
            IntentType.UPCOMING_PAYMENTS_QUERY: self._handle_upcoming_payments_query,
            IntentType.CANCEL: self._handle_cancel,
            IntentType.UNKNOWN: self._handle_unknown,
        }

        if intent_result.intent == IntentType.UNKNOWN:
            return self._handle_unknown(
                user_id,
                intent_result.slots,
                is_spanish=is_spanish,
                raw_text=intent_result.raw_text,
            )
        handler = handler_map.get(intent_result.intent, self._handle_unknown)
        return handler(user_id, intent_result.slots, is_spanish=is_spanish)

    # -------------------------------------------------------------------------
    # Intent Handlers
    # -------------------------------------------------------------------------

    def _handle_finance_entry(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        amount_cents = slots.get("amount_cents", 0)
        t_type_str = slots.get("transaction_type", "expense")
        t_type = (
            TransactionType.INCOME
            if t_type_str == "income"
            else TransactionType.EXPENSE
        )
        category = slots.get("category", "Other")
        description = slots.get("description", "Transaction")
        account_name = slots.get("account_name") or slots.get("account")

        dollars = amount_cents / 100.0

        if self.finance_service:
            self.finance_service.record_transaction(
                user_id=user_id,
                amount_cents=amount_cents,
                t_type=t_type,
                category=category,
                description=description,
            )
            alerts = self.finance_service.check_budget_alerts(user_id)
        else:
            alerts = []

        # Adjust balance on linked account
        acc_updated = None
        total_nw = None
        if amount_cents > 0:
            try:
                acc_svc = self.effective_account_service
                acc_svc.ensure_default_accounts(user_id)
                target_name = account_name or "Efectivo"
                acc = acc_svc.get_account_by_name(user_id, target_name)
                if acc:
                    delta = amount_cents if t_type == TransactionType.INCOME else -amount_cents
                    acc_updated = acc_svc.adjust_balance(acc.id, delta)
                    nw = acc_svc.get_net_worth(user_id)
                    total_nw = nw.get("total_net_worth", 0)
            except Exception as e:
                logger.error(f"Failed to adjust balance for account {account_name}: {e}")

        category_map = {
            "Food & Dining": "Alimentación y Restaurantes",
            "Groceries": "Supermercado",
            "Transportation": "Transporte",
            "Housing & Utilities": "Vivienda y Servicios",
            "Entertainment": "Entretenimiento",
            "Health & Wellness": "Salud y Bienestar",
            "Shopping": "Compras",
            "Income": "Ingresos",
            "Other": "Otros",
        }
        cat_display = category_map.get(category, category) if is_spanish else category
        amt_str = f"${int(dollars):,} COP" if (is_spanish and dollars.is_integer()) else f"${dollars:,.2f} COP" if is_spanish else f"${dollars:,.2f}"

        if is_spanish:
            if t_type == TransactionType.INCOME:
                msg = (
                    f"💰 **Ingreso Registrado con Éxito**\n"
                    f"• **Monto:** `{amt_str}`\n"
                    f"• **Origen:** {description}\n"
                    f"• **Categoría:** *{cat_display}*"
                )
            else:
                msg = (
                    f"✅ **Gasto Registrado con Éxito**\n"
                    f"• **Monto:** `{amt_str}`\n"
                    f"• **Descripción:** {description}\n"
                    f"• **Categoría:** *{cat_display}*"
                )
            if acc_updated:
                msg += f"\n• **Cuenta:** {acc_updated.name} (Nuevo Saldo: `${acc_updated.balance:,.0f} COP`)"
            if total_nw is not None and account_name:
                msg += f"\n\n💰 **Patrimonio Neto Total:** **${total_nw:,.0f} COP**"
            if alerts:
                alert_text = "\n".join(f"• ⚠️ {a}" for a in alerts)
                msg += f"\n\n**Advertencias de Presupuesto:**\n{alert_text}"
        else:
            if t_type == TransactionType.INCOME:
                msg = (
                    f"💰 **Income Recorded Successfully**\n"
                    f"• **Amount:** `${dollars:,.2f}`\n"
                    f"• **Source:** {description}\n"
                    f"• **Category:** *{category}*"
                )
            else:
                msg = (
                    f"✅ **Expense Recorded Successfully**\n"
                    f"• **Amount:** `${dollars:,.2f}`\n"
                    f"• **Description:** {description}\n"
                    f"• **Category:** *{category}*"
                )
            if acc_updated:
                msg += f"\n• **Account:** {acc_updated.name} (New Balance: `${acc_updated.balance:,.2f}`)"
            if alerts:
                alert_text = "\n".join(f"• ⚠️ {a}" for a in alerts)
                msg += f"\n\n**Budget Warnings:**\n{alert_text}"

        return msg

    def _handle_finance_query(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        query_type = slots.get("query_type", "summary")
        month = slots.get("month")

        if not self.finance_service:
            if is_spanish:
                return (
                    "📊 **Resumen Financiero (COP)**\n"
                    "• **Saldo:** `$0 COP`\n"
                    "• **Ingresos:** `$0 COP`\n"
                    "• **Gastos:** `$0 COP`\n"
                    "*(No hay transacciones registradas aún)*"
                )
            return (
                "📊 **Financial Summary**\n"
                "• **Balance:** `$0.00`\n"
                "• **Income:** `$0.00`\n"
                "• **Expenses:** `$0.00`\n"
                "*(No transactions recorded yet)*"
            )

        if query_type == "balance":
            bal = self.finance_service.get_balance(user_id)
            net_cents = bal.get("balance_cents", 0)
            inc_cents = bal.get("income_cents", 0)
            exp_cents = bal.get("expense_cents", 0)
            if is_spanish:
                net_val = net_cents / 100
                inc_val = inc_cents / 100
                exp_val = exp_cents / 100
                net_str = f"${int(net_val):,} COP" if net_val.is_integer() else f"${net_val:,.2f} COP"
                inc_str = f"${int(inc_val):,} COP" if inc_val.is_integer() else f"${inc_val:,.2f} COP"
                exp_str = f"${int(exp_val):,} COP" if exp_val.is_integer() else f"${exp_val:,.2f} COP"
                return (
                    f"📊 **Balance de Cuentas (COP)**\n"
                    f"• **Saldo Neto:** `{net_str}`\n"
                    f"• **Ingresos Totales:** `{inc_str}`\n"
                    f"• **Gastos Totales:** `{exp_str}`"
                )
            return (
                f"📊 **Account Balance Overview**\n"
                f"• **Net Balance:** `${net_cents / 100:,.2f}`\n"
                f"• **Total Income:** `${inc_cents / 100:,.2f}`\n"
                f"• **Total Expenses:** `${exp_cents / 100:,.2f}`"
            )

        if query_type == "breakdown":
            breakdown = self.finance_service.get_category_breakdown(user_id, month=month)
            if not breakdown:
                if is_spanish:
                    return "📈 **Desglose de Gastos:** No hay gastos registrados para este período."
                return "📈 **Spending Breakdown:** No expenses recorded for this period."

            header = "📈 **Desglose de Gastos por Categoría**" if is_spanish else "📈 **Spending Breakdown by Category**"
            lines = [header]
            for item in breakdown:
                cat = item.get("category", "Other")
                spent = item.get("total_cents", item.get("spent_cents", 0)) / 100.0
                pct = item.get("percentage", 0.0)
                curr_suffix = " COP" if is_spanish else ""
                lines.append(f"• **{cat}:** `${spent:,.2f}{curr_suffix}` ({pct:.1f}%)")
            return "\n".join(lines)

        # General summary
        bal = self.finance_service.get_balance(user_id)
        breakdown = self.finance_service.get_category_breakdown(user_id, month=month)
        net = bal.get("balance_cents", 0) / 100.0
        inc = bal.get("income_cents", 0) / 100.0
        exp = bal.get("expense_cents", 0) / 100.0

        if is_spanish:
            lines = [
                "📊 **Resumen Financiero (COP)**",
                f"• **Saldo Neto:** `${net:,.2f} COP`",
                f"• **Ingresos Totales:** `${inc:,.2f} COP`",
                f"• **Gastos Totales:** `${exp:,.2f} COP`",
            ]
            if breakdown:
                lines.append("\n**Categorías Principales:**")
                for item in breakdown[:3]:
                    lines.append(f"• {item.get('category')}: `${item.get('total_cents', item.get('spent_cents', 0)) / 100:,.2f} COP`")
        else:
            lines = [
                "📊 **Financial Summary**",
                f"• **Net Balance:** `${net:,.2f}`",
                f"• **Total Income:** `${inc:,.2f}`",
                f"• **Total Expenses:** `${exp:,.2f}`",
            ]
            if breakdown:
                lines.append("\n**Top Categories:**")
                for item in breakdown[:3]:
                    lines.append(f"• {item.get('category')}: `${item.get('total_cents', item.get('spent_cents', 0)) / 100:,.2f}`")
        return "\n".join(lines)

    def _handle_email_check(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        urgent_only = slots.get("urgent_only", False)
        account = slots.get("account")

        if not self.email_service:
            if is_spanish:
                return (
                    "📬 **Resumen de Correos**\n"
                    "• ¡Al día! No tienes correos prioritarios sin leer en tu bandeja."
                )
            return (
                "📬 **Email Digest**\n"
                "• All caught up! No unread high-priority emails in your inbox."
            )

        try:
            digest = self.email_service.generate_digest(user_id, account=account)
        except TypeError:
            digest = self.email_service.generate_digest(user_id)

        gemini_summary = digest.get("gemini_summary")
        urgent_count = digest.get("urgent_count", 0)
        items = digest.get("items", [])

        if urgent_only:
            items = [it for it in items if it.get("is_urgent", False)]

        limit = slots.get("limit")
        if limit and isinstance(limit, int) and limit > 0:
            items = items[:limit]

        if not items:
            account_desc = f" ({account})" if account else ""
            if is_spanish:
                return f"📬 **Resumen de Correos{account_desc}:** Tu bandeja no tiene correos pendientes que requieran atención inmediata."
            return f"📬 **Email Digest{account_desc}:** Your inbox has no unread messages requiring attention."

        # If Gemini generated an executive summary and we're answering in Spanish, show it!
        if gemini_summary and is_spanish and not (slots.get("limit") == 1 or slots.get("query_type") == "latest"):
            account_desc = f" ({account})" if account else ""
            return f"📬 **Resumen Inteligente de Correos{account_desc}**\n\n{gemini_summary}"

        is_latest = slots.get("limit") == 1 or slots.get("query_type") == "latest"
        if is_latest and len(items) == 1:
            it = items[0]
            subj = it.get("subject", "Sin asunto" if is_spanish else "No subject")
            sender = it.get("sender", "Desconocido" if is_spanish else "Unknown")
            is_urg = it.get("is_urgent", False)
            icon = "🔴" if is_urg else "✉️"
            snippet = it.get("snippet", "")
            date_str = it.get("date", "")
            if is_spanish:
                res = f"📬 **Resumen de Correos** (Último recibido)\n• {icon} **{subj}** de `{sender}`"
                if date_str:
                    res += f"\n• **Fecha:** {date_str}"
                if snippet:
                    res += f"\n• **Resumen:** *{snippet}*"
                return res
            else:
                res = f"📬 **Email Digest** (Latest message)\n• {icon} **{subj}** from `{sender}`"
                if date_str:
                    res += f"\n• **Date:** {date_str}"
                if snippet:
                    res += f"\n• **Summary:** *{snippet}*"
                return res

        acc_header = f" [{account}]" if account else ""
        title_header = f"📬 **Resumen de Correos{acc_header}** ({urgent_count} urgentes)" if is_spanish else f"📬 **Email Digest{acc_header}** ({urgent_count} urgent)"
        lines = [title_header]
        for it in items:
            subj = it.get("subject", "Sin asunto" if is_spanish else "No subject")
            sender = it.get("sender", "Desconocido" if is_spanish else "Unknown")
            is_urg = it.get("is_urgent", False)
            icon = "🔴" if is_urg else "✉️"
            from_word = "de" if is_spanish else "from"
            acc_tag = f" `[{it.get('account')}]`" if it.get("account") else ""
            lines.append(f"• {icon} **{subj}** {from_word} `{sender}`{acc_tag}")

        return "\n".join(lines)

    def _handle_calendar_schedule(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        title = slots.get("title", "Nuevo Evento" if is_spanish else "New Event")
        start_time = slots.get("start_time")
        end_time = slots.get("end_time")
        location = slots.get("location", "")

        if not start_time or not isinstance(start_time, datetime):
            if is_spanish:
                return "⚠️ Por favor indica una fecha y hora válidas para agendar este evento."
            return "⚠️ Please provide a valid date and time to schedule this event."

        if not end_time or not isinstance(end_time, datetime):
            end_time = start_time

        if self.calendar_service:
            conflicts = self.calendar_service.check_conflicts(user_id, start_time, end_time)
            if conflicts:
                conflict_lines = []
                for c in conflicts:
                    summary = c.get("summary") or c.get("title", "Ocupado" if is_spanish else "Busy")
                    c_start = c.get("start_time")
                    if not c_start and isinstance(c.get("start"), dict):
                        c_start = c["start"].get("dateTime") or c["start"].get("date")
                    elif not c_start and isinstance(c.get("start"), str):
                        c_start = c["start"]

                    c_end = c.get("end_time")
                    if not c_end and isinstance(c.get("end"), dict):
                        c_end = c["end"].get("dateTime") or c["end"].get("date")
                    elif not c_end and isinstance(c.get("end"), str):
                        c_end = c["end"]

                    conflict_lines.append(f"• **{summary}** ({c_start} - {c_end})")
                conflict_details = "\n".join(conflict_lines)
                if is_spanish:
                    return (
                        "⚠️ **Conflicto de Horario Detectado**\n"
                        "Tu solicitud se cruza con eventos existentes en tu agenda:\n"
                        f"{conflict_details}\n\n"
                        "Por favor selecciona otro horario."
                    )
                return (
                    "⚠️ **Scheduling Conflict Detected**\n"
                    "Your request overlaps with existing events:\n"
                    f"{conflict_details}\n\n"
                    "Please select another time slot."
                )

            self.calendar_service.create_event(
                user_id=user_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                location=location,
            )

        time_str = start_time.strftime("%A, %b %d at %I:%M %p")
        if is_spanish:
            msg = f"📅 **Evento Agendado en Calendario**\n• **Evento:** {title}\n• **Hora:** {time_str}"
            if location:
                msg += f"\n• **Ubicación:** {location}"
        else:
            msg = f"📅 **Calendar Event Scheduled**\n• **Event:** {title}\n• **Time:** {time_str}"
            if location:
                msg += f"\n• **Location:** {location}"
        return msg

    def _handle_calendar_query(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        start_time = slots.get("start_time", datetime.utcnow())
        end_time = slots.get("end_time", datetime.utcnow())

        if not self.calendar_service:
            if is_spanish:
                return "📅 **Agenda:** No tienes eventos programados para este período."
            return "📅 **Schedule:** You have no scheduled events for this period."

        events = self.calendar_service.list_events(user_id, start_time, end_time)
        if not events:
            if is_spanish:
                return "📅 **Agenda:** ¡Estás completamente libre durante este período!"
            return "📅 **Schedule:** You are completely free during this period!"

        header = "📅 **Próximos Eventos en tu Agenda**" if is_spanish else "📅 **Upcoming Events on Your Schedule**"
        lines = [header]
        at_word = "a las" if is_spanish else "at"
        for ev in events:
            lines.append(f"• **{ev.get('summary')}** {at_word} {ev.get('start_time')}")
        return "\n".join(lines)

    def _handle_task_create(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        title = slots.get("title", "Tarea" if is_spanish else "Task")
        priority = slots.get("priority", "medium")
        due_date = slots.get("due_date")

        if self.task_service:
            self.task_service.create_task(
                user_id=user_id,
                title=title,
                due_date=due_date,
                priority=priority,
            )

        if is_spanish:
            pri_map = {"urgent": "Urgente", "high": "Alta", "medium": "Media", "low": "Baja"}
            pri_es = pri_map.get(priority.lower(), priority.capitalize())
            msg = f"📝 **Tarea Agregada a tus Pendientes**\n• **Título:** {title}\n• **Prioridad:** {pri_es}"
            if due_date and isinstance(due_date, datetime):
                dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
                dia_str = dias[due_date.weekday()]
                mes_str = meses[due_date.month - 1]
                hora_str = due_date.strftime("%I:%M %p")
                msg += f"\n• **Fecha Límite:** {dia_str}, {due_date.day} de {mes_str} a las {hora_str}"
        else:
            msg = f"📝 **Task Added to To-Do List**\n• **Title:** {title}\n• **Priority:** {priority.capitalize()}"
            if due_date and isinstance(due_date, datetime):
                msg += f"\n• **Due:** {due_date.strftime('%A, %b %d at %I:%M %p')}"
        return msg

    def _handle_task_list(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        status = slots.get("status", "pending")

        if not self.task_service:
            if is_spanish:
                return "📋 **Lista de Tareas:** Tu lista de pendientes está vacía."
            return "📋 **To-Do List:** Your task list is currently empty."

        tasks = self.task_service.list_tasks(user_id, status=status)
        if not tasks:
            status_es = "pendientes" if status == "pending" else ("completadas" if status == "completed" else status)
            if is_spanish:
                return f"📋 **Lista de Tareas:** No tienes tareas {status_es}. ¡Excelente trabajo manteniéndote al día!"
            return f"📋 **To-Do List:** No {status} tasks found. Great job staying organized!"

        status_header = "Pendientes" if status == "pending" else status.capitalize()
        header = f"📋 **Tus Tareas ({status_header})**" if is_spanish else f"📋 **Your To-Do List ({status.capitalize()})**"
        lines = [header]
        due_prefix = "Para" if is_spanish else "Due"
        pri_map = {"urgent": "Urgente", "high": "Alta", "medium": "Media", "low": "Baja"}
        for idx, t in enumerate(tasks, 1):
            title = t.get("title", "Tarea" if is_spanish else "Task")
            pri = t.get("priority", "medium")
            pri_display = pri_map.get(pri.lower(), pri.capitalize()) if is_spanish else pri.capitalize()
            due = t.get("due_date")
            due_text = ""
            if due:
                try:
                    dt = datetime.fromisoformat(str(due))
                    if is_spanish:
                        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                        meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
                        dia_name = dias[dt.weekday()]
                        mes_name = meses[dt.month - 1]
                        hora = dt.strftime("%I:%M %p")
                        due_text = f" ({due_prefix}: {dia_name}, {dt.day} de {mes_name} a las {hora})"
                    else:
                        due_text = f" ({due_prefix}: {dt.strftime('%A, %b %d at %I:%M %p')})"
                except Exception:
                    due_text = f" ({due_prefix}: {due})"
            lines.append(f"{idx}. ⏳ **{title}** [{pri_display}]{due_text}")
        return "\n".join(lines)

    def _handle_task_complete(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        if not self.task_service:
            return "⚠️ Servicio de tareas no disponible." if is_spanish else "⚠️ Task service is not available."

        query = (slots.get("query") or slots.get("title") or "").strip()
        if hasattr(self.task_service, "complete_task_by_query") and query:
            target = self.task_service.complete_task_by_query(user_id, query)
            if target:
                title = target.get("title", "Tarea")
                return (
                    f"✅ **¡Excelente trabajo!** Marqué como completada: *'{title}'*."
                    if is_spanish
                    else f"✅ **Great job!** Marked task as completed: *'{title}'*."
                )

        tasks = self.task_service.list_tasks(user_id=user_id, status="pending")
        if not tasks:
            return "ℹ️ No tienes tareas pendientes por completar." if is_spanish else "ℹ️ You have no pending tasks to complete."

        target = None
        if query:
            target = next((t for t in tasks if query.lower() in t.get("title", "").lower()), None)
        if not target:
            target = tasks[0]

        target_id = target.get("task_id") or target.get("id")
        self.task_service.update_status(target_id, status="completed", user_id=user_id)
        title = target.get("title", "Tarea")
        if is_spanish:
            return f"✅ **¡Completada!** Marqué *'{title}'* como terminada. 🎉"
        return f"✅ **Completed!** Marked *'{title}'* as done. 🎉"

    def _handle_daily_briefing(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        """Synthesize daily status overview across tasks, calendar, emails, and finances."""
        import zoneinfo
        try:
            tz = zoneinfo.ZoneInfo("America/Bogota")
            now = datetime.now(tz)
        except Exception:
            now = datetime.now()

        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        fecha_str = f"{dias[now.weekday()]}, {now.day} de {meses[now.month - 1]}"
        hora_str = now.strftime("%I:%M %p")

        # 1. Tasks
        pending_tasks = self.task_service.list_tasks(user_id, status="pending") if self.task_service else []
        # 2. Finance
        bal = self.finance_service.get_balance(user_id) if self.finance_service else {}
        net = bal.get("balance_cents", 0) / 100.0
        exp = bal.get("expense_cents", 0) / 100.0
        # 3. Emails
        urgent_email_count = 0
        email_items = []
        if self.email_service:
            try:
                e_digest = self.email_service.generate_digest(user_id, account="all", use_gemini=False)
                email_items = e_digest.get("items", [])
                urgent_email_count = e_digest.get("urgent_count", 0)
            except Exception:
                pass

        # Check if Gemini can craft a cohesive morning briefing
        gemini_svc = self.effective_gemini_service
        if gemini_svc and gemini_svc.is_available() and is_spanish:
            tasks_desc = ", ".join([t.get("title", "") for t in pending_tasks[:5]]) or "Ninguna pendiente"
            email_desc = ", ".join([it.get("subject", "") for it in email_items[:4]]) or "Sin correos pendientes"
            prompt = (
                f"Hoy es {fecha_str} a las {hora_str} en Bogotá. Eres el asistente personal de Samuel Azuero.\n"
                f"Estado actual:\n"
                f"- Tareas pendientes ({len(pending_tasks)}): {tasks_desc}\n"
                f"- Correos sin leer: {len(email_items)} ({urgent_email_count} urgentes): {email_desc}\n"
                f"- Finanzas mes (COP): Saldo neto: ${net:,.2f} COP | Gastos: ${exp:,.2f} COP\n\n"
                "Genera un resumen diario (Daily Briefing) inspirador, claro y muy bien formateado en Markdown. "
                "Inicia con el encabezado '🌅 **Resumen del Día**\n👋 ¡Hola Samuel!' "
                "y organiza con viñetas limpias las tareas pendientes, estado de correos y finanzas, con un consejo corto al final."
            )
            try:
                briefing_gemini = gemini_svc.generate_text(prompt=prompt, temperature=0.7)
                if briefing_gemini and briefing_gemini.strip():
                    return briefing_gemini.strip()
            except Exception:
                pass

        # Fallback structured briefing
        if is_spanish:
            lines = [
                f"🌅 **Resumen del Día — {fecha_str} ({hora_str})**",
                "👋 ¡Hola Samuel! Aquí está el panorama para hoy:\n",
                f"📋 **Tareas Pendientes ({len(pending_tasks)}):**",
            ]
            if pending_tasks:
                for idx, t in enumerate(pending_tasks[:4], 1):
                    lines.append(f"  {idx}. ⏳ {t.get('title')}")
                if len(pending_tasks) > 4:
                    lines.append(f"  *(+ {len(pending_tasks) - 4} tareas más)*")
            else:
                lines.append("  • ¡Todo al día! No tienes pendientes registrados.")

            lines.append(f"\n📬 **Correos ({len(email_items)} sin leer, {urgent_email_count} urgentes):**")
            if email_items:
                for it in email_items[:3]:
                    lines.append(f"  • {it.get('subject')} (`{it.get('sender')}`)")
            else:
                lines.append("  • Bandejas al día.")

            lines.append("\n💰 **Finanzas del Mes (COP):**")
            lines.append(f"  • Saldo Neto: `${net:,.2f} COP` | Gastos: `${exp:,.2f} COP`")
            lines.append("\n💪 ¡Que tengas una jornada muy productiva!")
            return "\n".join(lines)

        return (
            f"🌅 **Daily Briefing — {now.strftime('%A, %b %d')}**\n"
            f"• Tasks: {len(pending_tasks)} pending\n"
            f"• Emails: {len(email_items)} unread\n"
            f"• Finances: ${net:,.2f} Net Balance"
        )

    def _handle_financial_advice(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        """Provide intelligent spending diagnosis and financial advice in COP."""
        if not self.finance_service:
            return "⚠️ Servicio financiero no disponible." if is_spanish else "⚠️ Finance service unavailable."

        bal = self.finance_service.get_balance(user_id)
        breakdown = self.finance_service.get_category_breakdown(user_id)
        net = bal.get("balance_cents", 0) / 100.0
        inc = bal.get("income_cents", 0) / 100.0
        exp = bal.get("expense_cents", 0) / 100.0

        gemini_svc = self.effective_gemini_service
        if gemini_svc and gemini_svc.is_available() and is_spanish:
            categories_text = ", ".join([f"{item.get('category')}: ${item.get('total_cents', 0) / 100:,.0f} COP ({item.get('percentage', 0):.1f}%)" for item in breakdown]) or "Sin gastos registrados"
            prompt = (
                f"Eres el asesor financiero personal de Samuel Azuero en Colombia. "
                f"Moneda exclusiva: Pesos Colombianos (COP). No menciones dólares.\n"
                f"Datos financieros del mes actual:\n"
                f"- Saldo actual: ${net:,.0f} COP\n"
                f"- Ingresos acumulados: ${inc:,.0f} COP\n"
                f"- Gastos acumulados: ${exp:,.0f} COP\n"
                f"- Desglose por categorías: {categories_text}\n\n"
                "Genera un diagnóstico financiero claro, motivador y realista en 2 o 3 párrafos cortos. "
                "Menciona explícitamente el saldo actual y las cifras en COP (Pesos Colombianos). "
                "Responde en español de Colombia con formato Markdown y viñetas con tips de ahorro."
            )
            try:
                advice = gemini_svc.generate_text(prompt=prompt, temperature=0.7)
                if advice and advice.strip():
                    if "saldo" not in advice.lower() or "cop" not in advice.lower():
                        return f"💡 **Diagnóstico Financiero (COP)**\n• **Saldo Actual:** `${net:,.2f} COP`\n\n{advice.strip()}"
                    return advice.strip()
            except Exception:
                pass

        if is_spanish:
            lines = [
                "💡 **Diagnóstico y Asesoría Financiera (COP)**",
                f"• **Saldo Actual:** `${net:,.2f} COP`",
                f"• **Gastos Acumulados:** `${exp:,.2f} COP`",
                f"• **Ingresos Registrados:** `${inc:,.2f} COP`\n",
            ]
            if breakdown:
                top = breakdown[0]
                lines.append(f"📌 **Categoría con mayor gasto:** {top.get('category')} con `${top.get('total_cents', 0) / 100:,.2f} COP` ({top.get('percentage', 0):.1f}% del total).")
            lines.append("\n🎯 **Recomendación:** Mantén un fondo de reserva para imprevistos y registra cada gasto diario para no perder el control del presupuesto.")
            return "\n".join(lines)

        return f"💡 **Financial Advice:** Net balance: ${net:,.2f}. Stay mindful of high category expenses."

    def _handle_task_delete(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        if not self.task_service:
            if is_spanish:
                return "⚠️ Servicio de tareas no disponible."
            return "⚠️ Task service is not available."

        title_query = (slots.get("query") or slots.get("title") or "").strip().lower()
        if hasattr(self.task_service, "delete_task_by_query") and title_query:
            deleted = self.task_service.delete_task_by_query(user_id, title_query)
            if deleted:
                target_title = deleted.get("title", "Tarea")
                if is_spanish:
                    return f"🗑️ **Tarea Eliminada con Éxito:** Se eliminó *'{target_title}'* de tus pendientes."
                return f"🗑️ **Task Deleted Successfully:** Removed *'{target_title}'* from your to-do list."

        tasks = self.task_service.list_tasks(user_id=user_id, status="pending")
        if not tasks:
            tasks = self.task_service.list_tasks(user_id=user_id)
        if not tasks:
            if is_spanish:
                return "ℹ️ No tienes tareas registradas para eliminar."
            return "ℹ️ You have no tasks registered to delete."

        target = None
        if title_query:
            target = next((t for t in tasks if title_query in t.get("title", "").lower()), None)
        if not target:
            # Delete the most recently created task by default
            tasks_by_recency = sorted(tasks, key=lambda t: str(t.get("created_at", "")), reverse=True)
            target = tasks_by_recency[0]

        target_id = target.get("task_id") or target.get("id")
        self.task_service.delete_task(target_id, user_id=user_id)

        target_title = target.get("title", "Tarea")
        if is_spanish:
            return f"🗑️ **Tarea Eliminada con Éxito:** Se eliminó *'{target_title}'* de tus pendientes."
        return f"🗑️ **Task Deleted Successfully:** Removed *'{target_title}'* from your to-do list."

    def _handle_outing_research(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        query = slots.get("query", "actividades cerca" if is_spanish else "activities nearby")
        cuisine = slots.get("cuisine")
        activity = slots.get("activity")
        location = slots.get("location", "cerca" if is_spanish else "nearby")

        if self.search_service:
            results = self.search_service.search_outings(user_id, query=query, location=location)
            if results:
                header = f"🌟 **Recomendaciones en {location}**" if is_spanish else f"🌟 **Recommendations for {location}**"
                lines = [header]
                for r in results:
                    name = r.get("name", "Lugar" if is_spanish else "Venue")
                    rating = r.get("rating", 4.5)
                    price = r.get("price_tier", "$$")
                    desc = r.get("description", "")
                    lines.append(f"• **{name}** (⭐ {rating} | {price})\n  {desc}")
                return "\n".join(lines)

        gemini_svc = self.effective_gemini_service
        if gemini_svc and gemini_svc.is_available() and is_spanish:
            prompt = (
                f"Eres el asistente personal de Samuel Azuero en Bogotá, Colombia. "
                f"El usuario busca planes o recomendaciones para: '{query}'. "
                f"Ubicación o contexto: '{location}'. Cocina/Actividad: '{cuisine or activity or 'variado'}'.\n"
                "Recomienda 3 lugares o planes reales y destacados en Bogotá (ej: Usaquén, Chapinero, La Candelaria, Zona G, etc.), "
                "con estimados de precios en Pesos Colombianos (COP) y un tip práctico. Usa formato Markdown con viñetas limpias."
            )
            try:
                outings_text = gemini_svc.generate_text(prompt=prompt, temperature=0.7)
                if outings_text and outings_text.strip():
                    return outings_text.strip()
            except Exception:
                pass

        topic = cuisine or activity or ("Planes" if is_spanish else "Outings")
        if is_spanish:
            return (
                f"🌟 **Recomendaciones Destacadas ({topic} en {location})**\n"
                f"1. **Restaurante La Casona** (⭐ 4.8 | `$$`)\n"
                f"   Ingredientes frescos, excelente sazón y gran ambiente.\n"
                f"2. **Café Bistro Central** (⭐ 4.6 | `$$$`)\n"
                f"   Especialidades de autor y ambiente ideal para compartir.\n"
                f"3. **Ruta del Parque y Café de Origen** (⭐ 4.7 | `$`) \n"
                f"   Caminata al aire libre seguida de café artesanal colombiano."
            )
        return (
            f"🌟 **Top Recommendations ({topic} in {location})**\n"
            f"1. **The Artisan Table** (⭐ 4.8 | `$$`)\n"
            f"   Fresh seasonal ingredients with exceptional ambiance.\n"
            f"2. **Downtown Bistro** (⭐ 4.6 | `$$$`)\n"
            f"   Highly rated chef specials and cozy atmosphere.\n"
            f"3. **City Park Trail & Cafe** (⭐ 4.7 | `$`) \n"
            f"   Scenic outdoor walk followed by artisan coffee."
        )

    def _handle_cancel(self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False) -> str:
        if is_spanish:
            return "❌ Operación cancelada. ¿En qué más te puedo colaborar hoy, Samuel?"
        return "❌ Operation canceled. How else can I assist you?"

    def _handle_unknown(
        self,
        user_id: str,
        slots: Dict[str, Any],
        is_spanish: bool = False,
        raw_text: str = "",
    ) -> str:
        # Check if Gemini AI can handle this as a natural conversational response
        if raw_text and raw_text.strip().lower() not in ("/help", "help", "ayuda", "/start", "start", "info"):
            gemini_svc = self.effective_gemini_service
            if gemini_svc and gemini_svc.is_available():
                try:
                    chat_resp = gemini_svc.chat(raw_text)
                    if chat_resp and chat_resp.strip():
                        return chat_resp
                except Exception:
                    pass

        return (
            "👋 **¡Hola Samuel! Soy tu Asistente Personal Autónomo (Autonomous Personal Assistant).**\n\n"
            "Aquí tienes algunos ejemplos de lo que puedo hacer por ti (Examples of how to use me):\n"
            "• **Finanzas / Finance:** `Gasté 50 mil en almuerzo`, `Spent $45 on groceries`, `¿Cuál es mi saldo?`\n"
            "• **Calendario / Calendar:** `Agendar reunión con profesor mañana a las 3pm`, `Schedule meeting tomorrow at 3pm`\n"
            "• **Tareas / Tasks:** `Recuérdame entregar taller el viernes`, `Remind me to buy milk tomorrow at 8am`\n"
            "• **Correos / Emails:** `¿Qué correos tengo?`, `Check my emails`, `¿Tengo correos urgentes?`\n"
            "• **Planes / Outings:** `Buscar planes para salir en Bogotá`, `Find good Italian restaurants nearby`\n\n"
            "Puedes escribir `/cancel` o `/cancelar` en cualquier momento para anular un comando activo."
        )

    # -------------------------------------------------------------------------
    # Colombian Banking, Debt & Subscription Handlers (R1-R4)
    # -------------------------------------------------------------------------

    def _handle_account_transfer(
        self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False
    ) -> str:
        """Handle inter-account fund transfers."""
        svc = self.effective_account_service
        from_acc = slots.get("from_account") or slots.get("source_account")
        to_acc = slots.get("to_account") or slots.get("destination_account")
        amount_cents = slots.get("amount_cents")
        if amount_cents is None and "amount" in slots:
            amount_cents = int(round(float(slots["amount"]) * 100))
        if amount_cents is None:
            amount_cents = 0
        note = slots.get("note") or slots.get("notes") or ""

        try:
            svc.transfer(
                user_id=user_id,
                from_account_name_or_id=from_acc,
                to_account_name_or_id=to_acc,
                amount_cents=amount_cents,
                description=note,
            )
            net_worth = svc.get_net_worth(user_id)
            total_nw = net_worth.get("total_net_worth", 0)

            from_record = svc.get_account_by_name(user_id, from_acc)
            to_record = svc.get_account_by_name(user_id, to_acc)
            from_bal = f"${from_record.balance:,.0f} COP" if from_record else ""
            to_bal = f"${to_record.balance:,.0f} COP" if to_record else ""

            amount_fmt = f"${amount_cents / 100:,.0f} COP"
            total_fmt = f"${total_nw:,.0f} COP"

            return (
                f"💸 **Transferencia Exitosa**\n\n"
                f"• Origen: **{from_acc}** ({from_bal})\n"
                f"• Destino: **{to_acc}** ({to_bal})\n"
                f"• Monto transferido: **{amount_fmt}**\n\n"
                f"💰 **Patrimonio Neto Total**: **{total_fmt}** (sin pérdida de valor)"
            )
        except Exception as e:
            return f"❌ Error al realizar la transferencia: {str(e)}"

    def _handle_account_query(
        self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False
    ) -> str:
        """Handle balance and net worth inquiries, or direct balance updates."""
        svc = self.effective_account_service
        svc.ensure_default_accounts(user_id)

        action = slots.get("action")
        if action == "set_balance" and slots.get("amount_cents") is not None:
            target_acc_name = slots.get("account_name")
            if not target_acc_name and slots.get("account_names"):
                target_acc_name = slots["account_names"][0]
            if target_acc_name:
                acc = svc.get_account_by_name(user_id, target_acc_name)
                if acc:
                    amt_cents = slots["amount_cents"]
                    updated = svc.set_balance(acc.id, amt_cents)
                    net_worth = svc.get_net_worth(user_id)
                    total_nw = net_worth.get("total_net_worth", 0)
                    bal_fmt = f"${updated.balance:,.0f} COP"
                    icon_map = {
                        "efectivo": "💵",
                        "nequi": "📱",
                        "nu": "🟣",
                        "daviplata": "🔴",
                        "bancolombia": "🟡",
                    }
                    icon = icon_map.get(updated.name.lower(), "💳")
                    return (
                        f"✅ **Saldo Actualizado con Éxito**\n\n"
                        f"• {icon} **Cuenta:** {updated.name}\n"
                        f"• **Nuevo Saldo:** **{bal_fmt}**\n\n"
                        f"💰 **Patrimonio Neto Total:** **${total_nw:,.0f} COP**"
                    )

        account_names = slots.get("account_names") or slots.get("accounts") or []
        all_accounts = slots.get("all_accounts", len(account_names) == 0)

        accounts = svc.get_accounts(user_id, active_only=True)
        if not all_accounts and account_names:
            target_lower = [name.lower() for name in account_names]
            filtered = [a for a in accounts if a.name.lower() in target_lower]
            if filtered:
                accounts = filtered

        net_worth = svc.get_net_worth(user_id)
        total_nw = net_worth.get("total_net_worth", 0)

        icon_map = {
            "efectivo": "💵",
            "nequi": "📱",
            "nu": "🟣",
            "daviplata": "🔴",
            "bancolombia": "🟡",
        }

        lines = ["🏦 💼 **Saldos de tus Cuentas:**\n"]
        for a in accounts:
            icon = icon_map.get(a.name.lower(), "💳")
            bal_fmt = f"${a.balance:,.0f} COP"
            lines.append(f"• {icon} **{a.name}**: {bal_fmt}")

        lines.append(f"\n💰 **Patrimonio Neto Total**: **${total_nw:,.0f} COP**")
        return "\n".join(lines)

    def _handle_debt_record(
        self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False
    ) -> str:
        """Handle debt and loan recordings."""
        svc = self.effective_debt_service
        counterparty = slots.get("counterparty")
        amount_cents = slots.get("amount_cents")
        if amount_cents is None and "amount" in slots:
            amount_cents = int(round(float(slots["amount"]) * 100))
        if amount_cents is None:
            amount_cents = 0
        debt_type = slots.get("debt_type") or slots.get("type", "receivable")
        if debt_type == "payable":
            debt_type = "debt"
        reason = slots.get("reason") or slots.get("notes") or "préstamo"
        due_date = slots.get("due_date")
        account_name = slots.get("account") or slots.get("account_name", "Efectivo")

        try:
            record = svc.record_debt(
                user_id=user_id,
                counterparty=counterparty,
                amount_cents=amount_cents,
                debt_type=debt_type,
                reason=reason,
                due_date=due_date,
                account_name=account_name,
            )

            amount_fmt = f"${amount_cents / 100:,.0f} COP"
            if record.due_date:
                due_str = record.due_date.strftime("%Y-%m-%d") if hasattr(record.due_date, "strftime") else str(record.due_date)[:10]
            else:
                due_str = "Sin fecha límite"

            if record.debt_type.value == "receivable":
                return (
                    f"🤝 **Préstamo Registrado (Por Cobrar)**\n\n"
                    f"• Deudor: **{record.counterparty}**\n"
                    f"• Monto prestado: **{amount_fmt}**\n"
                    f"• Cuenta de desembolso: **{record.account_name}**\n"
                    f"• Concepto: {record.reason}\n"
                    f"• Fecha estimada de cobro: **{due_str}**\n"
                    f"• Estado: **Activo**"
                )
            else:
                return (
                    f"📝 **Deuda Registrada (Por Pagar)**\n\n"
                    f"• Prestamista: **{record.counterparty}**\n"
                    f"• Monto recibido: **{amount_fmt}**\n"
                    f"• Cuenta de abono: **{record.account_name}**\n"
                    f"• Concepto: {record.reason}\n"
                    f"• Fecha límite de pago: **{due_str}**\n"
                    f"• Estado: **Activo**"
                )
        except Exception as e:
            return f"❌ Error al registrar el crédito/deuda: {str(e)}"

    def _handle_debt_settle(
        self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False
    ) -> str:
        """Handle full or partial debt settlements."""
        svc = self.effective_debt_service
        counterparty = slots.get("counterparty")
        amount_cents = slots.get("amount_cents")
        if amount_cents is None and "amount" in slots:
            amount_cents = int(round(float(slots["amount"]) * 100))
        account_name = slots.get("account") or slots.get("account_name")

        debts = svc.list_debts(user_id=user_id, counterparty=counterparty)
        active_debts = [d for d in debts if d.status.value in ("active", "partially_paid")]

        if not active_debts:
            return f"ℹ️ No se encontraron deudas activas con **{counterparty}**."

        target_debt = active_debts[0]

        try:
            if amount_cents and amount_cents < target_debt.remaining_cents:
                res = svc.record_payment(
                    user_id=user_id,
                    debt_id=target_debt.id,
                    amount_cents=amount_cents,
                    account_name=account_name,
                )
                paid_fmt = f"${amount_cents / 100:,.0f} COP"
                rem_fmt = f"${res['debt']['remaining_cents'] / 100:,.0f} COP"
                return (
                    f"✅ **Abono Parcial Registrado**\n\n"
                    f"• Contraparte: **{target_debt.counterparty}**\n"
                    f"• Monto abonado: **{paid_fmt}**\n"
                    f"• Saldo restante: **{rem_fmt}**\n"
                    f"• Estado: **Parcialmente pagado**"
                )
            else:
                res = svc.settle_debt(
                    user_id=user_id,
                    debt_id=target_debt.id,
                    account_name=account_name,
                )
                paid_fmt = f"${target_debt.remaining_cents / 100:,.0f} COP"
                return (
                    f"✅ 🎉 **Deuda Totalmente Saldada**\n\n"
                    f"• Contraparte: **{target_debt.counterparty}**\n"
                    f"• Monto liquidado: **{paid_fmt}**\n"
                    f"• Saldo restante: **$0 COP**\n"
                    f"• Estado: **Liquidada / Settled**"
                )
        except Exception as e:
            return f"❌ Error al liquidar la deuda: {str(e)}"

    def _handle_debt_query(
        self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False
    ) -> str:
        """Handle queries for debts and receivables."""
        svc = self.effective_debt_service
        query_type = slots.get("query_type", "all")
        counterparty = slots.get("counterparty")

        debts = svc.list_debts(user_id=user_id, counterparty=counterparty)
        active_debts = [d for d in debts if d.status.value in ("active", "partially_paid")]

        if not active_debts:
            return "🎉 ¡Excelente! No tienes deudas ni cobros pendientes."

        receivables = [d for d in active_debts if d.debt_type.value == "receivable"]
        payables = [d for d in active_debts if d.debt_type.value == "debt"]

        lines = ["📋 **Estado de Deudas y Cobros:**\n"]

        if query_type in ("all", "receivable") and receivables:
            total_rec = sum(d.remaining_cents for d in receivables)
            lines.append(f"📌 **Por Cobrar (Te deben):** Total: **${total_rec / 100:,.0f} COP**")
            for r in receivables:
                r_due = r.due_date.strftime("%Y-%m-%d") if hasattr(r.due_date, "strftime") else str(r.due_date)[:10]
                due = f" (vence {r_due})" if r.due_date else ""
                lines.append(f"  • **{r.counterparty}**: ${r.remaining_amount:,.0f} COP — _{r.reason}_{due}")
            lines.append("")

        if query_type in ("all", "debt", "payable") and payables:
            total_pay = sum(d.remaining_cents for d in payables)
            lines.append(f"💳 **Por Pagar (Debes):** Total: **${total_pay / 100:,.0f} COP**")
            for p in payables:
                p_due = p.due_date.strftime("%Y-%m-%d") if hasattr(p.due_date, "strftime") else str(p.due_date)[:10]
                due = f" (vence {p_due})" if p.due_date else ""
                lines.append(f"  • **{p.counterparty}**: ${p.remaining_amount:,.0f} COP — _{p.reason}_{due}")
            lines.append("")

        return "\n".join(lines).strip()

    def _handle_subscription_record(
        self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False
    ) -> str:
        """Handle recurring subscription additions."""
        svc = self.effective_subscription_service
        name = slots.get("name") or slots.get("service_name", "Suscripción")
        amount_cents = slots.get("amount_cents")
        if amount_cents is None and "amount" in slots:
            amount_cents = int(round(float(slots["amount"]) * 100))
        if amount_cents is None:
            amount_cents = 0
        billing_cycle = slots.get("billing_cycle", "monthly")
        billing_day = slots.get("billing_day", 1)
        account = slots.get("account") or slots.get("account_name")
        category = slots.get("category", "Entertainment")

        try:
            record = svc.create_subscription(
                user_id=user_id,
                name=name,
                amount_cents=amount_cents,
                billing_cycle=billing_cycle,
                billing_day=billing_day,
                account_name=account,
                category=category,
            )
            cost_fmt = f"${record.amount:,.0f} COP"
            return (
                f"🔁 **Suscripción Registrada**\n\n"
                f"• Servicio: **{record.name}**\n"
                f"• Costo: **{cost_fmt}** / {record.billing_cycle}\n"
                f"• Día de cobro: **{record.renewal_day}** de cada mes\n"
                f"• Cuenta predeterminada: **{record.account_name or 'Nu'}**\n"
                f"• Próxima renovación: **{record.next_payment_date}**"
            )
        except Exception as e:
            return f"❌ Error al registrar la suscripción: {str(e)}"

    def _handle_upcoming_payments_query(
        self, user_id: str, slots: Dict[str, Any], is_spanish: bool = False
    ) -> str:
        """Handle chronological upcoming payments schedule queries."""
        svc = self.effective_subscription_service
        days_ahead = slots.get("days_ahead", 30)

        payments = svc.get_upcoming_payments(user_id=user_id, days_ahead=days_ahead)
        if not payments:
            return f"📅 No tienes compromisos ni pagos pendientes en los próximos {days_ahead} días."

        urgency_icons = {
            "overdue": "🚨",
            "today": "⚠️",
            "soon": "🔔",
            "upcoming": "🗓️",
        }

        lines = [f"📅 **Próximos Pagos y Vencimientos ({days_ahead} días):**\n"]
        for p in payments:
            icon = urgency_icons.get(p.get("urgency", "upcoming"), "🗓️")
            amt_fmt = f"${p['amount']:,.0f} COP"
            due = p["due_date"][:10]
            tag = "Cobro" if p.get("direction") == "inflow" else "Pago"
            lines.append(f"• {icon} **{due}** — {p['title']}: **{amt_fmt}** ({tag})")

        return "\n".join(lines)
