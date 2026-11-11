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


def test_web_player_script_is_served() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/app.js")
    assert page.status_code == 200
    assert 'src="app.js"' in page.text
    assert script.status_code == 200
    assert "loadTracks" in script.text
    assert "playTrack" in script.text
    assert "CaptchaWidget" in script.text


def test_playlist_tracks_endpoint_keeps_playlist_access_key_server_side(monkeypatch) -> None:
    import app.api.routes as routes

    captured = []

    async def fake_playlist_tracks(service, owner_id, playlist_id, limit, offset):
        captured.append((owner_id, playlist_id, limit, offset))
        return [{"id": "42_7", "title": "Playlist song", "artist": "Artist", "duration": 200}]

    monkeypatch.setattr(routes, "get_credentials", lambda path: {
        "access_token": "test-token", "user_agent": "test-agent", "user_id": "42"
    })
    monkeypatch.setattr(routes, "make_service", lambda credentials: object())
    monkeypatch.setattr(routes, "list_playlist_tracks", fake_playlist_tracks)

    with TestClient(app) as client:
        response = client.get("/api/v1/playlists/42_123/tracks?limit=10&offset=20")

    assert response.status_code == 200
    assert captured == [("42", "123", 10, 20)]
    assert response.json()["has_more"] is False
    assert "access_key" not in response.text



def test_supervisor_internal_connection_details_are_returned_only_when_available() -> None:
    with TestClient(app) as client:
        app.state.supervisor_info = {
            "hostname": "repo-vk-music-server",
            "slug": "repo_vk_music_server",
        }
        response = client.get(
            "/api/v1/integration/info",
            headers={"host":"repo-vk-music-server:8099"},
        )

    assert response.status_code == 200
    assert response.json()["base_url"] == "http://repo-vk-music-server:8099"
    assert response.json()["available"] is True



def test_browser_script_has_no_runtime_external_captcha_cdn_dependency() -> None:
    from pathlib import Path

    script = Path("app/web/app.js").read_text(encoding="utf-8")
    assert 'from "@vkid/captcha"' in script
    assert "esm.sh" not in script



def test_auth_status_distinguishes_vk_network_failure_from_invalid_token(monkeypatch) -> None:
    import app.api.routes as routes

    class UnreachableVK:
        async def is_token_valid_async(self):
            raise RuntimeError("temporary network failure")

    monkeypatch.setattr(routes, "get_credentials", lambda path: {
        "access_token": "saved-token",
        "user_agent": "test-agent",
        "user_id": "123",
        "updated_at": "2026-11-11T00:00:00Z",
    })
    monkeypatch.setattr(routes, "make_service", lambda credentials: UnreachableVK())

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is False
    assert payload["token_saved"] is True
    assert payload["state"] == "validation_unavailable"
    assert payload["user_id"] == "123"
