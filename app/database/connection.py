"""SQLite connection manager with WAL mode, foreign keys, row factory, and persistent GCS sync."""

import logging
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get("DATABASE_PATH", "data/assistant.db")
SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve database path from argument, active DatabaseManager, environment, or default."""
    if custom_path is not None:
        return custom_path
    mgr = globals().get("_default_manager")
    if mgr is not None and not mgr.is_memory:
        return mgr.db_path
    return os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)


DEFAULT_ACCOUNT_DEFINITIONS = [
    {"name": "Efectivo", "account_type": "cash", "icon": "💵", "color": "#10b981"},
    {"name": "Nequi", "account_type": "digital_wallet", "icon": "📱", "color": "#200020"},
    {"name": "Nu", "account_type": "bank_account", "icon": "🟣", "color": "#820AD1"},
    {"name": "Daviplata", "account_type": "digital_wallet", "icon": "🔴", "color": "#EE3124"},
    {"name": "Bancolombia", "account_type": "bank_account", "icon": "🟡", "color": "#FDDA24"},
]


def seed_default_accounts_for_user(conn: sqlite3.Connection, user_id: str) -> None:
    """Ensure user exists and seed default Colombian accounts if not present."""
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?);",
        (user_id, user_id),
    )
    for acc in DEFAULT_ACCOUNT_DEFINITIONS:
        acc_id = f"acc_{user_id}_{acc['name'].lower()}"
        conn.execute(
            """
            INSERT OR IGNORE INTO accounts (
                account_id, user_id, name, account_type, balance_cents, currency, color, icon, is_active
            ) VALUES (?, ?, ?, ?, 0, 'COP', ?, ?, 1);
            """,
            (acc_id, user_id, acc["name"], acc["account_type"], acc["color"], acc["icon"]),
        )


def configure_connection(
    conn: sqlite3.Connection,
    is_memory: bool = False,
    journal_mode: Optional[str] = None,
) -> sqlite3.Connection:
    """Configure connection with WAL mode (if file-based), foreign keys, and row factory."""
    conn.row_factory = sqlite3.Row
    # Foreign keys must be enabled per connection in SQLite
    conn.execute("PRAGMA foreign_keys = ON;")
    if not is_memory:
        mode = (journal_mode or os.environ.get("SQLITE_JOURNAL_MODE", "WAL")).upper()
        conn.execute(f"PRAGMA journal_mode = {mode};")
        if mode == "WAL":
            conn.execute("PRAGMA synchronous = NORMAL;")
        else:
            conn.execute("PRAGMA synchronous = FULL;")
    conn.execute("PRAGMA busy_timeout = 10000;")  # 10 second timeout for lock contention
    return conn


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create a new SQLite connection with appropriate pragmas."""
    resolved_path = get_db_path(db_path)
    is_memory = resolved_path == ":memory:" or (
        resolved_path.startswith("file:") and "mode=memory" in resolved_path
    )

    if not is_memory:
        parent_dir = Path(resolved_path).parent
        if parent_dir and not parent_dir.exists():
            parent_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        resolved_path,
        timeout=30.0,
        check_same_thread=False,
    )
    return configure_connection(conn, is_memory=is_memory)


def restore_database(persistent_path: str, local_path: str) -> bool:
    """Restore local active database from persistent storage file if available."""
    p_file = Path(persistent_path)
    if not p_file.exists() or p_file.stat().st_size == 0:
        return False
    l_file = Path(local_path)
    l_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(p_file, l_file)
        logger.info(
            "Successfully restored database from %s to %s (%d bytes)",
            persistent_path,
            local_path,
            p_file.stat().st_size,
        )
        return True
    except Exception as e:
        logger.error("Failed to restore database from %s to %s: %s", persistent_path, local_path, e)
        return False


