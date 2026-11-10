"""Adversarial Stress Test Suite for M10 Storage Persistence and Database Synchronization.

Empirically challenges:
1. Rapid consecutive mutations: 50+ transactions rapidly inserted and verified in persistent DB.
2. High-concurrency multithreaded mutations: 10 concurrent threads executing 100 writes total.
3. Multi-cycle container scale-to-zero cold-start restarts with full /tmp wipe.
4. Abrupt container kill / SIGKILL simulation without graceful lifespan shutdown.
5. Persistent DB integrity check (PRAGMA integrity_check == ok, foreign_key_check clean).
6. Journal mode verification (journal_mode == DELETE) and zero orphaned -wal / -shm files.
7. Rollback isolation ensuring failed transactions do not dirty persistent storage.
8. Read-only operation purity ensuring zero write I/O amplification on persistent mount.
9. Adversarial Bug Reproduction: Production Cloud Run environment discrepancy where
   DATABASE_PATH="/app/data/assistant.db" results in task data loss upon transaction sync.
"""

import os
import shutil
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database.connection import (
    DatabaseManager,
    restore_database,
    seed_default_accounts_for_user,
    set_default_manager,
)
from app.api.finance_router import set_finance_service
from app.api.task_router import set_task_service
from app.main import app


@pytest.fixture(autouse=True)
def cleanup_default_manager():
    """Ensure singleton manager and service caches are clean before and after each adversarial test."""
    set_default_manager(None)
    set_finance_service(None)
    set_task_service(None)
    yield
    set_default_manager(None)
    set_finance_service(None)
    set_task_service(None)


def test_rapid_consecutive_mutations_50_plus():
    """Verify 60 rapid consecutive transactions across accounts are 100% synced to persistent DB."""
    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        persistent_db = os.path.join(td, "persistent", "assistant.db")
        active_db = os.path.join(td, "tmp", "assistant.db")
        os.makedirs(os.path.dirname(persistent_db), exist_ok=True)
        os.makedirs(os.path.dirname(active_db), exist_ok=True)

        orig_db_path = settings.database_path
        orig_persistent = settings.persistent_db_path
        settings.database_path = active_db
        settings.persistent_db_path = persistent_db
        os.environ["DATABASE_PATH"] = active_db
        os.environ["PERSISTENT_DB_PATH"] = persistent_db

        try:
            with TestClient(app) as client:
                accounts = ["Efectivo", "Nequi", "Nu", "Daviplata", "Bancolombia"]
                # Rapidly insert 60 transactions
                for i in range(1, 61):
                    acc = accounts[i % len(accounts)]
                    tx_type = "expense" if i % 3 != 0 else "income"
                    amount = 10000 * i
                    resp = client.post(
                        "/api/finance/transactions",
                        json={
                            "user_id": "samuel",
                            "amount_cents": amount,
                            "type": tx_type,
                            "category": "Alimentación" if tx_type == "expense" else "Salario",
                            "description": f"Rapid Transaction #{i}",
                            "account": acc,
                        },
                    )
                    assert resp.status_code in (200, 201), f"Failed to create transaction {i}: {resp.text}"

            # Lifespan closed. Empirically inspect persistent DB directly via independent sqlite3 connection
            assert os.path.exists(persistent_db), "Persistent DB must exist after rapid mutations"
            dst_conn = sqlite3.connect(persistent_db)
            try:
                tx_rows = dst_conn.execute(
                    "SELECT transaction_id, description, amount_cents FROM transactions WHERE user_id = 'samuel';"
                ).fetchall()
                assert len(tx_rows) == 60, f"Expected exactly 60 transactions in persistent DB, found {len(tx_rows)}"

                tx_descriptions = {row[1] for row in tx_rows}
                for i in range(1, 61):
                    assert f"Rapid Transaction #{i}" in tx_descriptions
            finally:
                dst_conn.close()

        finally:
            settings.database_path = orig_db_path
            settings.persistent_db_path = orig_persistent
            if "DATABASE_PATH" in os.environ:
                del os.environ["DATABASE_PATH"]
            if "PERSISTENT_DB_PATH" in os.environ:
                del os.environ["PERSISTENT_DB_PATH"]


