# Test Infrastructure Specification: Autonomous Cloud-Based Personal Assistant

**Document**: `TEST_INFRA.md`  
**Target Project**: Autonomous Cloud-Based Personal Assistant  
**Author**: E2E Test Writer  
**Status**: ACTIVE & RATIFIED  
**Integrity Mode**: Development & Cloud Free-Tier Ready  

---

## 1. Executive Summary & Testing Philosophy

The acceptance criteria set forth in `ORIGINAL_REQUEST.md` mandate a **100% automated test pass rate** across all core functionalities: natural language intent routing, multi-turn conversational flows, financial ledger precision, integration mocks (Gmail, Calendar, Voice/STT, Web Search), and dual user interfaces (Telegram webhook and lightweight Web Dashboard).

To fulfill these requirements on zero-cost free-tier cloud environments (Cloud Run / Firebase), the test infrastructure follows the **Opaque-Box (Black-Box)** testing paradigm.

### 1.1 The Opaque-Box Paradigm
1. **Public Interface Contracts Only**: Tests evaluate system behavior exclusively through public touchpoints:
   - Presentation Layer: Telegram Webhook (`POST /api/webhook/telegram`), Web Dashboard REST API (`/api/finance/*`, `/api/tasks/*`, `/health`, `/ready`), and Static SPA mount (`/`).
   - Domain Facade & Protocols: System services implementing public protocols (`IntentParserProtocol`, `FinanceServiceProtocol`, `EmailServiceProtocol`, `CalendarServiceProtocol`, `AudioTranscriptionProtocol`).
2. **Implementation Decoupling**: Tests do not inspect private method names or transient internal variables. Internal refactoring (e.g., regex to LLM routing or repository caching) does not break test assertions.
3. **Hermetic & Offline Execution**:
   - Zero live external network calls: All interactions with Telegram Bot API, Google Gmail API v1, Google Calendar API v3, Speech-to-Text, and Web Search are handled by deterministic in-memory test doubles.
   - Pinned Clock: All temporal evaluations use a frozen reference clock pinned to `2026-11-04T12:00:00Z`. Relative expressions like "today", "tomorrow", "yesterday", "this month" evaluate identically across runs.
   - Clean Database Isolation: Every test executes against an isolated, freshly migrated SQLite in-memory database with Write-Ahead Logging (WAL) and foreign keys enabled.

---

## 2. Test Architecture & Directory Structure

```
tests/
├── conftest.py                      # Global fixtures: client, in-memory DB, mocks, fixed clock
├── fixtures/                        # Authoritative static JSON test fixtures
│   ├── financial_transactions.json  # Nominal & edge financial records
│   ├── gmail_payloads.json          # Simulated RFC 2822 & Gmail REST payloads
│   ├── calendar_events.json         # Mock Calendar events & interval collisions
│   ├── telegram_updates.json        # Text & voice webhook update envelopes
│   └── multi_turn_conversations.json# Multi-turn slot-filling & dialogue trees
├── tier1_feature_coverage/          # Tier 1: Nominal feature coverage (>=5 tests per R1-R5, 30 tests)
│   ├── test_r1_agent_core.py        # T1-R1-01 to T1-R1-06 (NLP, session, voice routing)
│   ├── test_r2_finance.py           # T1-R2-01 to T1-R2-06 (Ledger, balance, categories, alerts)
│   ├── test_r3_email.py             # T1-R3-01 to T1-R3-06 (Gmail unread, urgency, digest)
│   ├── test_r4_schedule_tasks.py    # T1-R4-01 to T1-R4-06 (Calendar events, tasks, outing search)
│   └── test_r5_ui_cloud.py          # T1-R5-01 to T1-R5-06 (Webhook, dashboard API, health probes)
├── tier2_boundary_corner/           # Tier 2: Boundary & negative cases (>=5 tests per R1-R5, 30 tests)
│   ├── test_r1_boundary.py          # T2-R1-01 to T2-R1-06 (4096-char, injection, TTL expiry)
│   ├── test_r2_boundary.py          # T2-R2-01 to T2-R2-06 (Zero/negative, precision drift, dedup)
│   ├── test_r3_boundary.py          # T2-R3-01 to T2-R3-06 (Empty inbox, malformed MIME, 429 backoff)
│   ├── test_r4_boundary.py          # T2-R4-01 to T2-R4-06 (Interval collisions, inverted times, past due)
│   └── test_r5_boundary.py          # T2-R5-01 to T2-R5-06 (Missing secret, corrupted audio, malformed params)
├── tier3_combinations/              # Tier 3: Cross-feature pairwise interactions (8 tests)
│   └── test_cross_feature_combinations.py # T3-01 to T3-08 (R1xR2, R1xR3, R1xR4, R2xR4, R3xR4, R2xR5, R4xR5, R3xR5)
└── tier4_real_world/                # Tier 4: Real-world multi-turn application scenarios (4 tests)
    └── test_real_world_scenarios.py # Scenarios 4.1 to 4.4 (Executive morning, Outing budget, Travel crisis, Audit)
```

