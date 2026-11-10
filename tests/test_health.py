from fastapi.testclient import TestClient
from app.main import app

def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_auth_is_explicitly_unconfigured() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False


def test_search_api_returns_pagination_metadata(monkeypatch) -> None:
    import app.api.routes as routes

    async def fake_search(service, query, limit, offset):
        assert query == "test song"
        assert limit == 2
        assert offset == 0
        return [
            {"id": "1_1", "title": "First", "artist": "Artist", "duration": 120},
            {"id": "1_2", "title": "Second", "artist": "Artist", "duration": 130},
        ]

    monkeypatch.setattr(routes, "get_credentials", lambda path: {
        "access_token": "test-token", "user_agent": "test-agent", "user_id": "123"
    })
    monkeypatch.setattr(routes, "make_service", lambda credentials: object())
    monkeypatch.setattr(routes, "search_tracks", fake_search)

    with TestClient(app) as client:
        response = client.get("/api/v1/search?q=test%20song&limit=2&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True
    assert payload["query"] == "test song"
