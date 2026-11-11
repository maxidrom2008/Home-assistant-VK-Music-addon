from fastapi.testclient import TestClient

from app.main import app


def test_websocket_supports_ping_and_broadcasts_playback_changes() -> None:
    async def fake_stop():
        return {
            "state": "idle",
            "mode": "server",
            "track": None,
            "position": 0,
        }

    with TestClient(app) as client:
        app.state.playback_manager.stop = fake_stop
        with client.websocket_connect("/api/v1/events") as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "server.ready"

            websocket.send_text("ping")
            assert websocket.receive_json()["type"] == "server.pong"

            response = client.post("/api/v1/playback/server/stop")
            assert response.status_code == 200
            event = websocket.receive_json()
            assert event["type"] == "playback.state"
            assert event["data"]["state"] == "idle"
