# Project: Autonomous Cloud-Based Personal Assistant

## Architecture
The system follows a modular Clean Architecture / Ports-and-Adapters pattern in Python 3.12 with FastAPI:
- **Presentation Layer**: Telegram Webhook Endpoint (`POST /api/webhook/telegram`), Web Dashboard REST API (`/api/finance/*`, `/api/tasks/*`), and Static Web SPA Mount (`/static`).
- **Core Orchestrator**: NLP Intent & Slot Extractor, Multi-turn Conversation Session Manager, Tool Router, and Audio Note / STT Parser.
- **Domain Services**:
  - `FinanceService`: Double-precision/integer-cent transactions, validation, category aggregation, balance calculations, budget alerts.
  - `EmailService`: Gmail polling, RFC 2822 parsing, urgency scoring, digest generation.
  - `CalendarService`: Event scheduling, listing, interval conflict detection algorithm.
  - `TaskService`: To-do list tracking, priority tagging, status lifecycle.
  - `SearchService`: Outing & leisure recommendations via structured research.
- **Persistence Layer**: SQLite 3 with Write-Ahead Logging (WAL) and typed repositories.
- **Integration Layer**: Abstract Protocols and high-fidelity deterministic Mocks (`MockSTTService`, `MockGmailClient`, `MockCalendarClient`, `MockWebSearchClient`).
- **Cloud Packaging**: Multi-stage Dockerfile (<140MB), Cloud Run deployment manifest, zero-cost scale-to-zero config.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | F01_TEXT_INGEST | Parse incoming Telegram text messages into unified message envelope | M1 | Survey 1 (Spec Miner) |
| 2 | F02_VOICE_INGEST | Ingest Telegram voice notes (OGG/Opus / audio fixtures) | M1 | Survey 1 (Spec Miner) |
| 3 | F03_STT_SIMULATION | Transcribe voice notes to text via deterministic STT adapter / mock | M1 | Survey 1 (Spec Miner) |
| 4 | F04_SESSION_BUFFER | Retain multi-turn conversational context & slot filling | M1 | Survey 1 (Spec Miner) |
| 5 | F05_INTENT_EXTRACTION | Extract intent and parameters (finance, email, calendar, task, outing) | M1 | Survey 1 (Spec Miner) |
| 6 | F06_CLARIFICATION_PROMPT | Prompt user when required intent parameters are missing | M1 | Survey 1 (Spec Miner) |
| 7 | F07_TOOL_ROUTER | Dispatch parsed intent to corresponding domain service | M1 | Survey 1 (Spec Miner) |
| 8 | F08_CONV_FEEDBACK | Format structured domain output into user-friendly Markdown | M1 | Survey 1 (Spec Miner) |
| 9 | F09_SESSION_CANCEL | Allow user to cancel active multi-turn flow (/cancel) | M1 | Survey 1 (Spec Miner) |
| 10 | F10_USER_ISOLATION | Isolate sessions and data by user ID | M1 | Survey 1 (Spec Miner) |
| 11 | F11_EXPENSE_RECORD | Record user expense with timestamp, amount, category, note | M2 | Survey 1 (Spec Miner) |
| 12 | F12_INCOME_RECORD | Record user income with timestamp, amount, category, note | M2 | Survey 1 (Spec Miner) |
| 13 | F13_FIN_VALIDATION | Validate positive amount, valid category, non-empty note | M2 | Survey 1 (Spec Miner) |
| 14 | F14_BALANCE_CALC | Calculate net cumulative balance (Sum(Income) - Sum(Expense)) | M2 | Survey 1 (Spec Miner) |
| 15 | F15_CATEGORY_TAXONOMY | Maintain predefined and custom budget categories | M2 | Survey 1 (Spec Miner) |
| 16 | F16_AUTO_CATEGORIZE | Infer category from transaction notes (e.g. "coffee" -> Food) | M2 | Survey 1 (Spec Miner) |
| 17 | F17_PERIODIC_SUMMARY | Compute monthly, weekly, and custom-range financial summaries | M2 | Survey 1 (Spec Miner) |
| 18 | F18_CATEGORY_SHARE | Compute percentage breakdown across spending categories | M2 | Survey 1 (Spec Miner) |
| 19 | F19_BUDGET_ALERTS | Warn user when spending in a category exceeds defined threshold | M2 | Survey 1 (Spec Miner) |
| 20 | F20_HIGH_VALUE_ALERT | Flag single transactions exceeding high-value limit | M2 | Survey 1 (Spec Miner) |
| 21 | F21_FIN_QUERY | Query transactions by date range, category, or keyword | M2 | Survey 1 (Spec Miner) |
| 22 | F22_TRANSACTION_VOID | Support voiding/deleting errant transactions | M2 | Survey 1 (Spec Miner) |
| 23 | F23_GMAIL_POLL | Fetch unread messages from Gmail inbox (or mock) | M3 | Survey 1 (Spec Miner) |
| 24 | F24_EMAIL_DECODE | Parse MIME / RFC 2822 payload (headers, sender, subject, body) | M3 | Survey 1 (Spec Miner) |
| 25 | F25_URGENCY_SCORING | Compute urgency score (0-100) based on keywords, flags, senders | M3 | Survey 1 (Spec Miner) |
| 26 | F26_EMAIL_CATEGORIZE | Classify email into Personal, Work, Alert, or Noise | M3 | Survey 1 (Spec Miner) |
| 27 | F27_DIGEST_GEN | Generate concise bulleted digest of urgent communications | M3 | Survey 1 (Spec Miner) |
| 28 | F28_PROACTIVE_ALERT | Format high-priority alert for immediate Telegram notification | M3 | Survey 1 (Spec Miner) |
| 29 | F29_EMAIL_QUERY | Query email summaries on demand ("check my emails") | M3 | Survey 1 (Spec Miner) |
| 30 | F30_MOCK_GMAIL_FIXTURE | Provide high-fidelity Gmail API mock with synthetic payloads | M3 | Survey 1 (Spec Miner) |
| 31 | F31_OAUTH_REFRESH | Support simulated or live OAuth2 token lifecycle | M3 | Survey 1 (Spec Miner) |
| 32 | F32_TASK_CREATE | Create daily to-do item with priority, due date, description | M3 | Survey 1 (Spec Miner) |
| 33 | F33_TASK_LIFECYCLE | Update task status (pending -> in_progress -> completed -> cancelled) | M3 | Survey 1 (Spec Miner) |
| 34 | F34_TASK_FILTER | List tasks filtered by status, due date, or priority | M3 | Survey 1 (Spec Miner) |
| 35 | F35_REMINDER_SCHEDULE | Calculate upcoming due reminders and overdue alerts | M3 | Survey 1 (Spec Miner) |
| 36 | F36_CAL_QUERY | Query events on Google Calendar for a date range | M3 | Survey 1 (Spec Miner) |
| 37 | F37_CAL_RESERVE | Create new event on Google Calendar with title, start, end, location | M3 | Survey 1 (Spec Miner) |
| 38 | F38_CAL_CONFLICT | Detect scheduling conflicts (overlapping time intervals) | M3 | Survey 1 (Spec Miner) |
| 39 | F39_CAL_DELETE | Cancel/delete calendar event | M3 | Survey 1 (Spec Miner) |
| 40 | F40_MOCK_CAL_FIXTURE | Provide Google Calendar API v3 mock with conflict testing | M3 | Survey 1 (Spec Miner) |
| 41 | F41_OUTING_RESEARCH | Recommend dining, leisure, or outings based on user criteria | M3 | Survey 1 (Spec Miner) |
| 42 | F42_PARAM_EXTRACTION | Extract cuisine, location, budget, activity from outing request | M3 | Survey 1 (Spec Miner) |
| 43 | F43_STRUCTURED_RECOMM | Return curated suggestions with rating, price level, description | M3 | Survey 1 (Spec Miner) |
| 44 | F44_MOCK_SEARCH_FIXTURE| Deterministic search provider mock for offline outing tests | M3 | Survey 1 (Spec Miner) |
| 45 | F45_TG_WEBHOOK_HANDLER | Receive incoming Telegram Webhook updates (HTTPS POST) | M4 | Survey 1 (Spec Miner) |
| 46 | F46_TG_SECRET_VALIDATION| Validate X-Telegram-Bot-Api-Secret-Token header | M4 | Survey 1 (Spec Miner) |
| 47 | F47_TG_KEYBOARDS | Render quick-action Telegram inline & reply keyboards | M4 | Survey 1 (Spec Miner) |
| 48 | F48_DASHBOARD_SPA | Lightweight responsive HTML5/CSS3/JS single page application | M4 | Survey 1 (Spec Miner) |
| 49 | F49_KPI_CARDS | Render financial KPI cards (Balance, Income, Expense, Savings) | M4 | Survey 1 (Spec Miner) |
| 50 | F50_CATEGORY_CHART | Render interactive spending breakdown donut chart (Chart.js) | M4 | Survey 1 (Spec Miner) |
| 51 | F51_TREND_CHART | Render monthly/weekly spending trend chart | M4 | Survey 1 (Spec Miner) |
| 52 | F52_TASK_BOARD | Interactive task management list on dashboard | M4 | Survey 1 (Spec Miner) |
| 53 | F53_REST_GATEWAY | Provide secure JSON endpoints for dashboard data consumption | M4 | Survey 1 (Spec Miner) |
| 54 | F54_HEALTH_PROBES | Liveness and readiness endpoints (`/health`, `/ready`) | M4 | Survey 1 (Spec Miner) |
| 55 | F55_DOCKER_PACKAGING | Multi-stage Dockerfile optimized for minimal size (<140MB) | M4 | Survey 1 (Spec Miner) |
| 56 | F56_DEPLOY_SCRIPT | Automated deployment shell script for Google Cloud Run | M4 | Survey 1 (Spec Miner) |
| 57 | F57_ENV_TEMPLATE | Comprehensive `.env.example` with documented configurations | M4 | Survey 1 (Spec Miner) |
| 58 | F58_VERIFICATION_SUITE | Automated test runner verifying 100% of core functionality | M5 | Survey 1 (Spec Miner) |
| 59 | F59_IDEMPOTENCY_DEDUP | Prevent duplicate transaction/event insertions on retry | M2 | Survey 1 (Spec Miner) |
| 60 | F60_DEBT_RECORD | Record new debt or loan with counterparty, COP amount, reason, due date, account | M6 | Survey 2 (Spec Miner) |
| 61 | F61_DEBT_QUERY | Query active, partially paid, or settled debts and receivables with summary totals | M6 | Survey 2 (Spec Miner) |
| 62 | F62_DEBT_SETTLEMENT | Full or partial settlement payment adjusting debt and linked account balances | M6 | Survey 2 (Spec Miner) |
| 63 | F63_DEBT_DUE_ALERT | Compute impending payment deadlines and overdue debt/loan collection warnings | M6 | Survey 2 (Spec Miner) |
| 64 | F64_ACCOUNT_SCHEMA_INIT | Initialize default accounts (Efectivo, Nequi, Nu, Daviplata, Bancolombia) & dynamic creation | M6 | Survey 2 (Spec Miner) |
| 65 | F65_ACCOUNT_LINKED_TX | Attribute transactions to specific accounts with automatic balance adjustment | M6 | Survey 2 (Spec Miner) |
| 66 | F66_ACCOUNT_TRANSFER | Inter-account transfers with exact integer cents and zero net wealth loss | M6 | Survey 2 (Spec Miner) |
| 67 | F67_NET_WORTH_AGGREGATION | Real-time total net worth and asset allocation percentages across all accounts | M6 | Survey 2 (Spec Miner) |
| 68 | F68_SUBSCRIPTION_CRUD | Create and manage recurring subscriptions with renewal day and month-end clamping | M6 | Survey 2 (Spec Miner) |
| 69 | F69_PAYMENT_CALENDAR | Chronological payment calendar aggregating subscriptions, debt dues, and loan collections | M6 | Survey 2 (Spec Miner) |
| 70 | F70_SUBSCRIPTION_REMINDERS | Upcoming subscription renewal detection within alert horizon | M6 | Survey 2 (Spec Miner) |
| 71 | F71_NLP_DEBT_INTENT | Telegram NLP for Colombian debts and loans ("le presté 50k a Juan", "le debo a Carlos") | M7 | Survey 2 (Spec Miner) |
| 72 | F72_NLP_TRANSFER_INTENT | Telegram NLP for inter-account transfers ("pasé 100 mil de Bancolombia a Nequi") | M7 | Survey 2 (Spec Miner) |
| 73 | F73_NLP_ACCOUNT_QUERY | Telegram NLP for account balance queries ("cuánta plata tengo en efectivo y en Nu?") | M7 | Survey 2 (Spec Miner) |
| 74 | F74_NLP_UPCOMING_PAYMENTS | Telegram NLP for upcoming payment and subscription queries | M7 | Survey 2 (Spec Miner) |
| 75 | F75_DASHBOARD_ACCOUNT_CARDS | Web dashboard interactive account balance cards and net worth banner | M7 | Survey 2 (Spec Miner) |
| 76 | F76_DASHBOARD_DEBT_WIDGET | Web dashboard debt and receivable tables with due date badges and settlement modals | M7 | Survey 2 (Spec Miner) |
| 77 | F77_DASHBOARD_CALENDAR_WIDGET | Web dashboard subscription calendar timeline and management modal | M7 | Survey 2 (Spec Miner) |
| 78 | F78_REST_EXTENDED_ENDPOINTS | REST API endpoints for accounts, transfers, debts, subscriptions, and calendar | M7 | Survey 2 (Spec Miner) |
| 79 | F79_SECRETS_SANITIZATION | Robust .gitignore excluding .env, *.db, deploy/cloud_run_env.yaml, .venv, caches | M8 | Survey 2 (Spec Miner) |
| 80 | F80_ENV_EXAMPLE_HYGIENE | Updated .env.example with safe placeholders and complete documentation | M8 | Survey 2 (Spec Miner) |
| 81 | F81_GIT_REPO_INITIALIZATION | Clean git repo init, commit under est.samuel.azuero@unimilitar.edu.co, and remote push | M8 | Survey 2 (Spec Miner) |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Agent & Multi-Turn Tool Orchestration | Conversational NLP parser, multi-turn session buffer, tool routing, simulated STT voice decoder, Telegram webhook adapter | none | DONE |
| M2 | Personal Finance Ledger & Analytical Engine | SQLite transaction schema & repository, validation, balance calculations, category breakdowns, budget alerts, idempotency | none | DONE |
| M3 | Google Integrations & External Services | Email monitoring & urgency scoring, Calendar event CRUD & conflict detection, Task management, Outing research & mocks | none | DONE |
| M4 | Dual User Interface & Free-Tier Cloud Packaging | Web dashboard (SPA, charts, task board), FastAPI static mount, Dockerfile, Cloud Run deploy scripts, .env.example | M1, M2, M3 | DONE |
| M5 | Final E2E Verification & Adversarial Hardening | Phase 1: 100% E2E test suite pass rate (Tiers 1-4). Phase 2: Tier 5 adversarial coverage hardening | M1, M2, M3, M4, E2E-TEST | DONE |
| E2E-TEST | Opaque-Box E2E Testing Suite Track | Requirement-driven 4-tier test runner & test cases (Tiers 1-4, 72+ tests) -> TEST_READY.md | none | DONE |
| M6 | Debt & Multi-Account Banking Domain Core | DB schema extensions (accounts, transfers, debts, subscriptions), repositories, domain services, COP balance debit/credit, zero-loss transfers | none | DONE |
| M7 | Conversational NLP & Dual UI Dashboard Extensions | Colombian Spanish NLP intent extractors & tool router, REST endpoints (/api/accounts, /api/debts, etc.), Web UI cards & modals | M6 | DONE |
| M8 | Secrets Sanitization & Secure Git Setup | Comprehensive .gitignore, clean .env.example, git init, commit under est.samuel.azuero@unimilitar.edu.co, remote push | none | DONE |
| M9 | Final Expansion E2E Verification & Hardening | 100% pass rate across baseline + new unit & E2E tests, automated git secrets scan test | M6, M7, M8, E2E-TEST-2 | DONE |
| E2E-TEST-2 | Opaque-Box E2E Testing Suite Track (Expansion) | Comprehensive test suite for F60-F81 across Tiers 1-4 and secret scan -> TEST_EXPANSION_READY.md | none | DONE |

