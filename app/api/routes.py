"""Versioned REST API routes."""
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/api/v1")

@router.get("/status")
async def api_status() -> dict[str, str]:
    return {"status": "ok", "product": "VK Music Server", "version": "0.1.0"}

@router.get("/auth/status")
async def auth_status() -> dict[str, object]:
    return {"authenticated": False, "state": "not_configured", "challenge": None}

@router.get("/library/tracks")
async def library_tracks(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, object]:
    return {"items": [], "limit": limit, "offset": offset, "total": 0, "available": False}

@router.get("/playlists")
async def playlists(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, object]:
    return {"items": [], "limit": limit, "offset": offset, "total": 0, "available": False}

@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, object]:
    return {"query": q, "items": [], "limit": limit, "offset": offset, "total": 0, "available": False}

@router.get("/playback/state")
async def playback_state() -> dict[str, object]:
    return {"state": "idle", "mode": None, "track": None, "output": None}

@router.get("/tracks/{track_id}/stream")
async def track_stream(track_id: str) -> None:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="VK stream adapter is not implemented yet")
