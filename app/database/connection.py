"""SQLite connection manager with WAL mode, foreign keys, and row factory."""

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union

DEFAULT_DB_PATH = os.environ.get("DATABASE_PATH", "data/assistant.db")
SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve database path from argument, environment, or default."""
    if custom_path is not None:
        return custom_path
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


def configure_connection(conn: sqlite3.Connection, is_memory: bool = False) -> sqlite3.Connection:
    """Configure connection with WAL mode (if file-based), foreign keys, and row factory."""
    conn.row_factory = sqlite3.Row
    # Foreign keys must be enabled per connection in SQLite
    conn.execute("PRAGMA foreign_keys = ON;")
    if not is_memory:
        # WAL mode allows concurrent readers and a writer
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")  # 10 second timeout for lock contention
    return conn


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create a new SQLite connection with appropriate pragmas."""
    resolved_path = get_db_path(db_path)
    is_memory = resolved_path == ":memory:" or resolved_path.startswith("file:") and "mode=memory" in resolved_path

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


class DatabaseManager:
    """Thread-safe database manager managing SQLite connections and schema initialization."""

    def __init__(self, db_path: Optional[str] = None, conn: Optional[sqlite3.Connection] = None):
        if conn is not None:
            self.db_path = ":memory:"
            self.is_memory = True
            self._lock = threading.RLock()
            self._memory_conn = conn
            return

        self.db_path = get_db_path(db_path)
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
        """Context manager yielding a thread-safe connection with automatic commit/rollback."""
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
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

    def init_db(self, schema_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize database schema by executing DDL from schema.sql."""
        schema_file = Path(schema_path) if schema_path else SCHEMA_SQL_PATH
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found at: {schema_file}")

        schema_ddl = schema_file.read_text(encoding="utf-8")
        with self.connection() as conn:
            conn.executescript(schema_ddl)
            # Ensure transactions table has account_id and account_name columns
            cursor = conn.execute("PRAGMA table_info(transactions);")
            columns = [row[1] for row in cursor.fetchall()]
            if "account_id" not in columns:
                conn.execute("ALTER TABLE transactions ADD COLUMN account_id TEXT;")
            if "account_name" not in columns:
                conn.execute("ALTER TABLE transactions ADD COLUMN account_name TEXT;")

    def close(self) -> None:
        """Close persistent resources if in-memory."""
        with self._lock:
            if self._memory_conn is not None:
                try:
                    self._memory_conn.close()
                finally:
                    self._memory_conn = None


# Global default database manager
_default_manager: Optional[DatabaseManager] = None
_manager_lock = threading.Lock()


def get_default_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """Get or create singleton default DatabaseManager."""
    global _default_manager
    with _manager_lock:
        if _default_manager is None or (db_path is not None and _default_manager.db_path != db_path):
            _default_manager = DatabaseManager(db_path)
        return _default_manager


def set_default_manager(manager: DatabaseManager) -> None:
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
