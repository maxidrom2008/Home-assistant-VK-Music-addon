"""SQLite storage for durable VK credentials.

Only the final access token, User-Agent and VK user ID are persisted.
Passwords, CAPTCHA answers and one-time codes are never written to disk.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Any

SCHEMA_VERSION = 2


def _restrict_file_permissions(path: Path) -> None:
    """Best-effort chmod for the database and SQLite's sensitive sidecars."""
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            if candidate.exists():
                candidate.chmod(0o600)
        except OSError:
            # A read-only or unusual filesystem must not prevent startup.
            pass


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open SQLite with private permissions for the DB and WAL sidecars."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Tighten files from older releases before opening them; the token is
    # sensitive even when SQLite is only being read.
    _restrict_file_permissions(path)
    old_umask = os.umask(0o077)
    db: sqlite3.Connection | None = None
    try:
        # Keep the restrictive umask for the entire connection lifetime:
        # SQLite creates -wal/-shm lazily, after connect() has returned.
        db = sqlite3.connect(path)
        _restrict_file_permissions(path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        _restrict_file_permissions(path)
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()
    finally:
        try:
            if db is not None:
                db.close()
            _restrict_file_permissions(path)
        finally:
            os.umask(old_umask)


def initialize(path: Path) -> None:
    with connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS vk_credentials (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            access_token TEXT NOT NULL,
            user_agent TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(vk_credentials)")}
        if "user_id" not in columns:
            db.execute("ALTER TABLE vk_credentials ADD COLUMN user_id TEXT")
        db.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                   (str(SCHEMA_VERSION),))


def save_credentials(path: Path, access_token: str, user_agent: str,
                     user_id: str | None = None) -> None:
    if not access_token.strip() or not user_agent.strip():
        raise ValueError("Access token and User-Agent are required")
    with connect(path) as db:
        db.execute("""INSERT INTO vk_credentials(id, access_token, user_agent, user_id, updated_at)
            VALUES(1, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
            access_token=excluded.access_token, user_agent=excluded.user_agent,
            user_id=excluded.user_id, updated_at=CURRENT_TIMESTAMP""",
            (access_token.strip(), user_agent.strip(), user_id))


def get_credentials(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with connect(path) as db:
        row = db.execute("SELECT access_token, user_agent, user_id, updated_at "
                         "FROM vk_credentials WHERE id=1").fetchone()
    return dict(row) if row else None


def delete_credentials(path: Path) -> bool:
    if not path.exists():
        return False
    with connect(path) as db:
        cursor = db.execute("DELETE FROM vk_credentials WHERE id=1")
        deleted = cursor.rowcount > 0
    # Checkpoint and compact the DB so removed records are not left in its WAL.
    with connect(path) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("VACUUM")
    return deleted
