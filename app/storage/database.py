"""SQLite storage for durable VK credentials.

Only the final access token, User-Agent and VK user ID are persisted.
Passwords, CAPTCHA answers and one-time codes are never written to disk.
"""
import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        db = sqlite3.connect(path)
    finally:
        os.umask(old_umask)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return db


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
    return cursor.rowcount > 0
