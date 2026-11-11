"""FastAPI application entry point."""
from contextlib import asynccontextmanager
import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.routes import router as api_router
from app.api.websocket import EventHub, router as websocket_router
from app.config import settings
from app.playback.manager import ServerPlaybackManager
from app.security import IngressOnlyMiddleware
from app.version import VERSION
from app.storage.database import initialize
from app.vk.auth import VKAuthManager

WEB_ROOT = Path(__file__).parent / "web"


async def supervisor_app_info() -> dict[str, str]:
    """Read this app's internal DNS name from the Supervisor API."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(
                "http://supervisor/addons/self/info",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            hostname = str(data.get("hostname") or "")
            if not hostname or not all(ch.isalnum() or ch in ".-" for ch in hostname):
                return {}
            return {
                "hostname": hostname,
                "slug": str(data.get("slug") or ""),
            }
    except (httpx.HTTPError, ValueError, TypeError):
        return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    initialize(settings.database_path)
    app.state.database_path = settings.database_path
    app.state.supervisor_info = await supervisor_app_info()
    app.state.auth_manager = VKAuthManager(settings.database_path)
    app.state.event_hub = EventHub()

    async def publish_playback_state(state: dict) -> None:
        await app.state.event_hub.publish("playback.state", state)

    app.state.playback_manager = ServerPlaybackManager(
        on_state_change=publish_playback_state
    )
    try:
        yield
    finally:
        app.state.auth_manager.cancel_all()
        await app.state.playback_manager.stop()


app = FastAPI(title="VK Music Server", version=VERSION, lifespan=lifespan)
app.add_middleware(IngressOnlyMiddleware)
app.include_router(api_router)
app.include_router(websocket_router)


@app.get("/")
async def root():
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/app.js")
async def web_app_script():
    bundle = WEB_ROOT / "app.bundle.js"
    return FileResponse(
        bundle if bundle.is_file() else WEB_ROOT / "app.js",
        media_type="text/javascript; charset=utf-8",
        headers={"cache-control": "no-cache"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
