from pathlib import Path
import os
import stat

from app.storage.database import (
    connect,
    delete_credentials,
    get_credentials,
    initialize,
    save_credentials,
)


def test_credentials_survive_reopen_and_can_be_deleted(tmp_path: Path) -> None:
    database = tmp_path / "data" / "vk_music.sqlite3"
    initialize(database)
    save_credentials(database, "test-token", "test-agent", "123")

    saved = get_credentials(database)
    assert saved is not None
    assert saved["access_token"] == "test-token"
    assert saved["user_agent"] == "test-agent"
    assert saved["user_id"] == "123"

    assert delete_credentials(database) is True
    assert get_credentials(database) is None
    assert delete_credentials(database) is False


def test_database_and_wal_sidecars_are_private_even_with_permissive_umask(
    tmp_path: Path,
) -> None:
    database = tmp_path / "data" / "vk_music.sqlite3"
    initialize(database)
    save_credentials(database, "private-token", "test-agent", "123")

    previous_umask = os.umask(0o022)
    try:
        with connect(database) as db:
            db.execute(
                "UPDATE vk_credentials SET access_token = ? WHERE id = 1",
                ("updated-private-token",),
            )
            wal = Path(f"{database}-wal")
            assert wal.exists()
            assert stat.S_IMODE(database.stat().st_mode) == 0o600
            assert stat.S_IMODE(wal.stat().st_mode) == 0o600
            shm = Path(f"{database}-shm")
            if shm.exists():
                assert stat.S_IMODE(shm.stat().st_mode) == 0o600
    finally:
        os.umask(previous_umask)

    assert os.umask(previous_umask) == previous_umask


def test_schema_v1_is_migrated_without_losing_credentials(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE vk_credentials ("
            "id INTEGER PRIMARY KEY, access_token TEXT NOT NULL, "
            "user_agent TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO vk_credentials(id, access_token, user_agent, updated_at) "
            "VALUES(1, 'legacy-token', 'legacy-agent', '2025-01-01')"
        )

    initialize(database)
    credentials = get_credentials(database)
    assert credentials is not None
    assert credentials["access_token"] == "legacy-token"
    assert credentials["user_agent"] == "legacy-agent"
    assert credentials["user_id"] is None