def backup_database(source: Union[str, sqlite3.Connection], target_path: str) -> bool:
    """Hot-backup database to target persistent path using SQLite Online Backup API.

    Ensures target file is in DELETE journal mode so no -wal or -shm files
    are created on the persistent mount (preventing FUSE MAP_SHARED failures).
    """
    target_file = Path(target_path)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    close_source = False
    if isinstance(source, str):
        if source == ":memory:" or not Path(source).exists():
            return False
        src_conn = sqlite3.connect(source)
        close_source = True
    else:
        src_conn = source

    try:
        dst_conn = sqlite3.connect(target_path, timeout=30.0)
        try:
            src_conn.backup(dst_conn)
            dst_conn.execute("PRAGMA journal_mode = DELETE;")
            dst_conn.commit()
        finally:
            dst_conn.close()
        return True
    except Exception as e:
        logger.error("Failed to backup database to %s: %s", target_path, e)
        return False
    finally:
        if close_source:
            src_conn.close()


def checkpoint_database(db_path: str) -> None:
    """Execute WAL checkpoint to flush all WAL pages to main database file."""
    if db_path == ":memory:" or not Path(db_path).exists():
        return
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        finally:
            conn.close()
    except Exception as e:
        logger.warning("WAL checkpoint warning on %s: %s", db_path, e)