---

## 3. Hermetic Test Doubles & Synthetic Fixtures

### 3.1 Pinned Clock (`fixed_clock`)
- Base Timestamp: `2026-11-04T12:00:00Z` (`1793793600` epoch seconds)
- Today: `2026-11-04`
- Tomorrow: `2026-11-05`
- Yesterday: `2026-11-03`
- Current Month: `2026-11`

### 3.2 In-Memory SQLite Isolation (`mock_db`)
Every test receives a dedicated in-memory SQLite database connection (`sqlite3.connect(":memory:")`) with:
- PRAGMA foreign_keys = ON
- Complete table DDL: `users`, `conversation_sessions`, `transactions`, `budgets`, `tasks`, `calendar_events`, `email_messages`
- Automatic rollback/close on teardown.

### 3.3 Test Doubles (Integration Mocks)
- **`MockTelegramBotClient`**: Captures outgoing messages in `sent_messages: List[Dict]`. Simulates webhook event dispatch with optional secret header `X-Telegram-Bot-Api-Secret-Token`.
- **`MockGmailClient`**: Stores synthetic emails in memory. Implements unread filtering, urgency scoring (0-100), label modification, and configurable HTTP 429/401 fault injection.
- **`MockCalendarClient`**: Evaluates half-open intervals `[start_time, end_time)` to detect overlaps. Provides CRUD operations for calendar events.
- **`MockSTTService`**: Maps audio byte signatures and file IDs to deterministic transcripts without invoking cloud STT APIs.
- **`MockWebSearchClient`**: Provides structured recommendations (name, rating, address, price, tags) based on cuisine and location queries.

---

## 4. 4-Tier Test Breakdown & Feature Mapping

| Tier | Directory | Test Files | Total Tests | Focus |
|---|---|---|---|---|
| **Tier 1** | `tests/tier1_feature_coverage/` | 5 files | 30 tests | Nominal happy-path behavior across R1-R5 |
| **Tier 2** | `tests/tier2_boundary_corner/` | 5 files | 30 tests | Boundary conditions, errors, stress, and security |
| **Tier 3** | `tests/tier3_combinations/` | 1 file | 8 tests | Cross-subsystem pairwise integration workflows |
| **Tier 4** | `tests/tier4_real_world/` | 1 file | 4 tests | Full multi-turn realistic user lifecycle scenarios |
| **Total** | | | **72 tests** | **100% Comprehensive Opaque-Box Coverage** |

### 4.1 Requirement Traceability
- **R1 (Agent Core & NLP Routing)**: 6 Tier 1 tests, 6 Tier 2 tests, 4 Tier 3 tests, 4 Tier 4 steps.
- **R2 (Finance Ledger & Analytics)**: 6 Tier 1 tests, 6 Tier 2 tests, 3 Tier 3 tests, 3 Tier 4 steps.
- **R3 (Gmail Digest & Urgency)**: 6 Tier 1 tests, 6 Tier 2 tests, 3 Tier 3 tests, 2 Tier 4 steps.
- **R4 (Calendar, Tasks, Outings)**: 6 Tier 1 tests, 6 Tier 2 tests, 4 Tier 3 tests, 3 Tier 4 steps.
- **R5 (Telegram Webhook & Dashboard UI)**: 6 Tier 1 tests, 6 Tier 2 tests, 3 Tier 3 tests, 2 Tier 4 steps.

---

## 5. Test Runner & Quality Gates

The test runner script `run_tests.sh` executes tests in a controlled virtual environment with color output, tier filtering, and zero external network access.

```bash
# Run complete test suite (all 72+ tests)
./run_tests.sh

# Run specific tiers
./run_tests.sh --tier1
./run_tests.sh --tier2
./run_tests.sh --tier3
./run_tests.sh --tier4
```

### Flakiness Elimination Protocol
1. **Zero Real Network Access**: Any attempt to connect to external hosts (`api.telegram.org`, `googleapis.com`) results in a socket rejection.
2. **Integer Cent Financial Math**: All currency calculations use exact integer cents (`amount_cents`) or fixed-point decimal, preventing float rounding errors.
3. **Execution Speed**: Full test suite completes in under 5 seconds using in-memory SQLite and ASGI in-process test client.
