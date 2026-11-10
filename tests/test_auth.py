import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.vk.auth as auth
from app.vk.auth import (
    VKAuthChallenge,
    VKAuthManager,
    build_auth_request,
    challenge_view,
    validate_browser_captcha_link,
    validate_legacy_captcha_image,
)


CAPTCHA_LINK_1 = "https://id.vk.com/not_robot_captcha?domain=vk.com&session_token=first"
CAPTCHA_LINK_2 = "https://id.vk.com/not_robot_captcha?domain=vk.com&session_token=second"


def test_vk_auth_requests_offline_scope_without_forcing_sms() -> None:
    request = build_auth_request("user@example.invalid", "temporary-test-password")
    assert request.params["scope"] == "audio,offline"
    assert "force_sms" not in request.params


def test_browser_captcha_success_token_is_sent_as_its_own_parameter() -> None:
    request = build_auth_request(
        "user@example.invalid",
        "temporary-test-password",
        captcha_success_token="browser-captcha-token",
    )
    assert request.params["success_token"] == "browser-captcha-token"
    assert "captcha_sid" not in request.params
    assert "captcha_key" not in request.params


def test_legacy_image_captcha_parameters_are_preserved() -> None:
    request = build_auth_request(
        "user@example.invalid",
        "temporary-test-password",
        captcha_sid="captcha-id",
        captcha_answer="answer",
    )
    assert request.params["captcha_sid"] == "captcha-id"
    assert request.params["captcha_key"] == "answer"


def test_only_vk_id_browser_captcha_links_are_accepted() -> None:
    assert validate_browser_captcha_link(CAPTCHA_LINK_1) == CAPTCHA_LINK_1
    for link in (
        "http://id.vk.com/not_robot_captcha?session_token=x",
        "https://evil.example/not_robot_captcha?session_token=x",
        "https://id.vk.com.evil.example/not_robot_captcha?session_token=x",
        "https://id.vk.com/other?session_token=x",
        "https://id.vk.com/not_robot_captcha",
    ):
        with pytest.raises(ValueError):
            validate_browser_captcha_link(link)


def test_browser_captcha_challenge_view_contains_the_vk_id_link() -> None:
    view = challenge_view(
        {"error": "need_captcha", "redirect_uri": CAPTCHA_LINK_1},
        "challenge-id-that-is-long-enough",
    )
    assert view["state"] == "challenge_required"
    assert view["challenge"]["type"] == "browser_captcha"
    assert view["challenge"]["link"] == CAPTCHA_LINK_1


def test_legacy_image_challenge_view_is_still_supported() -> None:
    view = challenge_view(
        {
            "error": "need_captcha",
            "captcha_sid": "sid-123",
            "captcha_img": "https://vk.com/captcha.php?sid=sid-123",
        },
        "challenge-id-that-is-long-enough",
    )
    assert view["challenge"]["type"] == "captcha"
    assert view["challenge"]["image"].endswith("sid=sid-123")


def test_browser_captcha_flow_submits_success_token_and_clears_pending_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    persisted: list[tuple[str, str, str | None]] = []

    async def fake_request_vk_token(login: str, password: str, **kwargs) -> str:
        calls.append(kwargs)
        if len(calls) == 1:
            raise VKAuthChallenge(
                {"error": "need_captcha", "redirect_uri": CAPTCHA_LINK_1}
            )
        assert login == "user@example.invalid"
        assert password == "temporary-test-password"
        return "durable-token"

    class FakeService:
        def __init__(self, *, user_agent: str, token: str) -> None:
            assert token == "durable-token"
            self.user_agent = user_agent

        async def is_token_valid_async(self) -> bool:
            return True

        async def get_user_info_async(self):
            return SimpleNamespace(userid=12345)

    monkeypatch.setattr(auth, "request_vk_token", fake_request_vk_token)
    monkeypatch.setattr(auth, "Service", FakeService)
    monkeypatch.setattr(
        auth,
        "save_credentials",
        lambda path, token, user_agent, user_id: persisted.append(
            (token, user_agent, user_id)
        ),
    )

    async def scenario():
        manager = VKAuthManager(tmp_path / "vk.sqlite3")
        challenge = await manager.start("user@example.invalid", "temporary-test-password")
        assert challenge["challenge"]["type"] == "browser_captcha"
        challenge_id = challenge["challenge_id"]
        result = await manager.submit(challenge_id, "browser-generated-success-token")

        assert result["authenticated"] is True
        assert calls[1]["captcha_success_token"] == "browser-generated-success-token"
        assert calls[1]["captcha_sid"] is None
        assert persisted[0][0] == "durable-token"
        assert manager.pending == {}

    asyncio.run(scenario())