## Interface Contracts

### 1. Intent Parser & Tool Router Interface
```python
class IntentType(str, Enum):
    FINANCE_ENTRY = "finance_entry"
    FINANCE_QUERY = "finance_query"
    EMAIL_CHECK = "email_check"
    CALENDAR_SCHEDULE = "calendar_schedule"
    CALENDAR_QUERY = "calendar_query"
    TASK_CREATE = "task_create"
    TASK_LIST = "task_list"
    OUTING_RESEARCH = "outing_research"
    CANCEL = "cancel"
    UNKNOWN = "unknown"

@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    slots: Dict[str, Any]
    is_complete: bool
    missing_slots: List[str]
    raw_text: str

class IntentParserProtocol(Protocol):
    def parse(self, text: str, session_context: Optional[Dict[str, Any]] = None) -> IntentResult: ...
```

### 2. Finance Ledger Service Interface
```python
class TransactionType(str, Enum):
    EXPENSE = "expense"
    INCOME = "income"

@dataclass
class TransactionRecord:
    id: str
    user_id: str
    amount_cents: int
    transaction_type: TransactionType
    category: str
    description: str
    timestamp: datetime

class FinanceServiceProtocol(Protocol):
    def record_transaction(self, user_id: str, amount_cents: int, t_type: TransactionType, category: str, description: str) -> TransactionRecord: ...
    def get_balance(self, user_id: str) -> Dict[str, Any]: ...  # balance_cents, income_cents, expense_cents
    def get_category_breakdown(self, user_id: str, month: Optional[str] = None) -> List[Dict[str, Any]]: ...
    def check_budget_alerts(self, user_id: str) -> List[str]: ...
```