def test_concurrent_multithreaded_rapid_mutations_100():
    """Adversarial concurrency test: 10 threads executing 100 total mutations concurrently.

    Verifies threading lock synchronization, zero lock timeouts, and 100% persistent replication.
    """
    with tempfile.TemporaryDirectory() as td:
        persistent_db = os.path.join(td, "persistent", "assistant.db")
        active_db = os.path.join(td, "tmp", "assistant.db")
        os.makedirs(os.path.dirname(persistent_db), exist_ok=True)
        os.makedirs(os.path.dirname(active_db), exist_ok=True)

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        mgr.init_db()
        set_default_manager(mgr)

        with mgr.connection() as conn:
            seed_default_accounts_for_user(conn, "samuel")

        num_threads = 10
        mutations_per_thread = 10

        def worker_fn(thread_id: int):
            for i in range(mutations_per_thread):
                tx_id = f"tx_th_{thread_id}_{i}"
                with mgr.connection() as conn:
                    conn.execute(
                        "INSERT INTO transactions "
                        "(transaction_id, user_id, amount_cents, transaction_type, category, description) "
                        "VALUES (?, 'samuel', 50000, 'expense', 'General', ?);",
                        (tx_id, f"Concurrent TX {thread_id}-{i}"),
                    )

        # Launch concurrent threads
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_fn, t) for t in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        mgr.sync_to_persistent()

        # Verify active database
        with mgr.connection() as conn:
            active_txs = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'tx_th_%';"
            ).fetchone()[0]
            assert active_txs == 100

        # Verify persistent database independently
        dst_conn = sqlite3.connect(persistent_db)
        try:
            pers_txs = dst_conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'tx_th_%';"
            ).fetchone()[0]
            assert pers_txs == 100, f"Expected 100 transactions in persistent DB, got {pers_txs}"
        finally:
            dst_conn.close()


