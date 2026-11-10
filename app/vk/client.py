"""Thin adapter over vkpymusic; temporary stream URLs stay server-side."""
from typing import Any

from vkpymusic import Service, VkMobileClient


def make_service(credentials: dict[str, Any]) -> Service:
    return Service(
        user_agent=str(credentials["user_agent"] or VkMobileClient.user_agent),
        token=str(credentials["access_token"]),
    )


def song_to_dict(song: Any) -> dict[str, Any]:
    owner_id = str(getattr(song, "owner_id", ""))
    track_id = str(getattr(song, "track_id", ""))
    return {
        "id": f"{owner_id}_{track_id}",
        "owner_id": owner_id,
        "track_id": track_id,
        "title": str(getattr(song, "title", "") or ""),
        "artist": str(getattr(song, "artist", "") or ""),
        "duration": int(getattr(song, "duration", 0) or 0),
        "has_stream": bool(getattr(song, "url", None)),
    }


def playlist_to_dict(item: Any) -> dict[str, Any]:
    return {
        "id": f"{getattr(item, 'owner_id', '')}_{getattr(item, 'playlist_id', '')}",
        "owner_id": str(getattr(item, "owner_id", "")),
        "playlist_id": str(getattr(item, "playlist_id", "")),
        "title": str(getattr(item, "title", "") or ""),
        "description": str(getattr(item, "description", "") or ""),
        "photo": str(getattr(item, "photo", "") or ""),
    }


async def list_my_tracks(service: Service, limit: int, offset: int) -> list[dict[str, Any]]:
    user = await service.get_user_info_async()
    songs = await service.get_songs_by_userid_async(user.userid, count=limit, offset=offset)
    return [song_to_dict(song) for song in songs]


async def search_tracks(service: Service, query: str, limit: int, offset: int) -> list[dict[str, Any]]:
    songs = await service.search_songs_by_text_async(query, count=limit, offset=offset)
    return [song_to_dict(song) for song in songs]


async def list_playlists(service: Service, limit: int, offset: int) -> list[dict[str, Any]]:
    user = await service.get_user_info_async()
    items = await service.get_playlists_by_userid_async(user.userid, count=limit, offset=offset)
    return [playlist_to_dict(item) for item in items]


async def resolve_track(service: Service, track_id: str) -> dict[str, Any]:
    parts = track_id.split("_", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("Некорректный идентификатор VK-трека")
    songs = await service.get_songs_by_id_async([track_id])
    if not songs or not getattr(songs[0], "url", None):
        raise LookupError("VK не предоставил аудиопоток для этого трека")
    return {
        "track": song_to_dict(songs[0]),
        "stream_url": str(songs[0].url),
    }


async def resolve_stream(service: Service, track_id: str) -> str:
    result = await resolve_track(service, track_id)
    return result["stream_url"]
