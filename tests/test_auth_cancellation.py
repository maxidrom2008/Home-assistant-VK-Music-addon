import asyncio
from pathlib import Path

import pytest

import app.vk.auth as auth
from app.vk.auth import VKAuthError, VKAuthManager


def test_cancelled_inflight_login_never_persists_late_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request_started = asyncio.Event()
    release_request = asyncio.Event()
    persisted = []

    async def delayed_request(login: str, password: str, **kwargs) -> str:
        request_started.set()
        await release_request.wait()
        return "late-token-after-cancel"

    monkeypatch.setattr(auth, "request_vk_token", delayed_request)
    monkeypatch.setattr(
        auth,
        "save_credentials",
        lambda *args: persisted.append(args),
    )

    async def scenario():
        manager = VKAuthManager(tmp_path / "vk.sqlite3")
        login_task = asyncio.create_task(
            manager.start("user@example.invalid", "temporary-password")
        )
        await request_started.wait()
        challenge_id = next(iter(manager.pending))
        assert manager.cancel(challenge_id) is True
        release_request.set()

        with pytest.raises(VKAuthError, match="отменён или истёк"):
            await login_task

        assert manager.pending == {}
        assert persisted == []

    asyncio.run(scenario())
