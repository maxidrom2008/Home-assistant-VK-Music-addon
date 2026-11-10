from app.vk.auth import build_auth_request


def test_vk_auth_requests_offline_scope_without_forcing_sms() -> None:
    request = build_auth_request("user@example.invalid", "temporary-test-password")
    assert request.params["scope"] == "audio,offline"
    assert "force_sms" not in request.params
