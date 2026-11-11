from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app


def test_manual_token_import_validates_and_persists_token(monkeypatch) -> None:
    import app.api.routes as routes
    import app.storage.database as database

    persisted = []

    class FakeService:
        def __init__(self, *, user_agent: str, token: str) -> None:
            assert token == "valid-test-token"
            assert user_agent

        async def is_token_valid_async(self) -> bool:
            return True

        async def get_user_info_async(self):
            return SimpleNamespace(userid=2468)

    monkeypatch.setattr(routes, "Service", FakeService)
    monkeypatch.setattr(
        database,
        "save_credentials",
        lambda path, token, user_agent, user_id: persisted.append(
            (token, user_agent, user_id)
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/token",
            json={"access_token": "valid-test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "state": "authenticated",
        "authenticated": True,
        "user_id": "2468",
    }
    assert persisted == [("valid-test-token", routes.VkMobileClient.user_agent, "2468")]


def test_manual_token_import_rejects_invalid_token_without_persisting(monkeypatch) -> None:
    import app.api.routes as routes
    import app.storage.database as database

    class FakeService:
        def __init__(self, *, user_agent: str, token: str) -> None:
            pass

        async def is_token_valid_async(self) -> bool:
            return False

    monkeypatch.setattr(routes, "Service", FakeService)
    monkeypatch.setattr(
        database,
        "save_credentials",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("Invalid tokens must never be persisted")
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/token",
            json={"access_token": "invalid-test-token"},
        )

    assert response.status_code == 400
    assert "не принимает" in response.json()["detail"]


def test_deleting_token_stops_server_playback(monkeypatch) -> None:
    import app.api.routes as routes

    stopped = []

    async def fake_stop():
        stopped.append(True)
        return {"state": "idle"}

    monkeypatch.setattr(routes, "delete_credentials", lambda path: True)

    with TestClient(app) as client:
        app.state.playback_manager.stop = fake_stop
        response = client.delete("/api/v1/auth/token")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert stopped == [True]
