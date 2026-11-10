"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.routes import router as api_router
from app.api.websocket import router as websocket_router
from app.config import settings
from app.storage.database import initialize

@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    initialize(settings.database_path)
    yield

app = FastAPI(title="VK Music Server", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(websocket_router)

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "VK Music Server", "version": "0.1.0", "docs": "/docs"}
