"""
Tests for Spanish Language Support and Colombian Pesos (COP) parsing and routing.
"""

import pytest
from app.core.intent_parser import IntentParser, IntentType
from app.core.router import ToolRouter
from app.integrations.protocols import (
    TransactionRecord,
    TransactionType,
    FinanceServiceProtocol,
    EmailServiceProtocol,
    CalendarServiceProtocol,
    TaskServiceProtocol,
    SearchServiceProtocol,
)
from tests.unit.test_core_agent import (
    MockFinanceService,
    MockEmailService,
    MockCalendarService,
    MockTaskService,
    MockSearchService,
)


@pytest.fixture
def parser():
    return IntentParser()


@pytest.fixture
def router():
    return ToolRouter(
        finance_service=MockFinanceService(),
        email_service=MockEmailService(),
        calendar_service=MockCalendarService(has_conflict=False),
        task_service=MockTaskService(),
        search_service=MockSearchService(),
    )


class TestSpanishCOPParser:
    """Test IntentParser handling of Colombian slang, numbers, and Spanish vocabulary."""

    def test_parse_colombian_amounts(self, parser):
        # 50 mil -> 50000 * 100 = 5000000
        intent = parser.parse("gasté 50 mil en corrientazo")
        assert intent.intent == IntentType.FINANCE_ENTRY
        assert intent.slots["amount_cents"] == 5000000
        assert intent.slots["category"] == "Food & Dining"

        # 25k -> 25000 * 100 = 2500000
        intent = parser.parse("pagué 25k en transmilenio")
        assert intent.intent == IntentType.FINANCE_ENTRY
        assert intent.slots["amount_cents"] == 2500000
        assert intent.slots["category"] == "Transportation"

        # 2 millones -> 2000000 * 100 = 200000000
        intent = parser.parse("ingreso de 2 millones por salario")
        assert intent.intent == IntentType.FINANCE_ENTRY
        assert intent.slots["amount_cents"] == 200000000
        assert intent.slots["category"] == "Income"
        assert intent.slots["transaction_type"] == "income"

        # Colombian dot thousands notation: 150.000 -> 150000 * 100 = 15000000
        intent = parser.parse("compré mercado en el éxito por 150.000")
        assert intent.intent == IntentType.FINANCE_ENTRY
        assert intent.slots["amount_cents"] == 15000000
        assert intent.slots["category"] == "Groceries"

    def test_parse_spanish_finance_query(self, parser):
        assert parser.parse("¿cuál es mi saldo actual?").intent == IntentType.FINANCE_QUERY
        assert parser.parse("cuanto he gastado este mes").intent == IntentType.FINANCE_QUERY
        assert parser.parse("resumen de mis finanzas").intent == IntentType.FINANCE_QUERY

    def test_parse_spanish_tasks(self, parser):
        task_intent = parser.parse("recuérdame entregar proyecto final mañana a las 3pm")
        assert task_intent.intent == IntentType.TASK_CREATE
        assert "entregar proyecto" in task_intent.slots["title"].lower()

        list_intent = parser.parse("muéstrame mis tareas pendientes")
        assert list_intent.intent == IntentType.TASK_LIST

    def test_parse_spanish_calendar(self, parser):
        cal_sched = parser.parse("agendar reunión con profesor mañana a las 10am")
        assert cal_sched.intent == IntentType.CALENDAR_SCHEDULE

        cal_query = parser.parse("¿qué tengo en mi agenda hoy?")
        assert cal_query.intent == IntentType.CALENDAR_QUERY

    def test_parse_spanish_emails(self, parser):
        email_check = parser.parse("¿qué correos importantes me llegaron?")
        assert email_check.intent == IntentType.EMAIL_CHECK

    def test_parse_spanish_outings(self, parser):
        outing = parser.parse("recomiéndame planes para salir este fin de semana en Bogotá")
        assert outing.intent == IntentType.OUTING_RESEARCH


class TestSpanishCOPRouter:
    """Test ToolRouter returns Spanish responses and formats Colombian Pesos."""

    def test_finance_entry_spanish_reply(self, parser, router):
        intent_res = parser.parse("gasté 50 mil en almuerzo")
        msg = router.dispatch("user_samuel", intent_res)
        assert "Gasto Registrado con Éxito" in msg
        assert "COP" in msg
        assert "Food & Dining" in msg or "Categoría" in msg

    def test_finance_query_spanish_reply(self, parser, router):
        intent_res = parser.parse("¿cuál es mi saldo?")
        msg = router.dispatch("user_samuel", intent_res)
        assert "Balance de Cuentas (COP)" in msg
        assert "COP" in msg

    def test_email_check_spanish_reply(self, parser, router):
        intent_res = parser.parse("revisar mis correos urgentes")
        msg = router.dispatch("user_samuel", intent_res)
        assert "Resumen de Correos" in msg or "bandeja" in msg.lower()

    def test_calendar_and_tasks_spanish_reply(self, parser, router):
        task_intent = parser.parse("recuérdame estudiar para el parcial mañana a las 8am")
        task_msg = router.dispatch("user_samuel", task_intent)
        assert "Tarea Agregada a tus Pendientes" in task_msg
        assert "estudiar para el parcial" in task_msg.lower()

        cal_intent = parser.parse("agendar cita médica mañana a las 9am")
        cal_msg = router.dispatch("user_samuel", cal_intent)
        assert "Evento Agendado en Calendario" in cal_msg
