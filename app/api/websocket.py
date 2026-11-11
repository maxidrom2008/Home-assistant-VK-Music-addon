"""WebSocket event channel for live player and authentication updates."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.version import VERSION

router = APIRouter()


class EventHub:
    """Fan out state-change events to connected Home Assistant clients."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        await websocket.send_json({"type": "server.ready", "version": VERSION})

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def publish(self, event: str, data: dict | None = None) -> None:
        message = {"type": event, "data": data or {}}
        stale: list[WebSocket] = []
        for websocket in tuple(self._clients):
            try:
                await websocket.send_json(message)
            except (OSError, RuntimeError, WebSocketDisconnect):
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


@router.websocket("/api/v1/events")
async def events(websocket: WebSocket) -> None:
    hub: EventHub = websocket.app.state.event_hub
    try:
        await hub.connect(websocket)
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "server.pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)