def test_simulated_container_scale_to_zero_and_cold_start_restart():
    """Verify multi-cycle container cold-starts: data creation, wipe /tmp, restart instance, verify 100% restored."""
    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        persistent_db = os.path.join(td, "persistent", "assistant.db")
        active_db = os.path.join(td, "tmp", "assistant.db")
        os.makedirs(os.path.dirname(persistent_db), exist_ok=True)
        os.makedirs(os.path.dirname(active_db), exist_ok=True)

        orig_db_path = settings.database_path
        orig_persistent = settings.persistent_db_path
        settings.database_path = active_db
        settings.persistent_db_path = persistent_db
        os.environ["DATABASE_PATH"] = active_db
        os.environ["PERSISTENT_DB_PATH"] = persistent_db

        try:
            # -------------------------------------------------------------
            # CYCLE 1: First Container Instance
            # -------------------------------------------------------------
            with TestClient(app) as client1:
                # Add 10 transactions across Colombian accounts
                for i in range(1, 11):
                    res_tx = client1.post(
                        "/api/finance/transactions",
                        json={
                            "user_id": "samuel",
                            "amount_cents": 100000 * i,
                            "type": "income",
                            "category": "Salario",
                            "description": f"Cycle1 Income {i}",
                            "account": "Bancolombia",
                        },
                    )
                    assert res_tx.status_code in (200, 201)

            # Instance 1 shuts down (lifespan exit)
            assert os.path.exists(persistent_db)

            # -------------------------------------------------------------
            # SCALE-TO-ZERO: Wipe /tmp completely!
            # -------------------------------------------------------------
            shutil.rmtree(os.path.dirname(active_db))
            assert not os.path.exists(active_db), "Active DB must be completely deleted to simulate scale-to-zero"

            # Reset singletons to simulate fresh container cold-start
            set_default_manager(None)
            set_finance_service(None)
            set_task_service(None)

            # -------------------------------------------------------------
            # CYCLE 2: Second Container Instance (Cold Start)
            # -------------------------------------------------------------
            with TestClient(app) as client2:
                # Verify transactions restored
                res_txs = client2.get("/api/finance/transactions?user_id=samuel")
                assert res_txs.status_code == 200
                txs_data = res_txs.json()
                assert len(txs_data) == 10, f"Expected 10 restored transactions, got {len(txs_data)}"

                # Verify accounts and balance restored (sum of 100k * 1..10 = 5,500,000 cents)
                res_acc = client2.get("/api/finance/accounts?user_id=samuel")
                assert res_acc.status_code == 200
                acc_payload = res_acc.json()
                accounts_list = acc_payload.get("accounts", acc_payload) if isinstance(acc_payload, dict) else (
                    acc_payload
                )
                accounts = {a["name"]: a["balance_cents"] for a in accounts_list}
                assert accounts.get("Bancolombia") == 5500000, "Bancolombia balance must be restored exactly"

                # Add 5 more transactions in Cycle 2
                for i in range(11, 16):
                    res = client2.post(
                        "/api/finance/transactions",
                        json={
                            "user_id": "samuel",
                            "amount_cents": 50000,
                            "type": "expense",
                            "category": "Alimentación",
                            "description": f"Cycle2 Expense {i}",
                            "account": "Nequi",
                        },
                    )
                    assert res.status_code in (200, 201)

            # Instance 2 shuts down
            # -------------------------------------------------------------
            # SCALE-TO-ZERO AGAIN: Wipe /tmp completely a second time!
            # -------------------------------------------------------------
            shutil.rmtree(os.path.dirname(active_db))
            assert not os.path.exists(active_db)

            set_default_manager(None)
            set_finance_service(None)
            set_task_service(None)

            # -------------------------------------------------------------
            # CYCLE 3: Third Container Instance (Cold Start 2)
            # -------------------------------------------------------------
            with TestClient(app) as client3:
                res_all_txs = client3.get("/api/finance/transactions?user_id=samuel")
                assert res_all_txs.status_code == 200
                all_txs = res_all_txs.json()
                assert len(all_txs) == 15, f"Expected 15 accumulated transactions across cycles, got {len(all_txs)}"

                res_summary = client3.get("/api/finance/summary?user_id=samuel")
                assert res_summary.status_code == 200
                assert res_summary.json()["income_cents"] == 5500000
                assert res_summary.json()["expense_cents"] == 250000

        finally:
            settings.database_path = orig_db_path
            settings.persistent_db_path = orig_persistent
            if "DATABASE_PATH" in os.environ:
                del os.environ["DATABASE_PATH"]
            if "PERSISTENT_DB_PATH" in os.environ:
                del os.environ["PERSISTENT_DB_PATH"]


def test_abrupt_crash_simulation_ungraceful_sigkill():
    """Verify that if the container abruptly crashes (SIGKILL / OOM without lifespan shutdown),

    mutations committed prior to the crash are already synced to persistent storage due to sync_on_commit.
    """
    with tempfile.TemporaryDirectory() as td:
        persistent_db = os.path.join(td, "persistent", "assistant.db")
        active_db = os.path.join(td, "tmp", "assistant.db")
        os.makedirs(os.path.dirname(persistent_db), exist_ok=True)
        os.makedirs(os.path.dirname(active_db), exist_ok=True)

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        mgr.init_db()

        with mgr.connection() as conn:
            seed_default_accounts_for_user(conn, "crash_test_user")

        # Perform 25 committed mutations
        for i in range(1, 26):
            with mgr.connection() as conn:
                conn.execute(
                    "INSERT INTO transactions "
                    "(transaction_id, user_id, amount_cents, transaction_type, category, description) "
                    "VALUES (?, 'crash_test_user', 10000, 'expense', 'General', ?);",
                    (f"crash_tx_{i}", f"Pre-crash Tx {i}"),
                )

        # SIMULATE SUDDEN UNGRACEFUL CRASH:
        # DO NOT call mgr.sync_to_persistent()!
        # DO NOT call mgr.close()!
        # Immediately destroy the active directory
        shutil.rmtree(os.path.dirname(active_db))
        assert not os.path.exists(active_db)

        # Restart fresh instance pointing to the same persistent DB
        restored_active = os.path.join(td, "tmp_restored", "assistant.db")
        restored = restore_database(persistent_db, restored_active)
        assert restored is True, "Must successfully restore from persistent DB"

        restored_mgr = DatabaseManager(
            db_path=restored_active,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        with restored_mgr.connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE user_id = 'crash_test_user';"
            ).fetchone()[0]
            assert count == 25, f"All 25 pre-crash committed mutations must survive! Found {count}"


