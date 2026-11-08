# 🤖 Autonomous Cloud-Based Personal Assistant

A multi-channel, zero-cost operational personal assistant combining conversational AI, voice note processing, personal finance ledger analytics, email intelligence, calendar management, and leisure research.

Operates seamlessly via dual interfaces:
1. **Interactive Telegram Bot** for mobile messaging, voice notes, and fast conversational commands.
2. **Modern Web Dashboard** single-page application (SPA) for real-time visual KPI cards, financial charts, transaction ledgers, task management, and intelligence widgets.

---

## 🌟 Key Architecture & Features

```
+----------------------------------------------------------------------------------------------------+
|                                    CLIENT INTERFACES & CHANNELS                                    |
|                                                                                                    |
|       +------------------------------------+          +------------------------------------+       |
|       |     Telegram Bot (Text & Voice)    |          |   Responsive Web Dashboard (SPA)   |       |
|       +-----------------+------------------+          +-----------------+------------------+       |
+-------------------------|-----------------------------------------------|--------------------------+
                          | HTTPS POST Webhook                            | REST API & Static Mount
                          v                                               v
+----------------------------------------------------------------------------------------------------+
|                                      FASTAPI APPLICATION CORE                                      |
|                                                                                                    |
|   /api/webhook/telegram     /api/finance/*     /api/tasks/*     /health, /ready     /static        |
|            |                      |                  |                 |               |           |
|            v                      v                  v                 v               |           |
|   +-------------------+  +----------------+  +---------------+  +--------------+       |           |
|   |  Agent / Router   |  | Finance Ledger |  | Task Tracker  |  | System Health|       |           |
|   +-------------------+  +----------------+  +---------------+  +--------------+       |           |
|            |                     \                   /                 |               |           |
|            v                      \                 /                  |               |           |
|   +-------------------+            v               v                   v               v           |
|   | Services & Mocks  | --->       SQLite 3 Embedded Database (WAL Mode Enabled)                   |
|   | (STT, Gmail, Cal) |                                                                            |
|   +-------------------+                                                                            |
+----------------------------------------------------------------------------------------------------+
```

### Feature Inventory Summary
- **R1: Conversational Agent Core & Tool Orchestration**: Multi-turn dialogue buffer, slot filling, voice note OGG/Opus transcription via high-fidelity STT adapter.
- **R2: Personal Finance Ledger & Analytics**: Double-precision integer-cent storage, zero floating-point drift, budget threshold alerts, category breakdowns, and transaction voiding.
- **R3: Email Monitoring & Priority Digest**: RFC 2822 MIME decoding, urgency scoring (0-100), automated high-priority digest generation, and noise filtering.
- **R4: Schedule Management & Leisure Research**: Google Calendar v3 interval conflict detection ($\max(s_1,s_2) < \min(e_1,e_2)$), to-do list tracking, and curated outing recommendations.
- **R5: Dual User Interface & Free-Tier Cloud Packaging**: Responsive mobile-first dashboard (Chart.js), multi-stage minimal Dockerfile (<140MB), scale-to-zero Cloud Run deployment automation.

---

## ⚡ Zero-Cost Cloud Free-Tier Deployment (Google Cloud Run)

Google Cloud Run provides a permanent free-tier allowance that supports 24/7 autonomous operation with **$0.00 monthly cost**:
- **2,000,000 invocations / month** (System uses ~10,000 - 30,000)
- **180,000 vCPU-seconds / month** (Scale-to-zero keeps usage under 5.5%)
- **360,000 GiB-seconds memory / month** (256Mi container footprint)
- **1 GiB network egress / month**

### Automated Cloud Run Deployment

1. Make sure you have the Google Cloud SDK installed and authenticated:
   ```bash
   gcloud auth login
   gcloud config set project <YOUR_GCP_PROJECT_ID>
   ```

2. Run the automated deployment script:
   ```bash
   ./deploy/deploy_cloud_run.sh
   ```

3. The script will:
   - Build a multi-stage Docker container using Google Cloud Build (free tier: 120 mins/day).
   - Deploy the container to Cloud Run with `--min-instances 0`, `--memory 256Mi`, and `--cpu 1`.
   - Output your public HTTPS service URL (e.g. `https://personal-assistant-xyz.run.app`).

### Declarative Deployment via Knative Manifest
Alternatively, apply the declarative manifest:
```bash
gcloud run services replace deploy/cloudrun.yaml --region us-central1
```

