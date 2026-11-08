"""Comprehensive Test Suite for Colombian Banking Conversational NLP, Router, and REST API Extensions (R4).

Covers:
1. Intent Parser (NLP):
   - Colombian bank transfer extraction (Bancolombia, Nequi, Nu, Daviplata, Efectivo, cash withdrawals).
   - Multi-account queries and balance checks.
   - Debts & loans recording (receivables, payables, counterparties, due dates, linked accounts).
   - Debt settlement (partial and full settlement, counterparty recognition).
   - Debt queries (who owes me, who I owe, all active debts).
   - Subscription recording (services, amounts, cycles, billing days).
   - Upcoming payment timeline queries.
   - Multi-turn conversation slot prompts and follow-up resolutions.
2. Tool Router:
   - Tool routing and dispatch for all 7 new intents.
   - Emoji-rich, Spanish Markdown responses.
   - Proper service calls and state persistence.
3. REST API Endpoints:
   - GET /api/finance/accounts & POST /api/finance/accounts
   - POST /api/finance/transfers (with net worth preservation check)
   - GET /api/finance/debts & POST /api/finance/debts
   - POST /api/finance/debts/{debt_id}/settle
   - GET /api/finance/subscriptions & POST /api/finance/subscriptions
   - GET /api/finance/calendar/payments
   - Error cases: self-transfer, non-existent debt, invalid amounts, missing fields.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.connection import DatabaseManager
from app.integrations.protocols import IntentType, IntentResult
from app.core.intent_parser import IntentParser
from app.core.router import ToolRouter
from app.services.finance_service import FinanceService
from app.services.account_service import AccountService
from app.services.debt_service import DebtService
from app.services.subscription_service import SubscriptionService
from app.api.finance_router import (
    finance_router,
    set_finance_service,
    set_account_service,
    set_debt_service,
    set_subscription_service,
)


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def memory_db():
    """Isolated in-memory SQLite database initialized with full schema."""
    db = DatabaseManager(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def account_service(memory_db):
    return AccountService(db_manager=memory_db)


@pytest.fixture
def debt_service(memory_db, account_service):
    return DebtService(db_manager=memory_db, account_service=account_service)


@pytest.fixture
def subscription_service(memory_db):
    return SubscriptionService(db_manager=memory_db)


@pytest.fixture
def finance_service(memory_db):
    return FinanceService(db_manager=memory_db)


@pytest.fixture
def intent_parser():
    return IntentParser()


@pytest.fixture
def tool_router(account_service, debt_service, subscription_service, finance_service):
    router = ToolRouter(finance_service=finance_service)
    router.account_service = account_service
    router.debt_service = debt_service
    router.subscription_service = subscription_service
    return router


@pytest.fixture
def api_client(memory_db, account_service, debt_service, subscription_service, finance_service):
    app = FastAPI()
    app.include_router(finance_router)
    set_finance_service(finance_service)
    set_account_service(account_service)
    set_debt_service(debt_service)
    set_subscription_service(subscription_service)
    return TestClient(app)


# ==============================================================================
# 1. Intent Parser: Colombian Banking NLP
# ==============================================================================


class TestColombianBankingNLP:
    """Verifies Colombian banking intent parsing from Spanish conversational text."""

    def test_parse_transfer_bancolombia_to_nequi(self, intent_parser):
        text = "pasé 100 mil de Bancolombia a Nequi"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_TRANSFER
        assert res.confidence >= 0.85
        assert res.slots.get("amount") == 100000.0
        assert res.slots.get("source_account") == "Bancolombia"
        assert res.slots.get("destination_account") == "Nequi"

    def test_parse_transfer_nu_to_daviplata_with_k(self, intent_parser):
        text = "transferí 50k de Nu a Daviplata"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_TRANSFER
        assert res.confidence >= 0.85
        assert res.slots.get("amount") == 50000.0
        assert res.slots.get("source_account") == "Nu"
        assert res.slots.get("destination_account") == "Daviplata"

    def test_parse_withdrawal_to_cash_explicit(self, intent_parser):
        text = "retiré 80 mil de Bancolombia a efectivo"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_TRANSFER
        assert res.slots.get("amount") == 80000.0
        assert res.slots.get("source_account") == "Bancolombia"
        assert res.slots.get("destination_account") == "Efectivo"

    def test_parse_withdrawal_implicit_destination(self, intent_parser):
        text = "saqué 50k de Bancolombia"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_TRANSFER
        assert res.slots.get("amount") == 50000.0
        assert res.slots.get("source_account") == "Bancolombia"
        assert res.slots.get("destination_account") == "Efectivo"

    def test_parse_transfer_missing_slots(self, intent_parser):
        text = "quiero transferir plata a Nequi"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_TRANSFER
        assert res.slots.get("destination_account") == "Nequi"
        assert "amount" in res.missing_slots

    def test_parse_account_query_specific_accounts(self, intent_parser):
        text = "cuánta plata tengo en efectivo y en Nu?"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_QUERY
        accounts = res.slots.get("accounts", [])
        assert "Efectivo" in accounts
        assert "Nu" in accounts

    def test_parse_account_query_single_account(self, intent_parser):
        text = "saldo de Nequi"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_QUERY
        assert res.slots.get("accounts") == ["Nequi"]

    def test_parse_account_query_all_accounts(self, intent_parser):
        text = "mostrar mis cuentas bancarias"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.ACCOUNT_QUERY
        assert res.slots.get("accounts") is None or len(res.slots.get("accounts")) == 0

    def test_parse_debt_record_receivable_with_full_details(self, intent_parser):
        text = "le presté 50k a Juan desde Nequi para el almuerzo, me paga el viernes"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_RECORD
        assert res.slots.get("debt_type") == "receivable"
        assert res.slots.get("counterparty") == "Juan"
        assert res.slots.get("amount") == 50000.0
        assert res.slots.get("account_name") == "Nequi"
        assert "almuerzo" in (res.slots.get("notes") or "").lower()
        assert res.slots.get("due_date") is not None
        assert "T" in res.slots.get("due_date")

    def test_parse_debt_record_payable(self, intent_parser):
        text = "Juan me prestó 30 mil"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_RECORD
        assert res.slots.get("debt_type") == "payable"
        assert res.slots.get("counterparty") == "Juan"
        assert res.slots.get("amount") == 30000.0

    def test_parse_debt_record_le_debo(self, intent_parser):
        text = "le debo 45k a Pedro"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_RECORD
        assert res.slots.get("debt_type") == "payable"
        assert res.slots.get("counterparty") == "Pedro"
        assert res.slots.get("amount") == 45000.0

    def test_parse_debt_settle_payment_to_counterparty(self, intent_parser):
        text = "le pagué 20 mil a Juan"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_SETTLE
        assert res.slots.get("counterparty") == "Juan"
        assert res.slots.get("amount") == 20000.0

    def test_parse_debt_settle_counterparty_paid_me(self, intent_parser):
        text = "Juan me pagó 50k"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_SETTLE
        assert res.slots.get("counterparty") == "Juan"
        assert res.slots.get("amount") == 50000.0

    def test_parse_debt_settle_total(self, intent_parser):
        text = "saldé la deuda con Carlos"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_SETTLE
        assert res.slots.get("counterparty") == "Carlos"

    def test_parse_debt_query_all(self, intent_parser):
        text = "mis deudas"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_QUERY
        assert res.slots.get("query_type") == "all"

    def test_parse_debt_query_payable(self, intent_parser):
        text = "a quién le debo?"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_QUERY
        assert res.slots.get("query_type") == "payable"

    def test_parse_debt_query_receivable(self, intent_parser):
        text = "quién me debe plata?"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.DEBT_QUERY
        assert res.slots.get("query_type") == "receivable"

    def test_parse_subscription_record(self, intent_parser):
        text = "nueva suscripción de Netflix 45k los 15"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.SUBSCRIPTION_RECORD
        assert res.slots.get("service_name") == "Netflix"
        assert res.slots.get("amount") == 45000.0
        assert res.slots.get("billing_day") == 15
        assert res.slots.get("billing_cycle") == "monthly"

    def test_parse_subscription_record_with_account(self, intent_parser):
        text = "suscripción Spotify 20 mil mensual desde Nu"
        res = intent_parser.parse(text)
        assert res.intent == IntentType.SUBSCRIPTION_RECORD
        assert res.slots.get("service_name") == "Spotify"
        assert res.slots.get("amount") == 20000.0
        assert res.slots.get("account_name") == "Nu"

    def test_parse_upcoming_payments_query(self, intent_parser):
        queries = [
            "qué pagos tengo pendientes?",
            "vencimientos de esta semana",
            "próximos pagos",
            "calendario de pagos",
        ]
        for q in queries:
            res = intent_parser.parse(q)
            assert res.intent == IntentType.UPCOMING_PAYMENTS_QUERY, f"Failed on: {q}"


# ==============================================================================
# 2. Multi-turn Slot Resolution
# ==============================================================================


class TestMultiTurnSlotResolution:
    """Verifies follow-up conversational slot filling for banking and debts."""

    def test_transfer_missing_amount_followup(self, intent_parser):
        first_intent = intent_parser.parse("pasa de Bancolombia a Nequi")
        assert first_intent.intent == IntentType.ACCOUNT_TRANSFER
        assert "amount" in first_intent.missing_slots

        # Session context passed from state manager
        session_ctx = {
            "active_intent": first_intent.intent.value,
            "slots": first_intent.slots,
            "missing_slots": first_intent.missing_slots,
        }

        # User replies with the missing amount
        resolved = intent_parser.parse("100 mil", session_context=session_ctx)
        assert resolved.intent == IntentType.ACCOUNT_TRANSFER
        assert resolved.slots.get("amount") == 100000.0
        assert resolved.slots.get("source_account") == "Bancolombia"
        assert resolved.slots.get("destination_account") == "Nequi"

    def test_debt_record_missing_amount_followup(self, intent_parser):
        first_intent = intent_parser.parse("le presté plata a Carlos")
        assert first_intent.intent == IntentType.DEBT_RECORD
        assert "amount" in first_intent.missing_slots

        session_ctx = {
            "active_intent": first_intent.intent.value,
            "slots": first_intent.slots,
            "missing_slots": first_intent.missing_slots,
        }

        # User provides amount
        resolved = intent_parser.parse("50k", session_context=session_ctx)
        assert resolved.intent == IntentType.DEBT_RECORD
        assert resolved.slots.get("amount") == 50000.0
        assert resolved.slots.get("counterparty") == "Carlos"


# ==============================================================================
# 3. Tool Router: Integration & Formatting
# ==============================================================================


class TestToolRouterBanking:
    """Verifies ToolRouter dispatch and Spanish markdown formatting for new intents."""

    def test_route_account_transfer_success(self, tool_router, account_service):
        user_id = "usr_router_01"
        account_service.initialize_default_accounts(user_id)
        # Fund Bancolombia
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        account_service.update_balance(bancolombia.id, 50000000)  # $500,000

        intent = IntentResult(
            intent=IntentType.ACCOUNT_TRANSFER,
            confidence=0.95,
            slots={
                "source_account": "Bancolombia",
                "destination_account": "Nequi",
                "amount": 100000.0,
                "notes": "Transferencia de prueba",
            },
            raw_text="transferí 100k de Bancolombia a Nequi",
        )
        msg = tool_router.dispatch(user_id=user_id, intent_result=intent)
        assert "💸" in msg
        assert "Bancolombia" in msg
        assert "Nequi" in msg
        assert "100.000" in msg or "100,000" in msg

    def test_route_account_query(self, tool_router, account_service):
        user_id = "usr_router_02"
        account_service.initialize_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.update_balance(nequi.id, 15000000)  # $150,000

        intent = IntentResult(
            intent=IntentType.ACCOUNT_QUERY,
            confidence=0.95,
            slots={"accounts": ["Nequi"]},
            raw_text="saldo de Nequi",
        )
        msg = tool_router.dispatch(user_id=user_id, intent_result=intent)
        assert "🏦" in msg
        assert "Nequi" in msg

    def test_route_debt_record_and_settle(self, tool_router, account_service):
        user_id = "usr_router_03"
        account_service.initialize_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.update_balance(nequi.id, 10000000)  # $100,000

        # Record receivable
        intent_record = IntentResult(
            intent=IntentType.DEBT_RECORD,
            confidence=0.95,
            slots={
                "debt_type": "receivable",
                "counterparty": "Andres",
                "amount": 40000.0,
                "account_name": "Nequi",
                "notes": "Almuerzo",
            },
            raw_text="le presté 40k a Andres desde Nequi",
        )
        msg_record = tool_router.dispatch(user_id=user_id, intent_result=intent_record)
        assert "🤝" in msg_record
        assert "Andres" in msg_record
        assert "cobrar" in msg_record.lower()

        # Query debts
        intent_query = IntentResult(
            intent=IntentType.DEBT_QUERY,
            confidence=0.95,
            slots={"query_type": "all"},
            raw_text="mis deudas",
        )
        msg_query = tool_router.dispatch(user_id=user_id, intent_result=intent_query)
        assert "Andres" in msg_query

        # Settle debt
        intent_settle = IntentResult(
            intent=IntentType.DEBT_SETTLE,
            confidence=0.95,
            slots={
                "counterparty": "Andres",
                "amount": 40000.0,
                "account_name": "Nequi",
            },
            raw_text="Andres me pagó 40k",
        )
        msg_settle = tool_router.dispatch(user_id=user_id, intent_result=intent_settle)
        assert "✅" in msg_settle
        assert "Andres" in msg_settle

    def test_route_canonical_r4_debt_loan_with_relative_weekday(self, tool_router, account_service, intent_parser):
        user_id = "usr_canonical_r4_test"
        account_service.initialize_default_accounts(user_id)
        parsed = intent_parser.parse("le presté 50k a Juan desde Nequi para el almuerzo, me paga el viernes")
        resp = tool_router.dispatch(user_id=user_id, intent_result=parsed)
        assert "🤝" in resp
        assert "Juan" in resp
        assert "Nequi" in resp
        assert "almuerzo" in resp
        assert "Error" not in resp

    def test_route_subscription_record_and_upcoming(self, tool_router, account_service):
        user_id = "usr_router_04"
        account_service.initialize_default_accounts(user_id)

        intent_sub = IntentResult(
            intent=IntentType.SUBSCRIPTION_RECORD,
            confidence=0.95,
            slots={
                "service_name": "Netflix",
                "amount": 35000.0,
                "billing_cycle": "monthly",
                "billing_day": 15,
                "account_name": "Nu",
            },
            raw_text="nueva suscripción de Netflix 35k los 15",
        )
        msg_sub = tool_router.dispatch(user_id=user_id, intent_result=intent_sub)
        assert "🔁" in msg_sub
        assert "Netflix" in msg_sub

        intent_upcoming = IntentResult(
            intent=IntentType.UPCOMING_PAYMENTS_QUERY,
            confidence=0.95,
            slots={"days_ahead": 30},
            raw_text="próximos pagos",
        )
        msg_upcoming = tool_router.dispatch(user_id=user_id, intent_result=intent_upcoming)
        assert "📅" in msg_upcoming


# ==============================================================================
# 4. REST API Endpoints: Accounts, Transfers, Debts, Subscriptions, Calendar
# ==============================================================================


class TestRESTAPIFinanceEndpoints:
    """Verifies all new REST API endpoints under /api/finance/."""

    def test_get_and_post_accounts(self, api_client):
        # 1. GET default accounts
        resp = api_client.get("/api/finance/accounts?user_id=usr_api_01")
        assert resp.status_code == 200
        data = resp.json()
        assert "accounts" in data
        assert len(data["accounts"]) == 5
        names = {a["name"] for a in data["accounts"]}
        assert "Efectivo" in names
        assert "Nequi" in names
        assert "Bancolombia" in names
        assert data["total_net_worth"] == 0.0

        # 2. POST new custom account
        create_resp = api_client.post(
            "/api/finance/accounts?user_id=usr_api_01",
            json={
                "name": "Billetera Dale",
                "account_type": "digital_wallet",
                "initial_balance": 25000.0,
                "color": "#10b981",
                "icon": "📱",
            },
        )
        assert create_resp.status_code in (200, 201)
        new_acc = create_resp.json()["account"]
        assert new_acc["name"] == "Billetera Dale"
        assert new_acc["current_balance"] == 25000.0

    def test_post_transfer_and_net_worth_preservation(self, api_client, account_service):
        user_id = "usr_api_02"
        account_service.initialize_default_accounts(user_id)
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.update_balance(bancolombia.id, 20000000)  # $200,000

        # Get net worth before transfer
        summary_before = account_service.get_net_worth_summary(user_id)
        net_worth_before = summary_before.total_net_worth_cents

        # Execute transfer
        transfer_resp = api_client.post(
            "/api/finance/transfers?user_id=usr_api_02",
            json={
                "from_account_id": bancolombia.id,
                "to_account_id": nequi.id,
                "amount": 75000.0,
                "notes": "Recarga Nequi",
            },
        )
        assert transfer_resp.status_code in (200, 201)
        transfer_data = transfer_resp.json()
        assert transfer_data["transfer"]["amount"] == 75000.0

        # Verify net worth preserved exactly (0 net loss)
        summary_after = account_service.get_net_worth_summary(user_id)
        assert summary_after.total_net_worth_cents == net_worth_before

    def test_transfer_validation_errors(self, api_client, account_service):
        user_id = "usr_api_03"
        account_service.initialize_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")

        # Self-transfer rejected
        resp_self = api_client.post(
            "/api/finance/transfers?user_id=usr_api_03",
            json={
                "from_account_id": nequi.id,
                "to_account_id": nequi.id,
                "amount": 10000.0,
            },
        )
        assert resp_self.status_code in (400, 422)

        # Negative amount rejected
        bancolombia = account_service.get_account_by_name(user_id, "Bancolombia")
        resp_neg = api_client.post(
            "/api/finance/transfers?user_id=usr_api_03",
            json={
                "from_account_id": bancolombia.id,
                "to_account_id": nequi.id,
                "amount": -5000.0,
            },
        )
        assert resp_neg.status_code in (400, 422)

    def test_debts_crud_and_settlement(self, api_client, account_service):
        user_id = "usr_api_04"
        account_service.initialize_default_accounts(user_id)
        nequi = account_service.get_account_by_name(user_id, "Nequi")
        account_service.update_balance(nequi.id, 10000000)

        # 1. Create receivable
        rec_resp = api_client.post(
            "/api/finance/debts?user_id=usr_api_04",
            json={
                "debt_type": "receivable",
                "counterparty": "Camila",
                "amount": 60000.0,
                "account_id": nequi.id,
                "due_date": "2026-11-20",
                "notes": "Concierto",
            },
        )
        assert rec_resp.status_code in (200, 201)
        debt = rec_resp.json()["debt"]
        assert debt["counterparty"] == "Camila"
        assert debt["amount"] == 60000.0
        debt_id = debt["id"]

        # 2. GET debts
        debts_resp = api_client.get("/api/finance/debts?user_id=usr_api_04")
        assert debts_resp.status_code == 200
        debts_data = debts_resp.json()
        assert len(debts_data["receivables"]) == 1
        assert debts_data["total_receivable"] == 60000.0

        # 3. Settle debt partially
        settle_resp = api_client.post(
            f"/api/finance/debts/{debt_id}/settle?user_id=usr_api_04",
            json={
                "amount": 30000.0,
                "account_id": nequi.id,
                "notes": "Abono",
            },
        )
        assert settle_resp.status_code in (200, 201)
        settle_data = settle_resp.json()
        assert settle_data["status"] == "partially_paid"

        # 3b. Settle remaining balance fully
        settle_full_resp = api_client.post(
            f"/api/finance/debts/{debt_id}/settle?user_id=usr_api_04",
            json={
                "amount": 30000.0,
                "account_id": nequi.id,
                "notes": "Pago final",
            },
        )
        assert settle_full_resp.status_code in (200, 201)
        assert settle_full_resp.json()["status"] == "settled"

        # 4. Settle non-existent debt returns 404
        settle_404 = api_client.post(
            "/api/finance/debts/99999/settle?user_id=usr_api_04",
            json={"amount": 1000.0},
        )
        assert settle_404.status_code == 404

    def test_subscriptions_and_calendar_payments(self, api_client, account_service):
        user_id = "usr_api_05"
        account_service.initialize_default_accounts(user_id)
        nu = account_service.get_account_by_name(user_id, "Nu")

        # 1. POST subscription
        sub_resp = api_client.post(
            "/api/finance/subscriptions?user_id=usr_api_05",
            json={
                "name": "Spotify Premium",
                "amount": 18900.0,
                "billing_cycle": "monthly",
                "billing_day": 10,
                "account_id": nu.id,
                "category": "Entretenimiento",
            },
        )
        assert sub_resp.status_code in (200, 201)
        sub_data = sub_resp.json()["subscription"]
        assert sub_data["name"] == "Spotify Premium"
        assert sub_data["amount"] == 18900.0

        # 2. GET subscriptions
        list_resp = api_client.get("/api/finance/subscriptions?user_id=usr_api_05")
        assert list_resp.status_code == 200
        subs_list = list_resp.json()["subscriptions"]
        assert len(subs_list) == 1
        assert subs_list[0]["name"] == "Spotify Premium"

        # 3. GET calendar payments
        cal_resp = api_client.get("/api/finance/calendar/payments?user_id=usr_api_05&days_ahead=30")
        assert cal_resp.status_code == 200
        cal_data = cal_resp.json()
        assert "upcoming_payments" in cal_data
        assert "summary" in cal_data
        assert cal_data["summary"]["active_subscriptions_count"] == 1
