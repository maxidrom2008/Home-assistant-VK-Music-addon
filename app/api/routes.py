"""Versioned REST API."""
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from vkpymusic import Service, VkMobileClient
from vkpymusic.vk_api import VkApiException

from app.playback.stream import proxy_audio
from app.storage.database import delete_credentials, get_credentials
from app.vk.auth import VKAuthError
from app.vk.client import (
    list_my_tracks,
    list_playlists,
    make_service,
    resolve_stream,
    search_tracks,
)

router = APIRouter(prefix="/api/v1")


class AuthStart(BaseModel):
    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class AuthChallenge(BaseModel):
    challenge_id: str = Field(min_length=16, max_length=128)
    answer: str = Field(min_length=1, max_length=128)


class TokenImport(BaseModel):
    access_token: str = Field(min_length=5, max_length=4096)


@router.get("/status")
async def api_status() -> dict[str, str]:
    return {"status": "ok", "product": "VK Music Server", "version": "0.1.1"}


@router.get("/auth/status")
async def auth_status(request: Request) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        return {"authenticated": False, "state": "not_configured", "user_id": None}
    try:
        valid = bool(await make_service(credentials).is_token_valid_async())
    except Exception:
        valid = False
    return {
        "authenticated": valid,
        "token_saved": True,
        "state": "connected" if valid else "token_saved_but_invalid",
        "user_id": credentials.get("user_id"),
        "updated_at": credentials.get("updated_at"),
        "delete_available": True,
    }


@router.post("/auth/start")
async def auth_start(payload: AuthStart, request: Request) -> dict[str, object]:
    try:
        return await request.app.state.auth_manager.start(payload.login, payload.password)
    except (ValueError, VKAuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/challenge")
async def auth_challenge(payload: AuthChallenge, request: Request) -> dict[str, object]:
    try:
        return await request.app.state.auth_manager.submit(payload.challenge_id, payload.answer)
    except (ValueError, VKAuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/token")
async def auth_token_import(payload: TokenImport, request: Request) -> dict[str, object]:
    token = payload.access_token.strip()
    service = Service(user_agent=VkMobileClient.user_agent, token=token)
    try:
        if not await service.is_token_valid_async():
            raise HTTPException(status_code=400, detail="VK не принимает этот токен")
        user = await service.get_user_info_async()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось проверить токен VK ({type(exc).__name__})",
        ) from exc
    user_id = str(getattr(user, "userid", "") or "")
    from app.storage.database import save_credentials
    save_credentials(
        request.app.state.database_path,
        token,
        VkMobileClient.user_agent,
        user_id or None,
    )
    request.app.state.auth_manager.cancel_all()
    return {"state": "authenticated", "authenticated": True, "user_id": user_id or None}


@router.delete("/auth/challenge/{challenge_id}")
async def auth_challenge_cancel(challenge_id: str, request: Request) -> dict[str, bool]:
    return {"cancelled": request.app.state.auth_manager.cancel(challenge_id)}


@router.delete("/auth/token")
async def auth_delete(request: Request) -> dict[str, object]:
    request.app.state.auth_manager.cancel_all()
    deleted = delete_credentials(request.app.state.database_path)
    return {"deleted": deleted, "authenticated": False, "state": "not_configured"}


@router.get("/library/tracks")
async def library_tracks(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK в настройках")
    try:
        items = await list_my_tracks(make_service(credentials), limit, offset)
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc
    return {
        "items": items, "limit": limit, "offset": offset, "available": True,
        "has_more": len(items) == limit,
    }


@router.get("/playlists")
async def playlists(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK в настройках")
    try:
        items = await list_playlists(make_service(credentials), limit, offset)
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc
    return {
        "items": items, "limit": limit, "offset": offset, "available": True,
        "has_more": len(items) == limit,
    }


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK в настройках")
    try:
        items = await search_tracks(make_service(credentials), q, limit, offset)
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc
    return {"query": q, "items": items, "limit": limit, "offset": offset, "available": True}


@router.get("/playback/state")
async def playback_state() -> dict[str, object]:
    return {"state": "idle", "mode": "client_stream", "track": None, "output": None}


@router.get("/tracks/{track_id}/stream")
async def track_stream(track_id: str, request: Request):
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK")
    try:
        service = make_service(credentials)
        url = await resolve_stream(service, track_id)
        return await proxy_audio(url, credentials["user_agent"], request.headers.get("range"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc
