-- SQLite Schema: Autonomous Cloud-Based Personal Assistant
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. Users / Channels
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    telegram_chat_id TEXT UNIQUE,
    full_name TEXT,
    timezone TEXT DEFAULT 'UTC',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Conversational Sessions (Multi-turn state tracking)
CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    active_intent TEXT,
    context_json TEXT DEFAULT '{}',
    turn_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 3. Financial Transactions Ledger (R2)
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,          -- Stored as integer cents to eliminate floating-point drift
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('income', 'expense')),
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    idempotency_key TEXT UNIQUE,
    account_id TEXT,
    account_name TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(user_id, category);
CREATE INDEX IF NOT EXISTS idx_transactions_idempotency ON transactions(user_id, idempotency_key);

-- 4. Monthly Category Budgets (R2)
CREATE TABLE IF NOT EXISTS budgets (
    budget_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    monthly_limit_cents INTEGER NOT NULL,
    period TEXT NOT NULL,                  -- Format: 'YYYY-MM'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, category, period),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_budgets_user_period ON budgets(user_id, period);

-- 5. Tasks and Reminders (R4)
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
    due_date TIMESTAMP,
    is_completed BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, is_completed, due_date);

-- 6. Cached Calendar Events & Synced Items (R4)
CREATE TABLE IF NOT EXISTS calendar_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    external_calendar_id TEXT,             -- Google Calendar event ID
    summary TEXT NOT NULL,
    description TEXT,
    location TEXT,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    is_all_day BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_calendar_user_times ON calendar_events(user_id, start_time, end_time);

-- 7. Email Digests & Monitored Messages (R3)
CREATE TABLE IF NOT EXISTS email_messages (
    message_id TEXT PRIMARY KEY,           -- Gmail message ID
    user_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    snippet TEXT,
    is_urgent BOOLEAN DEFAULT 0,
    category TEXT DEFAULT 'general',
    received_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_email_user_urgent ON email_messages(user_id, is_urgent, received_at);

-- 8. Accounts & Digital Wallets (R2)
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,                      -- 'Efectivo', 'Nequi', 'Nu', 'Daviplata', 'Bancolombia'
    account_type TEXT NOT NULL DEFAULT 'digital_wallet', -- 'cash', 'digital_wallet', 'bank_account', 'savings'
    balance_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'COP',
    color TEXT,
    icon TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_accounts_user_active ON accounts(user_id, is_active);

-- 9. Inter-Account Transfers (R2)
CREATE TABLE IF NOT EXISTS transfers (
    transfer_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    from_account_id TEXT NOT NULL,
    to_account_id TEXT NOT NULL,
    from_account_name TEXT,
    to_account_name TEXT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    fee_cents INTEGER NOT NULL DEFAULT 0 CHECK (fee_cents >= 0),
    description TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (from_account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT,
    FOREIGN KEY (to_account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_transfers_user_date ON transfers(user_id, timestamp);

-- 10. Debts & Receivables Ledger (R1)
CREATE TABLE IF NOT EXISTS debts (
    debt_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    debt_type TEXT NOT NULL CHECK (debt_type IN ('debt', 'receivable')),
    counterparty TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    remaining_cents INTEGER NOT NULL CHECK (remaining_cents >= 0),
    reason TEXT NOT NULL,
    due_date TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'partially_paid', 'settled', 'cancelled')),
    account_id TEXT,
    account_name TEXT,
    paid_amount_cents INTEGER NOT NULL DEFAULT 0 CHECK (paid_amount_cents >= 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    settled_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_debts_user_status ON debts(user_id, status, due_date);
CREATE INDEX IF NOT EXISTS idx_debts_counterparty ON debts(user_id, counterparty);

-- 11. Debt & Receivable Payments / Settlements (R1)
CREATE TABLE IF NOT EXISTS debt_payments (
    payment_id TEXT PRIMARY KEY,
    debt_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    account_id TEXT,
    account_name TEXT,
    notes TEXT,
    payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (debt_id) REFERENCES debts(debt_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_debt_payments_debt ON debt_payments(debt_id, payment_date);

-- 12. Recurring Subscriptions (R3)
CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    billing_cycle TEXT NOT NULL DEFAULT 'monthly' CHECK (billing_cycle IN ('weekly', 'monthly', 'quarterly', 'semiannual', 'annual', 'yearly')),
    billing_day INTEGER CHECK (billing_day BETWEEN 1 AND 31),
    next_payment_date DATE NOT NULL,
    account_id TEXT,
    account_name TEXT,
    category TEXT DEFAULT 'Entertainment',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled')),
    reminder_days_before INTEGER DEFAULT 3,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status ON subscriptions(user_id, status, next_payment_date);

