# Original User Request

## 2026-11-04T11:36:45Z

Build a fully autonomous cloud-based personal assistant that operates via a Telegram bot for conversational/voice interactions and a lightweight web dashboard for visual finance and task overviews, with zero-cost hosting on cloud free tier services (e.g., Firebase / Cloud Run).

Working directory: ~/teamwork_projects/personal_assistant
Integrity mode: development

## Requirements

### R1. Conversational Agent Core & Natural Language Tool Orchestration
The assistant must parse incoming user messages (text commands and voice notes) in natural language, maintain conversational context, route actions to internal tools (finances, calendar, emails, tasks, search), and return structured, conversational feedback.

### R2. Personal Finance Ledger & Analytical Engine
The system must record user expenses and incomes, classify transactions into budget categories, maintain cumulative balances, and provide on-demand financial summaries, category breakdowns, and spending alerts.

### R3. Email Monitoring & Intelligent Digest
The assistant must integrate with Gmail to monitor unread emails, extract key content, identify high-priority or urgent communications, and generate concise digests and alert notifications.

### R4. Schedule Management, Task Tracking & Outing Research
The assistant must track daily to-do lists with reminder scheduling, query and reserve events on Google Calendar, and execute web research to recommend leisure activities, dining, or outing plans based on user requests.

### R5. Dual User Interface & Free-Tier Cloud Deployment
The system must provide an interactive Telegram bot interface for real-time mobile interaction alongside a lightweight, mobile-friendly web dashboard for visual financial charts and task status, packaged with configuration and instructions for free-tier cloud deployment (Firebase / Cloud Run).

## Acceptance Criteria

### Core & Intent Orchestration
- [ ] Natural language parser correctly identifies and routes user intents (financial entry, reminder, email check, schedule request, plan research) across automated test fixtures.
- [ ] Multi-turn context is retained across consecutive user interactions during conversational flows.

### Financial Management
- [ ] Financial module accurately calculates balances, category totals, and monthly budget aggregations across synthetic test transaction sets.
- [ ] The system validates transaction inputs (amount, category, description) and rejects malformed financial records with informative error messages.

### Google Integrations (Email & Calendar)
- [ ] Email module correctly parses simulated Gmail payloads, filters critical emails, and generates readable summary messages.
- [ ] Calendar integration successfully creates, lists, and checks event conflicts against mock Google Calendar API endpoints.

### User Interfaces & Cloud Packaging
- [ ] Telegram bot webhook handler processes incoming text messages and simulated audio notes, dispatching appropriate replies.
- [ ] Web dashboard builds without errors and renders financial summary charts and task lists.
- [ ] The project contains deployment manifests, environment variable templates (.env.example), and automated deployment scripts targeting free-tier cloud hosting.

### Verification Suite
- [ ] An automated test suite passes with 100% success rate verifying financial calculations, intent dispatching, and integration mocks.

## 2026-11-08T20:32:45Z

Expand Samuel Azuero's autonomous personal assistant with debt and receivable tracking (counterparty, amount, reason, due date), multi-account asset allocation (Efectivo, Nequi, Nu, Daviplata, Bancolombia), recurring subscription tracking with payment dates, account-linked transactions, and publish a sanitized, secure codebase to GitHub under his institutional account.

Working directory: ~/teamwork_projects/personal_assistant
Integrity mode: development

## Requirements

### R1. Debt & Receivable Tracking with Due Dates (Deudas y Cobros)
The assistant must track money owed by the user to others (debts) and money owed to the user by others (receivables/loans). Each record must capture: counterparty name, amount in COP, reason/concept, creation date, due date (fecha límite/pago), payment status (active, partially paid, settled), and the linked account used for disbursement or settlement.

### R2. Multi-Account Balance & Asset Allocation (Efectivo y Cuentas Digitales)
The assistant must manage distinct balances across physical cash and digital accounts:
- Default accounts: Efectivo, Nequi, Nu, Daviplata, Bancolombia (with capability to add additional accounts).
- Transactions (expenses, incomes, loans, debt payments) must debit or credit the designated account balance.
- Inter-account transfers (e.g., withdrawing cash from Bancolombia to Efectivo, or transferring from Nequi to Nu) must adjust respective account balances while preserving total net worth.

### R3. Recurring Subscriptions & Payment Calendar (Suscripciones y Vencimientos)
The assistant must track recurring commitments and subscriptions (e.g., Netflix, Spotify, gym, university fees) including service name, cost in COP, billing cycle / monthly renewal date, default payment account, and automated reminder alerts prior to upcoming due dates.

### R4. Conversational Natural Language & Web Dashboard Extensions
Natural language intent parsing and conversational routing in Telegram must support:
- Recording and querying debts and loans (e.g., "le presté 50k a Juan desde Nequi para el almuerzo, me paga el viernes").
- Recording and checking account balances and transfers (e.g., "pasé 100 mil de Bancolombia a Nequi", "cuánta plata tengo en efectivo y en Nu?").
- Querying upcoming payment dates and subscriptions.
- The web dashboard (/) must display interactive visual cards for account balances, active debts/receivables with due date badges, and subscription calendars.

### R5. Secrets Sanitization & Secure GitHub Publication
The project repository must be initialized and pushed to GitHub under the user's institutional account (est.samuel.azuero@unimilitar.edu.co).
- Rigorously sanitize the codebase: .env, SQLite databases (*.db), deploy/cloud_run_env.yaml, .venv, and cache directories must be completely excluded via .gitignore.
- Provide an updated .env.example with clear, safe placeholders for all required environment variables.
- Execute git initialization, initial commit with clean code, remote association, and push via the user's GitHub Personal Access Token (PAT).

## Acceptance Criteria

### Debt & Receivables Management
- [ ] Users can record debts owed to others and loans granted to others with counterparty, amount in COP, reason, due date, and payment account via Telegram and Web UI.
- [ ] Recording a loan or debt settlement immediately debits/credits the linked account.
- [ ] Users can query outstanding debts, upcoming collections, and mark debts as partially or fully settled.

### Multi-Account Asset Allocation
- [ ] System accurately maintains individual balances for Efectivo, Nequi, Nu, Daviplata, and Bancolombia.
- [ ] Expense and income entries update the specified account balance.
- [ ] Inter-account transfers update source and destination balances correctly with zero net wealth loss.

### Subscriptions & Due Dates
- [ ] System tracks recurring subscriptions with cost, renewal date, and payment method.
- [ ] Querying upcoming payments lists impending debts, loan collections, and subscription renewals sorted by due date.

### Security & GitHub Repository
- [ ] Git repository contains zero secrets, tokens, API keys, passwords, or personal credentials in tracked history or committed files.
- [ ] .gitignore securely ignores .env, SQLite DB files, deploy/cloud_run_env.yaml, virtual environments, and cache directories.
- [ ] Codebase is successfully pushed to the user's GitHub repository.

### Verification Suite
- [ ] 100% automated test pass rate (pytest) including new unit and integration tests covering debt tracking, account transfers, subscription dates, and secret-free repo verification.
