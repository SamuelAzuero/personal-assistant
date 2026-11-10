"""Automated tests for persistent SQLite storage synchronization and Cloud Run configuration.

Verifies:
1. Startup restore from persistent storage volume mount to local scratch disk (/tmp).
2. Hot backup synchronization on write commit using SQLite Online Backup API with DELETE journal mode.
3. WAL checkpointing and graceful shutdown flush in FastAPI lifespan.
4. Zero data loss across simulated container scale-to-zero lifecycles.
5. Static audit of Dockerfile permissions, cloudrun.yaml single-writer limits, and deploy script flags.
"""

import os
import shutil
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database.connection import (
    DatabaseManager,
    backup_database,
    checkpoint_database,
    configure_connection,
    get_default_manager,
    restore_database,
    set_default_manager,
)


# ============================================================================
# Unit Tests: Storage Sync Primitives
# ============================================================================

def test_restore_database_existing_file():
    """Verify restore_database copies persistent file to local active path."""
    with tempfile.TemporaryDirectory() as td:
        persistent_file = os.path.join(td, "mount", "assistant.db")
        local_file = os.path.join(td, "local", "assistant.db")
        os.makedirs(os.path.dirname(persistent_file), exist_ok=True)

        # Create dummy persistent file
        with open(persistent_file, "wb") as f:
            f.write(b"SQLITE_DATA_PAYLOAD_TEST")

        assert restore_database(persistent_file, local_file) is True
        assert os.path.exists(local_file)
        with open(local_file, "rb") as f:
            assert f.read() == b"SQLITE_DATA_PAYLOAD_TEST"


def test_restore_database_missing_or_empty():
    """Verify restore_database returns False when persistent file is absent or empty."""
    with tempfile.TemporaryDirectory() as td:
        missing_file = os.path.join(td, "non_existent.db")
        local_file = os.path.join(td, "local.db")
        assert restore_database(missing_file, local_file) is False
        assert not os.path.exists(local_file)

        # Empty file (0 bytes)
        empty_file = os.path.join(td, "empty.db")
        Path(empty_file).touch()
        assert restore_database(empty_file, local_file) is False


def test_backup_database_sets_delete_journal_mode():
    """Verify backup_database hot-backups SQLite DB and sets destination to DELETE journal mode."""
    with tempfile.TemporaryDirectory() as td:
        src_path = os.path.join(td, "source.db")
        dst_path = os.path.join(td, "dest.db")

        # Create source DB in WAL mode with test table
        src_conn = sqlite3.connect(src_path)
        src_conn.execute("PRAGMA journal_mode = WAL;")
        src_conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, value INT);")
        src_conn.execute("INSERT INTO records VALUES ('r1', 12345);")
        src_conn.commit()

        # Backup via connection
        success = backup_database(src_conn, dst_path)
        src_conn.close()
        assert success is True
        assert os.path.exists(dst_path)

        # Verify destination DB
        dst_conn = sqlite3.connect(dst_path)
        cur = dst_conn.execute("PRAGMA journal_mode;")
        mode = cur.fetchone()[0]
        assert mode.upper() == "DELETE", "Destination DB must be in DELETE mode to prevent GCS FUSE MAP_SHARED errors"

        rows = dst_conn.execute("SELECT id, value FROM records;").fetchall()
        assert rows == [("r1", 12345)]
        dst_conn.close()


def test_backup_database_from_file_path():
    """Verify backup_database works when source is provided as a file path string."""
    with tempfile.TemporaryDirectory() as td:
        src_path = os.path.join(td, "source.db")
        dst_path = os.path.join(td, "dest.db")

        src_conn = sqlite3.connect(src_path)
        src_conn.execute("CREATE TABLE items (name TEXT);")
        src_conn.execute("INSERT INTO items VALUES ('laptop');")
        src_conn.commit()
        src_conn.close()

        success = backup_database(src_path, dst_path)
        assert success is True
        assert os.path.exists(dst_path)

        dst_conn = sqlite3.connect(dst_path)
        rows = dst_conn.execute("SELECT name FROM items;").fetchall()
        assert rows == [("laptop",)]
        dst_conn.close()


