"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.routes import router as api_router
from app.api.websocket import router as websocket_router
from app.config import settings
from app.security import IngressOnlyMiddleware
from app.storage.database import initialize
from app.vk.auth import VKAuthManager

WEB_ROOT = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    initialize(settings.database_path)
    app.state.database_path = settings.database_path
    app.state.auth_manager = VKAuthManager(settings.database_path)
    yield
    app.state.auth_manager.cancel_all()


app = FastAPI(title="VK Music Server", version="0.1.1", lifespan=lifespan)
app.add_middleware(IngressOnlyMiddleware)
app.include_router(api_router)
app.include_router(websocket_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root():
    return FileResponse(WEB_ROOT / "index.html")