def test_rejected_captcha_token_gets_a_fresh_link_not_a_reused_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    persisted: list[str] = []

    async def fake_request_vk_token(login: str, password: str, **kwargs) -> str:
        calls.append(kwargs)
        if len(calls) == 1:
            raise VKAuthChallenge(
                {"error": "need_captcha", "redirect_uri": CAPTCHA_LINK_1}
            )
        if len(calls) == 2:
            assert kwargs["captcha_success_token"] == "expired-or-rejected"
            raise VKAuthChallenge({"error": "invalid_request"})
        if len(calls) == 3:
            assert kwargs["captcha_success_token"] is None
            raise VKAuthChallenge(
                {"error": "need_captcha", "redirect_uri": CAPTCHA_LINK_2}
            )
        assert kwargs["captcha_success_token"] == "fresh-success-token"
        return "durable-token"

    class FakeService:
        def __init__(self, *, user_agent: str, token: str) -> None:
            pass

        async def is_token_valid_async(self) -> bool:
            return True

        async def get_user_info_async(self):
            return SimpleNamespace(userid=12345)

    monkeypatch.setattr(auth, "request_vk_token", fake_request_vk_token)
    monkeypatch.setattr(auth, "Service", FakeService)
    monkeypatch.setattr(
        auth,
        "save_credentials",
        lambda path, token, user_agent, user_id: persisted.append(token),
    )

    async def scenario():
        manager = VKAuthManager(tmp_path / "vk.sqlite3")
        first = await manager.start("user@example.invalid", "temporary-test-password")
        challenge_id = first["challenge_id"]
        rejected = await manager.submit(challenge_id, "expired-or-rejected")
        assert rejected["challenge"]["link"] == CAPTCHA_LINK_2
        finished = await manager.submit(challenge_id, "fresh-success-token")
        assert finished["authenticated"] is True
        assert len(calls) == 4
        assert persisted == ["durable-token"]
        assert manager.pending == {}

    asyncio.run(scenario())


def test_refresh_expired_browser_captcha_requests_a_new_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    links = iter((CAPTCHA_LINK_1, CAPTCHA_LINK_2))

    async def fake_request_vk_token(login: str, password: str, **kwargs) -> str:
        raise VKAuthChallenge({"error": "need_captcha", "redirect_uri": next(links)})

    monkeypatch.setattr(auth, "request_vk_token", fake_request_vk_token)

    async def scenario():
        manager = VKAuthManager(tmp_path / "vk.sqlite3")
        first = await manager.start("user@example.invalid", "temporary-test-password")
        second = await manager.refresh_captcha(first["challenge_id"])
        assert first["challenge"]["link"] == CAPTCHA_LINK_1
        assert second["challenge"]["link"] == CAPTCHA_LINK_2

    asyncio.run(scenario())