def test_checkpoint_database_wal():
    """Verify checkpoint_database executes PRAGMA wal_checkpoint(TRUNCATE)."""
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "active.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("CREATE TABLE metrics (val INT);")
        conn.execute("INSERT INTO metrics VALUES (99);")
        conn.commit()
        conn.close()

        # Checkpoint WAL
        checkpoint_database(db_path)

        # Reopen and verify data
        conn2 = sqlite3.connect(db_path)
        rows = conn2.execute("SELECT val FROM metrics;").fetchall()
        assert rows == [(99,)]
        conn2.close()


def test_configure_connection_modes():
    """Verify configure_connection configures journal_mode and synchronous appropriately."""
    conn_mem = sqlite3.connect(":memory:")
    configure_connection(conn_mem, is_memory=True)
    conn_mem.close()

    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test_mode.db")
        conn = sqlite3.connect(db_path)
        configure_connection(conn, is_memory=False, journal_mode="DELETE")
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.upper() == "DELETE"
        conn.close()


# ============================================================================
# Integration Tests: DatabaseManager Persistent Synchronization
# ============================================================================

def test_database_manager_mutation_sync_on_commit():
    """Verify DatabaseManager automatically syncs to persistent path when a mutation commits."""
    with tempfile.TemporaryDirectory() as td:
        active_db = os.path.join(td, "local", "active.db")
        persistent_db = os.path.join(td, "persistent", "backup.db")

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        mgr.init_db()

        # Ensure schema initialization was synced to persistent storage
        assert os.path.exists(persistent_db)
        assert os.path.getsize(persistent_db) > 0

        # Perform a write mutation
        with mgr.connection() as conn:
            conn.execute("INSERT INTO users (user_id, full_name) VALUES ('usr_100', 'Test Sync User');")

        # Verify persistent_db has updated data immediately
        dst_conn = sqlite3.connect(persistent_db)
        row = dst_conn.execute("SELECT full_name FROM users WHERE user_id = 'usr_100';").fetchone()
        dst_conn.close()
        assert row is not None
        assert row[0] == "Test Sync User"


def test_database_manager_read_does_not_unnecessarily_sync():
    """Verify DatabaseManager read-only transactions (no mutations) don't trigger sync."""
    with tempfile.TemporaryDirectory() as td:
        active_db = os.path.join(td, "active.db")
        persistent_db = os.path.join(td, "persistent.db")

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=True,
        )
        mgr.init_db()

        # Track persistent file mtime
        initial_mtime = os.path.getmtime(persistent_db)

        # Read-only query
        with mgr.connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM users;")
            cur.fetchone()

        # Modification time remains untouched
        assert os.path.getmtime(persistent_db) == initial_mtime


def test_database_manager_sync_to_persistent_explicit():
    """Verify explicit sync_to_persistent flushes WAL pages to persistent file."""
    with tempfile.TemporaryDirectory() as td:
        active_db = os.path.join(td, "active.db")
        persistent_db = os.path.join(td, "persistent.db")

        mgr = DatabaseManager(
            db_path=active_db,
            persistent_db_path=persistent_db,
            sync_on_commit=False,  # mutation sync disabled
        )
        mgr.init_db()

        # Write directly to active connection
        with mgr.connection() as conn:
            conn.execute("INSERT INTO users (user_id, full_name) VALUES ('usr_200', 'Manual Flush User');")

        # Explicit sync
        res = mgr.sync_to_persistent()
        assert res is True

        dst_conn = sqlite3.connect(persistent_db)
        row = dst_conn.execute("SELECT full_name FROM users WHERE user_id = 'usr_200';").fetchone()
        dst_conn.close()
        assert row is not None
        assert row[0] == "Manual Flush User"


# ============================================================================
# E2E Simulation: Scale-to-Zero Container Lifecycle & Zero Data Loss
# ============================================================================

