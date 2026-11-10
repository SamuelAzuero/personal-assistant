"""Empirical adversarial stress tests for Milestone M10:
Cold-start initialization, read-heavy sync bypass, rollback safety, and deployment configurations.
"""

import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database.connection import (
    DatabaseManager,
    backup_database,
    restore_database,
    set_default_manager,
)
from app.main import app as main_app


def test_cold_start_nonexistent_persistent_db():
    """Empirical Test 1: Verify clean cold start when persistent DB does not exist.

    Ensures:
    1. restore_database returns False without raising an error.
    2. init_db() creates all schema tables from schema.sql cleanly.
    3. sync_to_persistent() automatically creates the persistent DB file with DELETE journal mode.
    4. /ready endpoint returns 200 HTTP OK.
    """
    with tempfile.TemporaryDirectory() as td:
        persistent_path = os.path.join(td, "mount", "data", "assistant.db")
        active_path = os.path.join(td, "scratch", "assistant.db")

        # Confirm non-existence
        assert not os.path.exists(persistent_path)
        assert not os.path.exists(active_path)

        # Attempt restore from non-existent file
        restored = restore_database(persistent_path, active_path)
        assert restored is False
        assert not os.path.exists(active_path)

        # Initialize manager with non-existent persistent path
        manager = DatabaseManager(
            db_path=active_path,
            persistent_db_path=persistent_path,
            sync_on_commit=True,
        )
        # Execute schema init
        manager.init_db()

        # Verify active DB created
        assert os.path.exists(active_path)
        # Verify persistent DB created and synced
        assert os.path.exists(persistent_path)
        assert os.path.getsize(persistent_path) > 0

        # Check all core tables exist in both active and persistent DB
        expected_tables = {
            "users",
            "conversation_sessions",
            "transactions",
            "budgets",
            "tasks",
            "calendar_events",
            "email_messages",
            "accounts",
            "transfers",
            "debts",
            "debt_payments",
            "subscriptions",
        }
        for path_to_check in [active_path, persistent_path]:
            conn = sqlite3.connect(path_to_check)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
            for table in expected_tables:
                assert table in tables, f"Expected table '{table}' missing in {path_to_check}"

            # Persistent DB must be in DELETE journal mode (FUSE compatibility)
            if path_to_check == persistent_path:
                mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
                assert mode.upper() == "DELETE"
            conn.close()

        # Verify readiness probe succeeds with this manager
        set_default_manager(manager)
        try:
            with TestClient(main_app) as client:
                resp = client.get("/ready")
                assert resp.status_code == 200
                assert resp.json() == {"status": "ready"}
        finally:
            set_default_manager(None)