### 3. Email & Calendar Service Interfaces
```python
class EmailServiceProtocol(Protocol):
    def poll_unread(self, user_id: str) -> List[Dict[str, Any]]: ...
    def generate_digest(self, user_id: str) -> Dict[str, Any]: ...  # urgent_count, items: List[Dict], summary_text

class CalendarServiceProtocol(Protocol):
    def list_events(self, user_id: str, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]: ...
    def create_event(self, user_id: str, title: str, start_time: datetime, end_time: datetime, location: str = "") -> Dict[str, Any]: ...
    def check_conflicts(self, user_id: str, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]: ...
```

### 4. Audio Transcription Interface
```python
class AudioTranscriptionProtocol(Protocol):
    def transcribe(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str: ...
```

## Code Layout
```
personal_assistant/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI application, webhook & REST routing, static mount
│   ├── config.py                  # Pydantic BaseSettings & configuration
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py          # SQLite WAL connection manager
│   │   ├── schema.sql             # SQLite tables DDL
│   │   └── repositories/          # Data access repositories
│   ├── core/
│   │   ├── __init__.py
│   │   ├── intent_parser.py       # Rule-based and keyword NLP intent extractor
│   │   ├── session_manager.py     # Multi-turn conversational buffer
│   │   ├── router.py              # Tool routing coordinator
│   │   └── audio.py               # Voice audio note parser & STT adapter
│   ├── services/
│   │   ├── __init__.py
│   │   ├── finance_service.py     # Income/expense calculations & category analytics
│   │   ├── email_service.py       # Gmail unread monitoring & priority digest
│   │   ├── calendar_service.py    # Google Calendar CRUD & interval conflict detection
│   │   ├── task_service.py        # To-do lists & reminder scheduling
│   │   └── search_service.py      # Outing & leisure recommendations
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── protocols.py           # Interface contracts (Protocols)
│   │   ├── mocks.py               # Deterministic in-memory mocks
│   │   ├── telegram_client.py     # Telegram Bot API webhook client
│   │   ├── gmail_client.py        # Gmail API client adapter
│   │   └── calendar_client.py     # Google Calendar API adapter
│   ├── api/
│   │   ├── __init__.py
│   │   ├── webhook.py             # Telegram webhook endpoint (POST /api/webhook/telegram)
│   │   ├── finance_router.py      # Dashboard REST endpoints (/api/finance/*)
│   │   ├── task_router.py         # Dashboard REST endpoints (/api/tasks/*)
│   │   └── health_router.py       # Health check endpoints (/health, /ready)
│   └── static/
│       ├── index.html             # Dashboard single-page application
│       ├── css/
│       │   └── styles.css         # Modern, mobile-responsive CSS
│       └── js/
│           ├── app.js             # Dashboard frontend app
│           └── charts.js          # Chart.js financial visualization
├── tests/
│   ├── conftest.py                # Fixtures, test client, in-memory DB
│   ├── tier1_feature_coverage/    # Tier 1 tests (6 per feature across R1-R5)
│   ├── tier2_boundary_corner/     # Tier 2 tests (boundary & edge cases)
│   ├── tier3_combinations/        # Tier 3 tests (cross-feature interactions)
│   └── tier4_real_world/          # Tier 4 tests (real-world workflows)
├── deploy/
│   ├── Dockerfile                 # Multi-stage production container
│   ├── deploy_cloud_run.sh        # Google Cloud Run deployment script
│   └── cloudrun.yaml              # Cloud Run declarative service manifest
├── .env.example                   # Environment variable template
├── requirements.txt               # Production dependencies
├── requirements-dev.txt           # Test dependencies
└── README.md                      # Documentation & instructions
```
