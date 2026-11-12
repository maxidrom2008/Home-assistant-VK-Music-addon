"""WebSocket event channel for live player and authentication updates."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.version import VERSION

router = APIRouter()


class EventHub:
    """Fan out state-change events to connected Home Assistant clients."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._snapshots: dict[str, dict] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        await websocket.send_json({"type": "server.ready", "version": VERSION})
        # A client may have missed events while disconnected. Send the latest
        # known state immediately after the handshake so its UI can resync.
        for event, data in self._snapshots.items():
            await websocket.send_json({"type": event, "data": data})

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def publish(self, event: str, data: dict | None = None) -> None:
        payload = data or {}
        if event == "playback.state":
            self._snapshots[event] = dict(payload)
        message = {"type": event, "data": payload}
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