def test_device_approval_can_continue_without_an_otp_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    persisted: list[str] = []

    async def fake_request_vk_token(login: str, password: str, **kwargs) -> str:
        calls.append(kwargs)
        if len(calls) == 1:
            raise VKAuthChallenge(
                {
                    "error": "need_validation",
                    "validation_type": "2fa_push",
                    "validation_sid": "validation-session",
                }
            )
        return "durable-token"

    async def fake_request_validation(sid: str) -> None:
        assert sid == "validation-session"

    class FakeService:
        def __init__(self, *, user_agent: str, token: str) -> None:
            assert token == "durable-token"

        async def is_token_valid_async(self) -> bool:
            return True

        async def get_user_info_async(self):
            return SimpleNamespace(userid=12345)

    monkeypatch.setattr(auth, "request_vk_token", fake_request_vk_token)
    monkeypatch.setattr(auth, "request_vk_validation", fake_request_validation)
    monkeypatch.setattr(auth, "Service", FakeService)
    monkeypatch.setattr(
        auth,
        "save_credentials",
        lambda path, token, user_agent, user_id: persisted.append(token),
    )

    async def scenario():
        manager = VKAuthManager(tmp_path / "vk.sqlite3")
        challenge = await manager.start("user@example.invalid", "temporary-test-password")
        assert challenge["challenge"]["approval_supported"] is True
        result = await manager.submit(challenge["challenge_id"], "", approved=True)
        assert result["authenticated"] is True
        assert calls[1]["code"] is None
        assert persisted == ["durable-token"]

    asyncio.run(scenario())



def test_legacy_captcha_image_requires_https_vk_host() -> None:
    url = "https://api.vk.com/captcha.php?sid=123"
    assert validate_legacy_captcha_image(url) == url
    for value in (
        "http://api.vk.com/captcha.php?sid=123",
        "https://evil.example/captcha.php?sid=123",
        "https://api.vk.com.evil.example/captcha.php?sid=123",
        "https://api.vk.com/not-an-image?sid=123",
    ):
        with pytest.raises(ValueError):
            validate_legacy_captcha_image(value)


def test_untrusted_legacy_captcha_image_is_not_returned_to_browser() -> None:
    view = challenge_view(
        {
            "error": "need_captcha",
            "captcha_sid": "sid-123",
            "captcha_img": "https://evil.example/captcha.php?sid=sid-123",
        },
        "challenge-id-that-is-long-enough",
    )
    assert view["challenge"]["type"] == "unsupported_captcha"
    assert "image" not in view["challenge"]


def test_pending_auth_session_is_expired_automatically_and_removed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth, "PENDING_TTL_SECONDS", 0.03)

    async def fake_request_vk_token(login: str, password: str, **kwargs) -> str:
        raise VKAuthChallenge(
            {"error": "need_captcha", "redirect_uri": CAPTCHA_LINK_1}
        )

    monkeypatch.setattr(auth, "request_vk_token", fake_request_vk_token)

    async def scenario():
        manager = VKAuthManager(tmp_path / "vk.sqlite3")
        challenge = await manager.start("user@example.invalid", "temporary-test-password")
        challenge_id = challenge["challenge_id"]
        assert challenge_id in manager.pending
        await asyncio.sleep(0.08)
        assert challenge_id not in manager.pending
        assert challenge_id not in manager._expiry_handles
        with pytest.raises(ValueError, match="истёк"):
            await manager.submit(challenge_id, "answer")

    asyncio.run(scenario())


def test_cancelled_pending_session_cancels_expiry_timer(tmp_path: Path) -> None:
    async def fake_request_vk_token(login: str, password: str, **kwargs) -> str:
        raise VKAuthChallenge(
            {"error": "need_captcha", "redirect_uri": CAPTCHA_LINK_1}
        )

    original = auth.request_vk_token
    auth.request_vk_token = fake_request_vk_token
    try:
        async def scenario():
            manager = VKAuthManager(tmp_path / "vk.sqlite3")
            challenge = await manager.start("user@example.invalid", "temporary-test-password")
            challenge_id = challenge["challenge_id"]
            assert manager.cancel(challenge_id) is True
            assert challenge_id not in manager.pending
            assert challenge_id not in manager._expiry_handles
        asyncio.run(scenario())
    finally:
        auth.request_vk_token = original
