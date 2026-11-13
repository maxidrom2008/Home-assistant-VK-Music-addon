"""Versioned REST API."""
import hashlib
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from vkpymusic import Service, VkMobileClient
from vkpymusic.vk_api import VkApiException

from app.playback.manager import PlaybackError
from app.playback.stream import proxy_audio
from app.storage.database import delete_credentials, get_credentials
from app.vk.auth import VKAuthError
from app.version import VERSION
from app.vk.stream_cache import StreamUrlCache
from app.vk.hls_proxy import HlsProxy, HlsProxyError
from app.vk.client import (
    list_my_tracks,
    list_playlists,
    list_playlist_tracks,
    make_service,
    resolve_stream,
    resolve_track,
    search_tracks,
)

router = APIRouter(prefix="/api/v1")
_STREAM_URL_CACHE = StreamUrlCache()
_HLS_PROXY = HlsProxy()


async def _publish_event(request: Request, event: str, data: dict[str, object]) -> None:
    hub = getattr(request.app.state, "event_hub", None)
    if hub is not None:
        await hub.publish(event, data)


class AuthStart(BaseModel):
    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class AuthChallenge(BaseModel):
    challenge_id: str = Field(min_length=16, max_length=128)
    answer: str = Field(default="", max_length=8192)
    approved: bool = False


class AuthChallengeRefresh(BaseModel):
    challenge_id: str = Field(min_length=16, max_length=128)


class TokenImport(BaseModel):
    access_token: str = Field(min_length=5, max_length=4096)


class ServerPlaybackRequest(BaseModel):
    track_id: str = Field(pattern=r"^-?[0-9]+_-?[0-9]+$", max_length=64)
    output_device: str = Field(default="default", min_length=1, max_length=512)


class ServerPlaybackSeekRequest(BaseModel):
    position: float = Field(ge=0.0, le=86400.0)
    output_device: str = Field(default="default", min_length=1, max_length=512)


class ServerPlaybackEqualizerRequest(BaseModel):
    output_device: str = Field(default="default", min_length=1, max_length=512)
    bass: float = Field(default=0.0, ge=-12.0, le=12.0)
    low_mid: float = Field(default=0.0, ge=-12.0, le=12.0)
    mid: float = Field(default=0.0, ge=-12.0, le=12.0)
    high_mid: float = Field(default=0.0, ge=-12.0, le=12.0)
    treble: float = Field(default=0.0, ge=-12.0, le=12.0)


class PlaybackOutputRequest(BaseModel):
    device: str = Field(min_length=1, max_length=512)


class PlaybackVolumeRequest(BaseModel):
    volume: float = Field(ge=0.0, le=1.0)
    output_device: str = Field(default="default", min_length=1, max_length=512)


@router.get("/integration/info")
async def integration_info(request: Request) -> dict[str, object]:
    """Return the private hostname needed by the companion HA integration."""
    info = getattr(request.app.state, "supervisor_info", {})
    hostname = info.get("hostname")
    return {
        "available": bool(hostname),
        "hostname": hostname,
        "base_url": f"http://{hostname}:8099" if hostname else None,
        "port": 8099,
        "network": "Home Assistant internal network only",
    }


@router.get("/status")
async def api_status() -> dict[str, str]:
    return {"status": "ok", "product": "VK Music Server", "version": VERSION}


