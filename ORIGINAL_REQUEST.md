# Original User Request

## 2026-11-09T04:38:02Z

This is a single self-contained fix; keep it small and focused.

Fix the interactive modal dialogs (`<dialog>`) and form submissions on the Autonomous Personal Assistant web dashboard so modals do not prematurely close upon click or tap, and add account selection to the web transaction modal so transactions immediately adjust the designated account balance (`Efectivo`, `Nequi`, `Nu`, `Daviplata`, `Bancolombia`) and synchronize with the active user.

Working directory: ~/teamwork_projects/personal_assistant
Integrity mode: development

## Requirements

### R1. Modal Dialog Stability & Event Target Isolation
Fix backdrop and event handling across all dialog modals in `app/static/js/app.js` and `app/static/index.html`:
- Modals (`#transaction-dialog`, `#task-dialog`, `#transfer-dialog`, `#debt-dialog`, `#settle-dialog`, `#sub-dialog`) must NOT close when clicking or tapping inside the modal, clicking input fields, interacting with select dropdown options, or scrolling on mobile.
- Close modals only when the cancel button, close (`×`) button is clicked, or when the user directly clicks the backdrop (`e.target === dialog`).
- Prevent default form behavior and ensure forms submit smoothly without unintended window navigation or premature closing.

### R2. Account Selection in Web Transaction Modal & API Integration
Update the Web Transaction creation workflow:
- In `app/static/index.html`, add an account selector (`Efectivo`, `Nequi`, `Nu`, `Daviplata`, `Bancolombia`) to `#transaction-form`.
- In `app/static/js/app.js`, include the selected account in the `POST /api/finance/transactions` payload.
- In `app/api/finance_router.py`, update `TransactionCreateRequest` to accept `account` / `account_name`, and in `_handle_create_transaction`, adjust the balance of the designated account in `AccountService` and resolve `get_effective_user_id()`.
- Update `_handle_list_transactions`, `get_summary`, and `get_categories` to consistently resolve `get_effective_user_id()` so dashboard cards immediately reflect transactions.

### R3. Quality Assurance & Regression Verification
- Add automated pytest unit and integration tests verifying:
  1. Transaction creation via API with linked account properly adjusts account balances.
  2. Effective user fallback across transactions and summary endpoints.
- Ensure 100% of tests in `tests/` pass without regression.

### R4. Production Deployment & Cloud Verification
- Rebuild container image via Cloud Build and deploy the revision to Google Cloud Run (`personal-assistant`).
- Verify endpoints (`/health`, `/api/finance/accounts`, `/api/finance/transactions`) return HTTP 200 on Cloud Run.

## Acceptance Criteria

### Modal Stability
- [ ] Users can open any modal on desktop or mobile, click inputs, and select dropdown options without the modal abruptly closing.
- [ ] Clicking the modal backdrop or cancel button closes the dialog cleanly without full page reloads.

### Web Transaction & Balance Synchronization
- [ ] Users can select a destination or source account (`Nequi`, `Nu`, `Efectivo`, etc.) when creating a transaction from the web dashboard.
- [ ] Saving a transaction from the web UI updates the transaction list and immediately credits or debits the selected account's balance card.

### Verification Suite & Deployment
- [ ] 100% automated test pass rate with pytest across all tests.
- [ ] Successful deployment to Cloud Run with live service verification.

## 2026-11-09T16:10:04Z

Upgrade Samuel Azuero's autonomous personal assistant with persistent cloud storage across Cloud Run deployments (preventing data wipe), direct account deposits/withdrawals, debt modifications and installment plans (cuotas), geo-aware sector search for restaurants and places with direct Google Maps links, and automated GitHub synchronization.

Working directory: ~/teamwork_projects/personal_assistant
Integrity mode: development

## Requirements

