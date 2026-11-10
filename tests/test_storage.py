from pathlib import Path

from app.storage.database import delete_credentials, get_credentials, initialize, save_credentials


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