@router.get("/auth/status")
async def auth_status(request: Request) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        return {"authenticated": False, "state": "not_configured", "user_id": None}
    try:
        valid = bool(await make_service(credentials).is_token_valid_async())
    except Exception as exc:
        # vkpymusic maps VK API rejections to False, but transport errors escape.
        # Do not tell users their token is invalid during a VK/network outage.
        return {
            "authenticated": False,
            "token_saved": True,
            "state": "validation_unavailable",
            "user_id": credentials.get("user_id"),
            "updated_at": credentials.get("updated_at"),
            "delete_available": True,
            "error": f"Не удалось связаться с VK для проверки токена ({type(exc).__name__})",
        }
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
        result = await request.app.state.auth_manager.start(payload.login, payload.password)
        await _publish_event(request, "auth.state", {
            "state": result.get("state"),
            "authenticated": result.get("authenticated", False),
        })
        return result
    except (ValueError, VKAuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/challenge")
async def auth_challenge(payload: AuthChallenge, request: Request) -> dict[str, object]:
    try:
        result = await request.app.state.auth_manager.submit(
            payload.challenge_id, payload.answer, approved=payload.approved
        )
        await _publish_event(request, "auth.state", {
            "state": result.get("state"),
            "authenticated": result.get("authenticated", False),
            "user_id": result.get("user_id"),
        })
        return result
    except (ValueError, VKAuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/challenge/refresh")
async def auth_challenge_refresh(
    payload: AuthChallengeRefresh,
    request: Request,
) -> dict[str, object]:
    try:
        return await request.app.state.auth_manager.refresh_captcha(payload.challenge_id)
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
    result = {"state": "authenticated", "authenticated": True, "user_id": user_id or None}
    await _publish_event(request, "auth.state", result)
    return result


@router.delete("/auth/challenge/{challenge_id}")
async def auth_challenge_cancel(challenge_id: str, request: Request) -> dict[str, bool]:
    return {"cancelled": request.app.state.auth_manager.cancel(challenge_id)}


@router.delete("/auth/token")
async def auth_delete(request: Request) -> dict[str, object]:
    request.app.state.auth_manager.cancel_all()
    await request.app.state.playback_manager.stop_all()
    credentials = get_credentials(request.app.state.database_path)
    if credentials:
        token = str(credentials.get("access_token") or "")
        _STREAM_URL_CACHE.clear_for_token(token)
        _HLS_PROXY.clear_for_token(hashlib.sha256(token.encode()).hexdigest())
    deleted = delete_credentials(request.app.state.database_path)
    result = {"deleted": deleted, "authenticated": False, "state": "not_configured"}
    await _publish_event(request, "auth.state", result)
    for state in request.app.state.playback_manager.get_states():
        await _publish_event(request, "playback.state", state)
    return result


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


@router.get("/playlists/{owner_id}_{playlist_id}/tracks")
async def playlist_tracks(
    owner_id: str,
    playlist_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK в настройках")
    try:
        items = await list_playlist_tracks(
            make_service(credentials), owner_id, playlist_id, limit, offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc
    return {
        "items": items, "limit": limit, "offset": offset,
        "available": True, "has_more": len(items) == limit,
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
    return {
        "query": q, "items": items, "limit": limit, "offset": offset,
        "available": True, "has_more": len(items) == limit,
    }


@router.get("/playback/outputs")
async def playback_outputs(request: Request) -> dict[str, object]:
    try:
        return await request.app.state.playback_manager.list_outputs()
    except PlaybackError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/playback/output")
async def playback_select_output(
    payload: PlaybackOutputRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await request.app.state.playback_manager.select_output(payload.device)
    except PlaybackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/playback/volume")
async def playback_set_volume(payload: PlaybackVolumeRequest, request: Request) -> dict[str, object]:
    try:
        return await request.app.state.playback_manager.set_volume(
            payload.volume, output_device=payload.output_device
        )
    except PlaybackError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/playback/state")
async def playback_state(
    request: Request, output_device: str | None = Query(default=None, max_length=512)
) -> dict[str, object]:
    return request.app.state.playback_manager.get_state(output_device)


@router.get("/playback/states")
async def playback_states(request: Request) -> dict[str, object]:
    return {"zones": request.app.state.playback_manager.get_states()}


@router.post("/playback/server/play")
async def playback_server_play(
    payload: ServerPlaybackRequest,
    request: Request,
) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK")
    try:
        resolved = await resolve_track(make_service(credentials), payload.track_id)
        state = await request.app.state.playback_manager.play(
            resolved["stream_url"],
            credentials["user_agent"],
            resolved["track"],
            output_device=payload.output_device,
        )
        await _publish_event(request, "playback.state", state)
        return state
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlaybackError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc


async def _restart_server_zone(
    request: Request, output_device: str, position: float, equalizer: dict[str, float] | None = None
) -> dict[str, object]:
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK")
    manager = request.app.state.playback_manager
    current = manager.get_state(output_device)
    track = current.get("track")
    if not isinstance(track, dict) or not track.get("id"):
        raise HTTPException(status_code=409, detail="В этой зоне сейчас нет активного трека")
    try:
        if equalizer is not None:
            await manager.set_equalizer(equalizer, output_device)
        resolved = await resolve_track(make_service(credentials), str(track["id"]))
        duration = max(0.0, float(resolved["track"].get("duration") or 0))
        target = min(max(0.0, float(position)), duration) if duration else max(0.0, float(position))
        was_paused = current.get("state") == "paused"
        state = await manager.play(
            resolved["stream_url"], credentials["user_agent"], resolved["track"],
            output_device=output_device, start_seconds=target,
        )
        if was_paused and state.get("state") == "playing":
            state = await manager.pause(output_device)
        await _publish_event(request, "playback.state", state)
        return state
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlaybackError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc


@router.post("/playback/server/seek")
async def playback_server_seek(
    payload: ServerPlaybackSeekRequest, request: Request
) -> dict[str, object]:
    return await _restart_server_zone(
        request, payload.output_device, payload.position
    )


@router.post("/playback/server/equalizer")
async def playback_server_equalizer(
    payload: ServerPlaybackEqualizerRequest, request: Request
) -> dict[str, object]:
    manager = request.app.state.playback_manager
    current = manager.get_state(payload.output_device)
    bands = {
        "bass": payload.bass, "low_mid": payload.low_mid, "mid": payload.mid,
        "high_mid": payload.high_mid, "treble": payload.treble,
    }
    if current.get("state") not in ("playing", "paused") or not current.get("track"):
        state = await manager.set_equalizer(bands, payload.output_device)
        await _publish_event(request, "playback.state", state)
        return state
    return await _restart_server_zone(
        request, payload.output_device, float(current.get("position") or 0), bands
    )


@router.post("/playback/server/pause")
async def playback_server_pause(
    request: Request, output_device: str = Query(default="default", max_length=512)
) -> dict[str, object]:
    try:
        state = await request.app.state.playback_manager.pause(output_device)
        await _publish_event(request, "playback.state", state)
        return state
    except PlaybackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/playback/server/resume")
async def playback_server_resume(
    request: Request, output_device: str = Query(default="default", max_length=512)
) -> dict[str, object]:
    try:
        state = await request.app.state.playback_manager.resume(output_device)
        await _publish_event(request, "playback.state", state)
        return state
    except PlaybackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/playback/server/stop")
async def playback_server_stop(
    request: Request, output_device: str = Query(default="default", max_length=512)
) -> dict[str, object]:
    state = await request.app.state.playback_manager.stop(output_device)
    await _publish_event(request, "playback.state", state)
    return state


@router.get("/tracks/{track_id}/stream")
async def track_stream(
    track_id: str,
    request: Request,
    start: float = Query(0.0, ge=0.0, le=86400.0),
):
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK")
    try:
        service = make_service(credentials)
        url = await _STREAM_URL_CACHE.get_or_resolve(
            str(credentials["access_token"]),
            track_id,
            lambda: resolve_stream(service, track_id),
            # A start-at-zero request begins a new play action and refreshes the
            # signed URL. Offset requests reuse it instead of querying VK again.
            force_refresh=start <= 0.0,
        )
        return await proxy_audio(
            url, credentials["user_agent"], request.headers.get("range"), start_seconds=start
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc


@router.post("/tracks/{track_id}/hls")
async def create_track_hls_session(track_id: str, request: Request) -> dict[str, str]:
    """Create a short-lived browser HLS session; signed VK URLs remain server-side."""
    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK")
    try:
        service = make_service(credentials)
        url = await _STREAM_URL_CACHE.get_or_resolve(
            str(credentials["access_token"]),
            track_id,
            lambda: resolve_stream(service, track_id),
            force_refresh=True,
        )
        fingerprint = hashlib.sha256(str(credentials["access_token"]).encode()).hexdigest()
        session_id, resource_id = _HLS_PROXY.create_session(
            url, str(credentials["user_agent"]), fingerprint
        )
        return {
            "manifest_url": f"api/v1/hls/{session_id}/{resource_id}",
            "session_id": session_id,
        }
    except (ValueError, HlsProxyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VkApiException as exc:
        raise HTTPException(status_code=502, detail=f"VK API error {getattr(exc, 'error_code', 'unknown')}") from exc


@router.get("/hls/{session_id}/{resource_id}")
async def proxy_hls_resource(
    session_id: str,
    resource_id: str,
    request: Request,
):
    """Proxy a playlist, media segment, initialization map or AES key."""
    from fastapi.responses import Response

    credentials = get_credentials(request.app.state.database_path)
    if not credentials:
        raise HTTPException(status_code=401, detail="Сначала подключите VK")
    fingerprint = hashlib.sha256(str(credentials["access_token"]).encode()).hexdigest()
    try:
        resource = await _HLS_PROXY.fetch(
            session_id, resource_id, fingerprint, request.headers.get("range")
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="HLS-сессия истекла или недоступна") from exc
    except HlsProxyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    headers.update(resource.headers)
    return Response(
        content=resource.body,
        status_code=resource.status_code,
        media_type=resource.content_type,
        headers=headers,
    )