### R1. Cloud Run Persistent Storage (Zero Data Loss Across Revisions)
The system must guarantee permanent persistence of all database records (accounts, transactions, debts, tasks, sessions) across Cloud Run deployments, container scale-to-zero, and restarts:
- Configure and attach a Google Cloud Storage persistent volume (e.g., `gs://personal-assistant-data-435709049712` mounted at `/app/data` in Cloud Run gen2) or automated GCS SQLite bidirectional synchronization.
- Ensure `deploy/deploy_cloud_run.sh` provisions and binds this persistent storage so future code updates and redeployments never reset the database or erase existing user tasks and balances.

### R2. Direct Account Balance Operations (Deposits & Withdrawals)
The assistant must allow users to directly add or subtract money from any account without requiring an inter-account transfer:
- Natural Language & Bot: Parse phrases like *"añadir 50 mil a Nequi"*, *"meter 100k a Bancolombia"*, *"retirar 30k de Daviplata"*, *"quitar 20 mil de Efectivo"*, adjusting the designated account balance and total net worth immediately.
- Web Dashboard: Add interactive actions/modals directly on account cards to deposit or withdraw funds with a custom concept/note, updating balances and charts in real time.

### R3. Advanced Debt Management: Modifications & Installment Plans (Cuotas)
The system must support editing existing debts and managing installment structures:
- Allow updating debt records (changing amount, counterparty, due date, concept, or status).
- Support installment loans and debts (*cuotas*): track total number of installments, installment amount in COP, payment frequency (e.g., monthly), next installment due date, and remaining installments.
- Enable partial installment settlements (paying off one or more installments) that update both the remaining debt balance and the linked account.
- Expose installment details and modification controls in both Telegram bot interactions and the Web Dashboard.

### R4. Geo-Aware Sector & Restaurant Search with Interactive Map Links
The assistant must provide location-accurate restaurant and leisure recommendations tailored to the specific sector, neighborhood, or city specified by the user:
- Implement hybrid geospatial search utilizing OpenStreetMap / Nominatim and dynamic search (zero API costs), returning authentic venues for requested Colombian sectors (e.g., *"restaurantes en Chapinero"*, *"lugares para cenar en Usaquén"*, *"planes en Parque 93"*, or coordinates from Telegram location shares).
- Each recommendation must include: venue name, cuisine/category, address, approximate price tier, rating, and a direct Google Maps navigation URL (`https://www.google.com/maps/search/?api=1&query=...`).
- Display recommendation cards on the web dashboard and format rich responses in Telegram.

### R5. Task Due Reminders & Automated GitHub Synchronization
- Ensure task due date checks and reminder alerts function reliably without being lost to container resets.
- Commit and push all project changes to GitHub (`https://github.com/SamuelAzuero/personal-assistant.git`) under Samuel's account with strict secret sanitization (zero exposed API keys or tokens).

## Acceptance Criteria

### Storage Persistence
- [ ] Database data (accounts, balances, debts, tasks) is retained across Cloud Run deployments and container restarts without data loss.

### Direct Balance Operations
- [ ] Users can add or withdraw funds to/from specific accounts (`Efectivo`, `Nequi`, `Nu`, `Daviplata`, `Bancolombia`) via Telegram and Web UI without needing a transfer.
- [ ] Account balances and net worth update immediately upon direct deposit or withdrawal.

### Debt Installments & Editing
- [ ] Debts can be created with installment plans (cuotas) and edited with new amounts or due dates.
- [ ] Users can record installment payments, reducing the remaining installments and total balance accurately.

### Geo-Aware Place Search
- [ ] Searching for restaurants or outings in a specific sector returns real local establishments with clickable Google Maps navigation links.

### Quality Assurance & Git Traceability
- [ ] 100% automated test pass rate with pytest across all existing and new test suites.
- [ ] Complete codebase is pushed to the GitHub repository with clean history and zero leaked credentials.
- [ ] Cloud Run service is active, persistent, and responding with HTTP 200.
