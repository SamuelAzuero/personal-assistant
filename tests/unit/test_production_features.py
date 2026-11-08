"""Unit tests for advanced assistant features: Daily Briefing, Task Completion, Financial Advice, and Dual Email Monitoring."""

import pytest
from unittest.mock import MagicMock
from app.core.intent_parser import IntentParser
from app.core.router import ToolRouter
from app.integrations.protocols import IntentType
from app.services.task_service import TaskService
from app.services.finance_service import FinanceService
from app.services.email_service import EmailService


@pytest.fixture
def parser():
    return IntentParser()


@pytest.fixture
def mock_task_service():
    svc = MagicMock(spec=TaskService)
    svc.list_tasks.return_value = [
        {'task_id': 't1', 'title': 'Hacer simulaciones de tópicos', 'status': 'pending', 'priority': 'high', 'due_date': '2026-11-05T10:00:00'},
        {'task_id': 't2', 'title': 'Estudiar para parcial', 'status': 'pending', 'priority': 'medium', 'due_date': None},
    ]
    svc.complete_task_by_query.return_value = {'task_id': 't1', 'title': 'Hacer simulaciones de tópicos', 'status': 'completed'}
    svc.delete_task_by_query.return_value = {'task_id': 't1', 'title': 'Hacer simulaciones de tópicos'}
    return svc


@pytest.fixture
def mock_finance_service():
    svc = MagicMock(spec=FinanceService)
    svc.get_balance.return_value = {
        'balance_cents': 150000000,
        'income_cents': 250000000,
        'expense_cents': 100000000,
    }
    svc.get_category_breakdown.return_value = [
        {'category': 'Alimentación', 'total_cents': 60000000, 'percentage': 60.0},
        {'category': 'Transporte', 'total_cents': 40000000, 'percentage': 40.0},
    ]
    return svc


@pytest.fixture
def mock_email_service():
    svc = MagicMock(spec=EmailService)
    svc.generate_digest.return_value = {
        'urgent_count': 1,
        'total_unread': 2,
        'items': [
            {'subject': 'Urgente: Entrega de Tópicos', 'sender': 'profesor@unimilitar.edu.co', 'is_urgent': True, 'account': 'est.samuel.azuero@unimilitar.edu.co'},
            {'subject': 'Factura Claro', 'sender': 'pagos@claro.com.co', 'is_urgent': False, 'account': 'user@example.com'},
        ],
        'summary_text': 'Resumen de correos de prueba',
        'gemini_summary': '• Tienes 1 entrega urgente del profesor para Tópicos.',
    }
    return svc


def test_parse_daily_briefing(parser):
    res1 = parser.parse('buenos días')
    assert res1.intent == IntentType.DAILY_BRIEFING

    res2 = parser.parse('cómo va mi día')
    assert res2.intent == IntentType.DAILY_BRIEFING

    res3 = parser.parse('resumen de hoy')
    assert res3.intent == IntentType.DAILY_BRIEFING


def test_parse_task_complete(parser):
    res1 = parser.parse('ya hice las simulaciones de tópicos')
    assert res1.intent == IntentType.TASK_COMPLETE
    assert 'simulaciones' in res1.slots.get('query', '').lower()

    res2 = parser.parse('marcar como hecha la tarea de física')
    assert res2.intent == IntentType.TASK_COMPLETE


def test_parse_financial_advice(parser):
    res1 = parser.parse('consejo financiero sobre mis gastos')
    assert res1.intent == IntentType.FINANCIAL_ADVICE

    res2 = parser.parse('cómo van mis finanzas este mes')
    assert res2.intent == IntentType.FINANCIAL_ADVICE

    res3 = parser.parse('¿puedo gastar hoy?')
    assert res3.intent == IntentType.FINANCIAL_ADVICE


def test_router_handle_task_complete(mock_task_service):
    router = ToolRouter(task_service=mock_task_service)
    res = router.dispatch('u1', IntentParser().parse('ya hice las simulaciones de tópicos'))
    assert 'completada' in res.lower()
    assert 'simulaciones' in res.lower()


def test_router_handle_daily_briefing(mock_task_service, mock_finance_service, mock_email_service):
    router = ToolRouter(
        task_service=mock_task_service,
        finance_service=mock_finance_service,
        email_service=mock_email_service,
    )
    res = router.dispatch('u1', IntentParser().parse('buenos días'))
    assert 'resumen' in res.lower() or 'hola' in res.lower() or 'tareas' in res.lower()


def test_router_handle_financial_advice(mock_finance_service):
    router = ToolRouter(finance_service=mock_finance_service)
    res = router.dispatch('u1', IntentParser().parse('consejo financiero'))
    assert 'cop' in res.lower() or 'saldo' in res.lower()
