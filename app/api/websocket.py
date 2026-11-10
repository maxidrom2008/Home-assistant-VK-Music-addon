"""WebSocket event channel."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

@router.websocket("/api/v1/events")
async def events(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await websocket.send_json({"type": "server.ready", "version": "0.1.0"})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
