"""SQLite bootstrap and connection helpers."""
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
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
        db.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