class DatabaseManager:
    """Thread-safe database manager managing SQLite connections, schema initialization, and persistent sync."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
        persistent_db_path: Optional[str] = None,
        sync_on_commit: bool = True,
    ):
        if conn is not None:
            self.db_path = ":memory:"
            self.is_memory = True
            self.persistent_db_path = None
            self.sync_on_commit = False
            self._lock = threading.RLock()
            self._memory_conn = conn
            return

        self.db_path = get_db_path(db_path)
        self.persistent_db_path = persistent_db_path or os.environ.get("PERSISTENT_DB_PATH")
        self.sync_on_commit = sync_on_commit and bool(self.persistent_db_path)
        self.is_memory = self.db_path == ":memory:" or (
            self.db_path.startswith("file:") and "mode=memory" in self.db_path
        )
        self._lock = threading.RLock()
        self._memory_conn: Optional[sqlite3.Connection] = None

        if self.is_memory:
            # Maintain persistent root connection for in-memory DB so data persists for manager's lifetime
            self._memory_conn = create_connection(self.db_path)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding a thread-safe connection with automatic commit/rollback and persistent sync."""
        with self._lock:
            if self.is_memory and self._memory_conn is not None:
                try:
                    yield self._memory_conn
                    self._memory_conn.commit()
                except Exception:
                    self._memory_conn.rollback()
                    raise
            else:
                conn = create_connection(self.db_path)
                try:
                    initial_changes = conn.total_changes
                    yield conn
                    conn.commit()
                    has_mutations = conn.total_changes > initial_changes
                    if has_mutations and self.sync_on_commit and self.persistent_db_path:
                        self._sync_conn_to_persistent(conn)
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

    def _sync_conn_to_persistent(self, conn: sqlite3.Connection) -> bool:
        """Hot-backup open connection to persistent storage file."""
        if not self.persistent_db_path or self.is_memory:
            return False
        try:
            target_path = Path(self.persistent_db_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            dst_conn = sqlite3.connect(self.persistent_db_path, timeout=30.0)
            try:
                conn.backup(dst_conn)
                dst_conn.execute("PRAGMA journal_mode = DELETE;")
                dst_conn.commit()
            finally:
                dst_conn.close()
            return True
        except Exception as e:
            logger.error("Failed to sync database to %s: %s", self.persistent_db_path, e)
            return False

    def sync_to_persistent(self) -> bool:
        """Explicitly checkpoint WAL and flush local database to persistent storage."""
        with self._lock:
            if not self.persistent_db_path or self.is_memory:
                return False
            try:
                checkpoint_database(self.db_path)
                return backup_database(self.db_path, self.persistent_db_path)
            except Exception as e:
                logger.error("Failed to sync database to %s: %s", self.persistent_db_path, e)
                return False

    def init_db(self, schema_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize database schema by executing DDL from schema.sql."""
        schema_file = Path(schema_path) if schema_path else SCHEMA_SQL_PATH
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found at: {schema_file}")

        schema_ddl = schema_file.read_text(encoding="utf-8")
        with self.connection() as conn:
            # Pre-migration: If tables already exist in legacy form, add new columns before executing schema DDL/indexes
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions';")
            if cursor.fetchone():
                cursor = conn.execute("PRAGMA table_info(transactions);")
                columns = [row[1] for row in cursor.fetchall()]
                if "account_id" not in columns:
                    conn.execute("ALTER TABLE transactions ADD COLUMN account_id TEXT;")
                if "account_name" not in columns:
                    conn.execute("ALTER TABLE transactions ADD COLUMN account_name TEXT;")

            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='debts';")
            if cursor.fetchone():
                cursor = conn.execute("PRAGMA table_info(debts);")
                debt_cols = {row[1] for row in cursor.fetchall()}
                new_debt_columns = [
                    ("is_installment", "BOOLEAN NOT NULL DEFAULT 0"),
                    ("total_installments", "INTEGER DEFAULT 1"),
                    ("remaining_installments", "INTEGER DEFAULT 1"),
                    ("installment_amount_cents", "INTEGER DEFAULT 0"),
                    ("payment_frequency", "TEXT DEFAULT 'monthly'"),
                    ("next_installment_due_date", "TIMESTAMP"),
                    ("updated_at", "TIMESTAMP"),
                ]
                for col_name, col_ddl in new_debt_columns:
                    if col_name not in debt_cols:
                        conn.execute(f"ALTER TABLE debts ADD COLUMN {col_name} {col_ddl};")

            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='debt_payments';")
            if cursor.fetchone():
                cursor = conn.execute("PRAGMA table_info(debt_payments);")
                payment_cols = {row[1] for row in cursor.fetchall()}
                if "installments_paid" not in payment_cols:
                    conn.execute("ALTER TABLE debt_payments ADD COLUMN installments_paid INTEGER DEFAULT 1;")

            conn.executescript(schema_ddl)

        # If persistent storage is configured, ensure initial schema is synced to persistent mount
        if self.persistent_db_path and not self.is_memory:
            self.sync_to_persistent()

    def close(self) -> None:
        """Close persistent resources and checkpoint database."""
        with self._lock:
            if self._memory_conn is not None:
                try:
                    self._memory_conn.close()
                finally:
                    self._memory_conn = None
            elif not self.is_memory and self.db_path and Path(self.db_path).exists():
                checkpoint_database(self.db_path)


# Global default database manager
_default_manager: Optional[DatabaseManager] = None
_manager_lock = threading.Lock()


def get_default_manager(
    db_path: Optional[str] = None,
    persistent_db_path: Optional[str] = None,
    sync_on_commit: bool = True,
) -> DatabaseManager:
    """Get or create singleton default DatabaseManager."""
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = DatabaseManager(
                db_path=db_path,
                persistent_db_path=persistent_db_path,
                sync_on_commit=sync_on_commit,
            )
        elif _default_manager.is_memory and _default_manager._memory_conn is not None:
            # Preserves injected in-memory manager from tests
            return _default_manager
        elif db_path is not None and _default_manager.db_path != db_path:
            _default_manager = DatabaseManager(
                db_path=db_path,
                persistent_db_path=persistent_db_path,
                sync_on_commit=sync_on_commit,
            )
        else:
            if persistent_db_path is not None and _default_manager.persistent_db_path != persistent_db_path:
                _default_manager.persistent_db_path = persistent_db_path
            _default_manager.sync_on_commit = sync_on_commit
        return _default_manager


def set_default_manager(manager: Optional[DatabaseManager]) -> None:
    """Set global default DatabaseManager (primarily for testing with isolated in-memory DB)."""
    global _default_manager
    with _manager_lock:
        _default_manager = manager


@contextmanager
def get_db_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Convenience context manager for database connections."""
    manager = get_default_manager(db_path)
    with manager.connection() as conn:
        yield conn


def init_db(db_path: Optional[str] = None, schema_path: Optional[Union[str, Path]] = None) -> None:
    """Initialize database schema for the target path."""
    manager = get_default_manager(db_path)
    manager.init_db(schema_path)
