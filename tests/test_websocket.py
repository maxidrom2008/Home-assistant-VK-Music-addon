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

            initial_state = websocket.receive_json()
            assert initial_state["type"] == "playback.state"
            assert initial_state["data"]["state"] == "idle"

            websocket.send_text("ping")
            assert websocket.receive_json()["type"] == "server.pong"

            response = client.post("/api/v1/playback/server/stop")
            assert response.status_code == 200
            event = websocket.receive_json()
            assert event["type"] == "playback.state"
            assert event["data"]["state"] == "idle"


def test_websocket_new_client_receives_latest_playback_snapshot() -> None:
    snapshot = {
        "state": "playing",
        "mode": "server",
        "track": {"id": "123_456", "title": "Current track", "artist": "Artist"},
        "position": 42,
    }

    with TestClient(app) as client:
        import asyncio

        asyncio.run(app.state.event_hub.publish("playback.state", snapshot))
        with client.websocket_connect("/api/v1/events") as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "server.ready"

            initial_state = websocket.receive_json()
            assert initial_state["type"] == "playback.state"
            assert initial_state["data"] == snapshot


def test_websocket_reconnected_client_receives_latest_state_not_stale_events() -> None:
    first_snapshot = {"state": "paused", "track": {"id": "1_1"}, "position": 10}
    latest_snapshot = {"state": "playing", "track": {"id": "2_2"}, "position": 20}

    with TestClient(app) as client:
        import asyncio

        asyncio.run(app.state.event_hub.publish("playback.state", first_snapshot))
        asyncio.run(app.state.event_hub.publish("playback.state", latest_snapshot))
        with client.websocket_connect("/api/v1/events") as websocket:
            assert websocket.receive_json()["type"] == "server.ready"
            received = websocket.receive_json()
            assert received["type"] == "playback.state"
            assert received["data"] == latest_snapshot
