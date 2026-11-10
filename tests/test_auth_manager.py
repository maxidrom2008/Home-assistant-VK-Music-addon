import asyncio

import pytest

from app.vk.auth import AuthManager


def test_auth_manager_rejects_empty_credentials() -> None:
    manager = AuthManager()
    with pytest.raises(ValueError):
        asyncio.run(manager.start("", "secret"))


def test_auth_manager_rejects_answer_without_challenge() -> None:
    manager = AuthManager()
    with pytest.raises(RuntimeError):
        manager.submit_answer("123456")