def test_fastapi_lifespan_scale_to_zero_simulation():
    """Simulate complete Cloud Run lifecycle: cold start, mutation, scale-to-zero wipe, and restore."""
    with tempfile.TemporaryDirectory() as td:
        persistent_mount = os.path.join(td, "app_data", "assistant.db")
        tmp_scratch = os.path.join(td, "tmp", "assistant.db")

        # 1. Cold Start Instance 1
        @asynccontextmanager
        async def custom_lifespan(app_inst: FastAPI):
            # Startup restore
            restore_database(persistent_mount, tmp_scratch)
            os.makedirs(os.path.dirname(tmp_scratch), exist_ok=True)
            mgr = DatabaseManager(
                db_path=tmp_scratch,
                persistent_db_path=persistent_mount,
                sync_on_commit=True,
            )
            mgr.init_db()
            set_default_manager(mgr)
            app_inst.state.mgr = mgr

            yield

            # Shutdown flush on SIGTERM
            mgr.sync_to_persistent()
            mgr.close()
            set_default_manager(None)

        test_app = FastAPI(lifespan=custom_lifespan)

        @test_app.post("/api/deposit")
        def deposit(amount: int):
            with test_app.state.mgr.connection() as conn:
                conn.execute(
                    "UPDATE accounts SET balance_cents = balance_cents + ? WHERE account_type = 'digital_wallet';",
                    (amount,),
                )
            return {"status": "ok"}

        # Boot instance 1
        with TestClient(test_app) as client:
            # Seed an account in the active DB
            with test_app.state.mgr.connection() as conn:
                conn.execute("INSERT INTO users (user_id, full_name) VALUES ('samuel', 'Samuel Azuero');")
                conn.execute(
                    "INSERT INTO accounts (account_id, user_id, name, account_type, balance_cents, currency) "
                    "VALUES ('acc_nequi', 'samuel', 'Nequi', 'digital_wallet', 5000000, 'COP');"
                )
            resp = client.post("/api/deposit?amount=2500000")
            assert resp.status_code == 200

        # Instance 1 has terminated (lifespan exit complete)
        assert os.path.exists(persistent_mount), "Persistent storage file must exist"
        assert os.path.getsize(persistent_mount) > 0

        # Verify persistent image has the updated balance (7,500,000 cents = 75,000 COP)
        dst_check = sqlite3.connect(persistent_mount)
        bal = dst_check.execute("SELECT balance_cents FROM accounts WHERE account_id = 'acc_nequi';").fetchone()[0]
        dst_check.close()
        assert bal == 7500000

        # 2. SCALE-TO-ZERO: The local container overlay (/tmp) is completely wiped!
        shutil.rmtree(os.path.dirname(tmp_scratch))
        assert not os.path.exists(tmp_scratch), "/tmp scratch disk must be gone"

        # 3. Cold Start Instance 2: boots up with clean scratch disk, restores from persistent mount
        test_app_v2 = FastAPI(lifespan=custom_lifespan)

        @test_app_v2.get("/api/balance")
        def get_balance():
            with test_app_v2.state.mgr.connection() as conn:
                row = conn.execute("SELECT balance_cents FROM accounts WHERE account_id = 'acc_nequi';").fetchone()
                return {"balance_cents": row[0] if row else 0}

        with TestClient(test_app_v2) as client2:
            resp = client2.get("/api/balance")
            assert resp.status_code == 200
            assert resp.json()["balance_cents"] == 7500000, "Balance must be 100% retained across scale-to-zero!"