---

## 🚀 Local Quickstart Guide

### 1. Prerequisites
- Python 3.12+
- `pip` and virtual environment support (`venv`)

### 2. Setup Virtual Environment & Dependencies
```bash
# Clone or navigate to the repository
cd personal_assistant

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3. Configure Environment Variables
Copy the template and inspect settings:
```bash
cp .env.example .env
```
By default, `MOCK_SERVICES=true` is enabled, allowing all features (voice transcription, Gmail polling, Google Calendar, and web research) to function offline without external API keys.

### 4. Run the Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Visit the services in your browser:
- **Web Dashboard**: [http://localhost:8080/](http://localhost:8080/)
- **Interactive Swagger Docs**: [http://localhost:8080/docs](http://localhost:8080/docs)
- **Health Check**: [http://localhost:8080/health](http://localhost:8080/health)
- **Readiness Probe**: [http://localhost:8080/ready](http://localhost:8080/ready)

---

## 📱 Telegram Bot Setup & Webhook Registration

1. **Create Bot**: Message `@BotFather` on Telegram, create a new bot, and receive your `TELEGRAM_BOT_TOKEN`.
2. **Generate Secret Token**: Create a random string (e.g. `openssl rand -hex 16`) for `TELEGRAM_SECRET_TOKEN`.
3. **Set Webhook**:
   ```bash
   curl -F "url=https://<YOUR_CLOUD_RUN_URL>/api/webhook/telegram" \
        -F "secret_token=<YOUR_SECRET_TOKEN>" \
        "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook"
   ```
4. **Interact**: Send messages or voice notes to your bot:
   - *"Spent $45 on groceries"*
   - *"What is my balance?"*
   - *"Check my emails"*
   - *"Schedule lunch with Sarah tomorrow at 1pm"*
   - *"Remind me to file quarterly taxes by Friday"*
   - *"Find good Italian restaurants in downtown"*

---

## 📊 Web Dashboard Capabilities

The web dashboard is an ultra-lightweight Single Page Application (SPA) requiring zero frontend compilation or node_modules:
- **Financial KPI Cards**: Instant visualization of Net Balance, Total Income, Total Expenses, and Savings Rate.
- **Interactive Financial Charts**:
  - Category spending breakdown donut chart (Chart.js).
  - Income vs Expenses monthly trend comparison chart.
- **Live Ledger Table**: Filter transactions by type, view date and category badges, and void/delete entries.
- **Quick Entry Modal**: Native accessible `<dialog>` component for rapid recording of expenses or incomes.
- **Task & Schedule Board**: Filter tasks by pending/completed status, toggle completion with real-time sync, and add new to-do items.
- **Urgent Email Digest Widget**: Displays high-priority emails flagged by urgency scoring.
- **Outing Recommendations Widget**: Curated leisure picks with ratings, price tiers, and locations.

---

## 📡 REST API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the web dashboard SPA (`index.html`) |
| `GET` | `/health` | Liveness health probe (`{"status": "healthy"}`) |
| `GET` | `/ready` | Readiness probe verifying SQLite connectivity |
| `POST` | `/api/webhook/telegram` | Ingests Telegram Bot updates and voice notes |
| `GET` | `/api/finance/summary` | Net balance, total income, expenses, and savings |
| `GET` | `/api/finance/transactions` | Query recent transactions with pagination & filters |
| `GET` | `/api/finance/categories` | Spending aggregated by budget category |
| `POST` | `/api/finance/transactions` | Record a new expense or income transaction |
| `DELETE` | `/api/finance/transactions/{id}` | Void / delete an existing transaction |
| `GET` | `/api/tasks` | List to-do tasks filtered by status or priority |
| `POST` | `/api/tasks` | Create a new task with due date and priority |
| `PATCH` | `/api/tasks/{id}` | Update task title, status, or priority |
| `DELETE` | `/api/tasks/{id}` | Delete a task |
| `GET` | `/api/email/digest` | Returns executive digest of urgent emails |
| `GET` | `/api/research/outings` | Returns curated dining and leisure recommendations |

---

## 🧪 Testing & Verification

Run the comprehensive unit test suite:
```bash
pytest tests/unit/ -v
```

Run linting checks:
```bash
flake8 app/ tests/unit/ --max-line-length=120
```

---

## 🛡️ License & Authorship

Developed for the Autonomous Personal Assistant project under the MIT License.