def test_cold_start_zero_byte_corrupted_persistent_file():
    """Verify that a 0-byte or corrupted persistent file is safely handled on cold start."""
    with tempfile.TemporaryDirectory() as td:
        persistent_path = os.path.join(td, "mount", "data", "assistant.db")
        active_path = os.path.join(td, "scratch", "assistant.db")
        os.makedirs(os.path.dirname(persistent_path), exist_ok=True)
        # Touch 0-byte file
        Path(persistent_path).touch()
        assert os.path.getsize(persistent_path) == 0

        # restore_database should gracefully return False without crashing
        assert restore_database(persistent_path, active_path) is False

        # init_db() should overwrite the empty file with a valid schema
        manager = DatabaseManager(
            db_path=active_path,
            persistent_db_path=persistent_path,
            sync_on_commit=True,
        )
        manager.init_db()

        assert os.path.exists(persistent_path)
        assert os.path.getsize(persistent_path) > 0

        # Verify persistent DB is readable SQLite
        conn = sqlite3.connect(persistent_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        assert len(tables) >= 12
        conn.close()


def test_read_heavy_workload_zero_sync_overhead():
    """Empirical Test 2: Verify read-heavy workloads never trigger hot-backup sync overhead.

    Executes 1,000 read queries and verifies:
    1. _sync_conn_to_persistent is never called (count = 0).
    2. backup_database is never called (count = 0).
    3. Persistent DB file mtime and size remain completely untouched.
    4. Execution is sub-millisecond fast.
    """
    with tempfile.TemporaryDirectory() as td:
        persistent_path = os.path.join(td, "mount", "assistant.db")
        active_path = os.path.join(td, "scratch", "assistant.db")

        manager = DatabaseManager(
            db_path=active_path,
            persistent_db_path=persistent_path,
            sync_on_commit=True,
        )
        manager.init_db()

        # Seed test data
        with manager.connection() as conn:
            conn.execute("INSERT INTO users (user_id, full_name) VALUES ('u1', 'User 1');")
            conn.execute(
                "INSERT INTO accounts (account_id, user_id, name, account_type, balance_cents, currency) "
                "VALUES ('acc1', 'u1', 'Nequi', 'digital_wallet', 100000, 'COP');"
            )
            for i in range(10):
                conn.execute(
                    "INSERT INTO tasks (task_id, user_id, title, is_completed) VALUES (?, 'u1', ?, 0);",
                    (f"task_{i}", f"Task {i}"),
                )

        # Persistent DB now has seed data. Record timestamp and file size.
        initial_mtime = os.path.getmtime(persistent_path)
        initial_size = os.path.getsize(persistent_path)

        # Patch both _sync_conn_to_persistent and backup_database to detect any calls
        with patch.object(
            manager, "_sync_conn_to_persistent", wraps=manager._sync_conn_to_persistent
        ) as spy_sync, patch(
            "app.database.connection.backup_database", wraps=backup_database
        ) as spy_backup:

            start_time = time.perf_counter()

            # Execute 1,000 read queries across various patterns
            for i in range(1000):
                with manager.connection() as conn:
                    if i % 4 == 0:
                        cur = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id = 'u1';")
                        assert cur.fetchone()[0] == 10
                    elif i % 4 == 1:
                        cur = conn.execute("SELECT balance_cents FROM accounts WHERE account_id = 'acc1';")
                        assert cur.fetchone()[0] == 100000
                    elif i % 4 == 2:
                        cur = conn.execute("SELECT full_name FROM users WHERE user_id = 'u1';")
                        assert cur.fetchone()[0] == "User 1"
                    else:
                        cur = conn.execute("SELECT task_id, title FROM tasks ORDER BY task_id LIMIT 5;")
                        rows = cur.fetchall()
                        assert len(rows) == 5

            elapsed = time.perf_counter() - start_time

            # Verification 1: Exactly ZERO sync calls triggered
            assert spy_sync.call_count == 0, f"Expected 0 sync calls, got {spy_sync.call_count}"
            assert spy_backup.call_count == 0, f"Expected 0 backup calls, got {spy_backup.call_count}"

            # Verification 2: Persistent file untouched
            assert os.path.getmtime(persistent_path) == initial_mtime
            assert os.path.getsize(persistent_path) == initial_size

            # Verification 3: High performance (1,000 reads completed within 1.0 second)
            assert elapsed < 1.0, f"Read workload took {elapsed:.2f}s, expected < 1.0s"


def test_rest_api_read_endpoints_zero_sync_overhead():
    """Verify REST API read endpoints (/health, /ready, /api/finance/accounts) do not trigger sync."""
    with tempfile.TemporaryDirectory() as td:
        persistent_path = os.path.join(td, "mount", "assistant.db")
        active_path = os.path.join(td, "scratch", "assistant.db")

        manager = DatabaseManager(
            db_path=active_path,
            persistent_db_path=persistent_path,
            sync_on_commit=True,
        )
        manager.init_db()

        set_default_manager(manager)
        try:
            with patch.object(
                manager, "_sync_conn_to_persistent", wraps=manager._sync_conn_to_persistent
            ) as spy_sync:
                with TestClient(main_app) as client:
                    for _ in range(50):
                        r1 = client.get("/health")
                        assert r1.status_code == 200
                        r2 = client.get("/ready")
                        assert r2.status_code == 200
                        r3 = client.get("/api/finance/accounts?user_id=default_user")
                        assert r3.status_code == 200

                # Must not have triggered a single sync
                assert spy_sync.call_count == 0
        finally:
            set_default_manager(None)


def test_write_triggers_sync_but_rollback_does_not():
    """Verify that write commits trigger sync, but rolled back transactions do NOT trigger sync."""
    with tempfile.TemporaryDirectory() as td:
        persistent_path = os.path.join(td, "mount", "assistant.db")
        active_path = os.path.join(td, "scratch", "assistant.db")

        manager = DatabaseManager(
            db_path=active_path,
            persistent_db_path=persistent_path,
            sync_on_commit=True,
        )
        manager.init_db()

        with patch.object(
            manager, "_sync_conn_to_persistent", wraps=manager._sync_conn_to_persistent
        ) as spy_sync:

            # 1. Successful write commit -> MUST trigger sync (call_count = 1)
            with manager.connection() as conn:
                conn.execute("INSERT INTO users (user_id, full_name) VALUES ('u_success', 'Success User');")

            assert spy_sync.call_count == 1

            # Verify persisted
            check_conn = sqlite3.connect(persistent_path)
            row = check_conn.execute("SELECT full_name FROM users WHERE user_id = 'u_success';").fetchone()
            check_conn.close()
            assert row is not None
            assert row[0] == "Success User"

            # 2. Failed / rolled back transaction -> MUST NOT trigger sync (call_count remains 1)
            with pytest.raises(sqlite3.IntegrityError):
                with manager.connection() as conn:
                    # Attempt duplicate insert on primary key
                    conn.execute("INSERT INTO users (user_id, full_name) VALUES ('u_success', 'Duplicate');")

            assert spy_sync.call_count == 1, "Rolled-back transaction must not trigger sync!"


def test_configuration_and_deployment_integrity():
    """Empirical Test 3: Static & structural verification of deployment configurations.

    Checks:
    1. deploy/deploy_cloud_run.sh:
       - --execution-environment gen2
       - --max-instances 1
       - Volume mount flags: --add-volume and --add-volume-mount=/app/data
       - Uniform bucket level access and roles/storage.objectAdmin
    2. deploy/cloudrun.yaml:
       - autoscaling.knative.dev/maxScale: "1"
       - uid=1001,gid=1001 in mountOptions
       - run.googleapis.com/execution-environment: gen2
       - bucketName: personal-assistant-data-435709049712
    3. deploy/Dockerfile:
       - Explicit UID 1001, GID 1001 appuser
       - chmod 700 /app/data
       - USER appuser
    """
    repo_root = Path(__file__).parent.parent

    # Check 1: deploy/deploy_cloud_run.sh
    deploy_sh = repo_root / "deploy" / "deploy_cloud_run.sh"
    assert deploy_sh.exists(), "deploy/deploy_cloud_run.sh missing"
    sh_content = deploy_sh.read_text(encoding="utf-8")

    assert "--execution-environment gen2" in sh_content
    assert "--max-instances 1" in sh_content
    assert "--add-volume=" in sh_content
    assert "type=cloud-storage" in sh_content
    assert "uid=1001;gid=1001;file-mode=0700;dir-mode=0700" in sh_content
    assert "--add-volume-mount=volume=data-volume,mount-path=/app/data" in sh_content
    assert "--uniform-bucket-level-access" in sh_content
    assert "roles/storage.objectAdmin" in sh_content

    # Check 2: deploy/cloudrun.yaml
    cloudrun_yaml = repo_root / "deploy" / "cloudrun.yaml"
    assert cloudrun_yaml.exists(), "deploy/cloudrun.yaml missing"
    yaml_content = cloudrun_yaml.read_text(encoding="utf-8")

    assert 'autoscaling.knative.dev/maxScale: "1"' in yaml_content
    assert "run.googleapis.com/execution-environment: gen2" in yaml_content
    assert 'mountOptions: "uid=1001,gid=1001,file-mode=0700,dir-mode=0700"' in yaml_content
    assert "mountPath: /app/data" in yaml_content
    assert "bucketName: personal-assistant-data-435709049712" in yaml_content

    # Check 3: deploy/Dockerfile
    dockerfile = repo_root / "deploy" / "Dockerfile"
    assert dockerfile.exists(), "deploy/Dockerfile missing"
    docker_content = dockerfile.read_text(encoding="utf-8")

    assert "groupadd -g 1001 appuser && useradd -r -u 1001 -g 1001 appuser" in docker_content
    assert "chmod 700 /app/data" in docker_content
    assert "USER appuser" in docker_content
    assert 'DATABASE_PATH="/app/data/assistant.db"' in docker_content