def test_app_main_lifespan_decouple_app_data():
    """Verify app.main lifespan decouples /app/data path to /tmp for WAL speed and GCS sync."""
    from app.main import app
    from app.config import get_settings

    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        fake_app_data = os.path.join(td, "app", "data", "assistant.db")
        fake_tmp = os.path.join(td, "tmp", "assistant.db")
        os.makedirs(os.path.dirname(fake_app_data), exist_ok=True)
        os.makedirs(os.path.dirname(fake_tmp), exist_ok=True)

        # Pre-seed persistent DB file
        p_conn = sqlite3.connect(fake_app_data)
        p_conn.execute("CREATE TABLE config (k TEXT PRIMARY KEY, v TEXT);")
        p_conn.execute("INSERT INTO config VALUES ('deployed_version', 'v2.1');")
        p_conn.commit()
        p_conn.close()

        # Temporarily mock settings
        orig_db_path = settings.database_path
        orig_persistent = settings.persistent_db_path
        try:
            settings.database_path = fake_app_data
            settings.persistent_db_path = None

            # Startup test client
            with TestClient(app) as client:
                resp = client.get("/ready")
                assert resp.status_code == 200

                # Active database should have been decoupled to /tmp
                assert settings.database_path == f"/tmp/{Path(fake_app_data).name}"

                # Verify restored table exists in active DB
                mgr = get_default_manager()
                with mgr.connection() as conn:
                    row = conn.execute("SELECT v FROM config WHERE k = 'deployed_version';").fetchone()
                    assert row is not None
                    assert row[0] == "v2.1"
        finally:
            settings.database_path = orig_db_path
            settings.persistent_db_path = orig_persistent


# ============================================================================
# Static Audit Tests: Dockerfile, cloudrun.yaml, and deploy_cloud_run.sh
# ============================================================================

def test_static_audit_dockerfile_permissions():
    """Verify Dockerfile creates appuser with UID/GID 1001 and chmod 700 /app/data."""
    dockerfile_path = Path("deploy/Dockerfile")
    assert dockerfile_path.exists()
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "groupadd -g 1001 appuser" in content or "useradd -r -u 1001 -g 1001 appuser" in content, (
        "Dockerfile must configure explicit UID 1001 and GID 1001 for appuser"
    )
    assert "chmod 700 /app/data" in content, "Dockerfile must set directory permissions chmod 700 /app/data"
    assert "USER appuser" in content


def test_static_audit_cloudrun_yaml_integrity():
    """Verify cloudrun.yaml enforces maxScale 1, GCS volume mount, and UID 1001 mount options."""
    yaml_path = Path("deploy/cloudrun.yaml")
    assert yaml_path.exists()
    content = yaml_path.read_text(encoding="utf-8")

    assert 'autoscaling.knative.dev/maxScale: "1"' in content, (
        "cloudrun.yaml must enforce maxScale: '1' for single-writer SQLite integrity"
    )
    assert "bucketName: personal-assistant-data-435709049712" in content
    assert 'mountOptions: "uid=1001,gid=1001,file-mode=0700,dir-mode=0700"' in content
    assert "mountPath: /app/data" in content
    assert "run.googleapis.com/execution-environment: gen2" in content


def test_static_audit_deploy_cloud_run_script():
    """Verify deploy_cloud_run.sh automates project number detection, bucket creation, IAM, and volume mount."""
    script_path = Path("deploy/deploy_cloud_run.sh")
    assert script_path.exists()
    content = script_path.read_text(encoding="utf-8")

    # Project number auto-detection
    assert "PROJECT_NUMBER=$(gcloud projects describe" in content
    assert "value(projectNumber)" in content

    # Bucket naming & creation
    assert "personal-assistant-data-${PROJECT_NUMBER}" in content
    assert "storage.googleapis.com" in content
    assert "gcloud storage buckets create" in content
    assert "--uniform-bucket-level-access" in content

    # IAM role binding
    assert "roles/storage.objectAdmin" in content
    assert "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" in content or "COMPUTE_SA" in content

    # Cloud Run flags
    assert "--max-instances 1" in content
    assert "--execution-environment gen2" in content
    assert "--add-volume=" in content
    assert "mount-options=" in content
    assert "uid=1001" in content
    assert "gid=1001" in content
    assert "--add-volume-mount=volume=data-volume,mount-path=/app/data" in content