def test_persistent_db_integrity_delete_journal_and_zero_orphaned_files():
    """Verify PRAGMA integrity_check == ok, journal_mode == DELETE, and zero orphaned -wal / -shm files."""
    with tempfile.TemporaryDirectory() as td:
        persistent_dir = os.path.join(td, "persistent_storage")
        persistent_db = os.path.join(persistent_dir, "assistant.db")
        active_db = os.path.join(td, "tmp", "assistant.db")
        os.makedirs(persistent_dir, exist_ok=True)

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        mgr.init_db()

        with mgr.connection() as conn:
            seed_default_accounts_for_user(conn, "samuel")

        # Execute 50 mutations creating accounts and transactions
        for i in range(1, 51):
            with mgr.connection() as conn:
                conn.execute(
                    "INSERT INTO transactions "
                    "(transaction_id, user_id, amount_cents, transaction_type, category, description) "
                    "VALUES (?, 'samuel', 1000, 'expense', 'General', ?);",
                    (f"integ_tx_{i}", f"Integrity Tx {i}"),
                )

        mgr.sync_to_persistent()
        mgr.close()

        # 1. Inspect the persistent storage directory
        pers_files = os.listdir(persistent_dir)
        for fname in pers_files:
            assert not fname.endswith("-wal"), f"Orphaned WAL file found on persistent mount: {fname}"
            assert not fname.endswith("-shm"), f"Orphaned SHM file found on persistent mount: {fname}"
            assert not fname.endswith("-journal"), f"Orphaned journal file found on persistent mount: {fname}"

        assert "assistant.db" in pers_files, "Persistent database file must exist"

        # 2. Check PRAGMA integrity_check
        p_conn = sqlite3.connect(persistent_db)
        try:
            cur = p_conn.execute("PRAGMA integrity_check;")
            integ_res = cur.fetchall()
            assert integ_res == [("ok",)], f"Integrity check failed: {integ_res}"

            # 3. Check PRAGMA foreign_key_check
            fk_cur = p_conn.execute("PRAGMA foreign_key_check;")
            fk_res = fk_cur.fetchall()
            assert fk_res == [], f"Foreign key check violations found: {fk_res}"

            # 4. Check PRAGMA journal_mode
            jm_cur = p_conn.execute("PRAGMA journal_mode;")
            jm_res = jm_cur.fetchone()[0]
            assert jm_res.upper() == "DELETE", (
                f"Persistent journal mode must be DELETE for GCS FUSE compatibility, got {jm_res}"
            )
        finally:
            p_conn.close()


def test_transaction_rollback_isolation():
    """Verify that rolled-back transactions do not dirty or corrupt the persistent DB."""
    with tempfile.TemporaryDirectory() as td:
        persistent_db = os.path.join(td, "persistent", "assistant.db")
        active_db = os.path.join(td, "tmp", "assistant.db")

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        mgr.init_db()

        # Valid commit
        with mgr.connection() as conn:
            conn.execute("INSERT INTO users (user_id, full_name) VALUES ('usr_valid', 'Valid User');")

        # Capture persistent DB size and mtime
        dst_conn = sqlite3.connect(persistent_db)
        row = dst_conn.execute("SELECT full_name FROM users WHERE user_id = 'usr_valid';").fetchone()
        assert row is not None
        dst_conn.close()

        # Attempt a failing transaction (violating UNIQUE constraint)
        with pytest.raises(Exception):
            with mgr.connection() as conn:
                conn.execute("INSERT INTO users (user_id, full_name) VALUES ('usr_rolled_back', 'Should Disappear');")
                conn.execute("INSERT INTO users (user_id, full_name) VALUES ('usr_valid', 'Duplicate Key!');")

        # Verify active DB rolled back
        with mgr.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM users WHERE user_id = 'usr_rolled_back';").fetchone()[0] == 0

        # Verify persistent DB does not have the rolled back record
        dst_conn2 = sqlite3.connect(persistent_db)
        try:
            assert dst_conn2.execute(
                "SELECT COUNT(*) FROM users WHERE user_id = 'usr_rolled_back';"
            ).fetchone()[0] == 0
        finally:
            dst_conn2.close()


