"""Credential persistence helpers."""
from pathlib import Path
from app.config import settings
from app.storage.database import connect


def save_credentials(token: str, user_agent: str) -> None:
    if not token or not user_agent:
        raise ValueError("VK token and user-agent are required")
    with connect(settings.database_path) as db:
        db.execute(
            """INSERT INTO vk_credentials(id, access_token, user_agent, updated_at)
               VALUES(1, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id) DO UPDATE SET
                 access_token=excluded.access_token,
                 user_agent=excluded.user_agent,
                 updated_at=CURRENT_TIMESTAMP""",
            (token, user_agent),
        )


def load_credentials() -> tuple[str, str] | None:
    if not settings.database_path.exists():
        return None
    with connect(settings.database_path) as db:
        row = db.execute(
            "SELECT access_token, user_agent FROM vk_credentials WHERE id=1"
        ).fetchone()
    if row is None:
        return None
    return str(row["access_token"]), str(row["user_agent"])


def delete_credentials() -> None:
    with connect(settings.database_path) as db:
        db.execute("DELETE FROM vk_credentials WHERE id=1")