def test_read_operations_do_not_trigger_sync():
    """Verify that read-only queries do not cause unnecessary write I/O to the persistent DB."""
    with tempfile.TemporaryDirectory() as td:
        persistent_db = os.path.join(td, "persistent", "assistant.db")
        active_db = os.path.join(td, "tmp", "assistant.db")

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        mgr.init_db()

        with mgr.connection() as conn:
            conn.execute("INSERT INTO users (user_id, full_name) VALUES ('u1', 'Read Tester');")

        initial_mtime = os.stat(persistent_db).st_mtime_ns

        # Execute 50 rapid read queries
        for _ in range(50):
            with mgr.connection() as conn:
                conn.execute("SELECT * FROM users WHERE user_id = 'u1';").fetchall()
                conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()

        final_mtime = os.stat(persistent_db).st_mtime_ns
        assert initial_mtime == final_mtime, "Read queries must not trigger hot backup to persistent DB"


# ============================================================================
# Adversarial Challenge: Empirical Defect Reproduction in Cloud Run Environment
# ============================================================================

def test_adversarial_defect_cloudrun_task_wipe_on_sync():
    """Empirical reproduction of critical defect:

    When deployed to Cloud Run with DATABASE_PATH=/app/data/assistant.db (as set in cloudrun.yaml),
    app.main decouples settings.database_path to /tmp/assistant.db but does not update os.environ["DATABASE_PATH"].
    Consequently, TaskRepository writes directly to /app/data/assistant.db while FinanceService writes to
    /tmp/assistant.db. The subsequent financial transaction hot-backup overwrites /app/data/assistant.db,
    WIPING ALL TASKS!
    """
    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        persistent_mount = os.path.join(td, "app", "data", "assistant.db")
        os.makedirs(os.path.dirname(persistent_mount), exist_ok=True)

        orig_db_path = settings.database_path
        orig_persistent = settings.persistent_db_path

        # Simulate EXACT Cloud Run container environment from deploy/cloudrun.yaml
        os.environ["DATABASE_PATH"] = persistent_mount
        if "PERSISTENT_DB_PATH" in os.environ:
            del os.environ["PERSISTENT_DB_PATH"]

        settings.database_path = persistent_mount
        settings.persistent_db_path = None
        set_default_manager(None)
        set_finance_service(None)
        set_task_service(None)

        try:
            with TestClient(app) as client:
                # 1. Create a task via API
                res_task = client.post(
                    "/api/tasks/",
                    json={"title": "Mission Critical Task", "user_id": "samuel"},
                )
                assert res_task.status_code == 201

                # 2. Create a financial transaction via API
                res_tx = client.post(
                    "/api/finance/transactions",
                    json={
                        "user_id": "samuel",
                        "amount_cents": 50000,
                        "type": "expense",
                        "category": "General",
                        "description": "Lunch with Nequi",
                        "account": "Nequi",
                    },
                )
                assert res_tx.status_code in (200, 201)

            # Container lifespan has shut down (simulating container scale-to-zero)
            # Inspect the persistent volume mount DB
            p_conn = sqlite3.connect(persistent_mount)
            try:
                task_count = p_conn.execute("SELECT COUNT(*) FROM tasks;").fetchone()[0]
                tx_count = p_conn.execute("SELECT COUNT(*) FROM transactions;").fetchone()[0]
            finally:
                p_conn.close()

            # VERIFICATION OF REMEDIATION:
            # Both tasks and transactions must be preserved in persistent storage across sync cycles!
            assert task_count >= 1, (
                f"Tasks must be retained in persistent storage! Found: {task_count}"
            )
            assert tx_count >= 1, "Transactions were preserved in persistent storage"
        finally:
            settings.database_path = orig_db_path
            settings.persistent_db_path = orig_persistent
            if "DATABASE_PATH" in os.environ:
                del os.environ["DATABASE_PATH"]
