"""Thin adapter over vkpymusic; temporary stream URLs stay server-side."""
from typing import Any
import re

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


async def list_playlist_tracks(
    service: Service,
    owner_id: str,
    playlist_id: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Resolve a user's playlist on the server so its access key stays private."""
    if not owner_id.lstrip("-").isdigit() or not playlist_id.isdigit():
        raise ValueError("Некорректный идентификатор плейлиста")
    user = await service.get_user_info_async()
    if str(user.userid) != owner_id:
        raise LookupError("Можно открывать только плейлисты текущего аккаунта")
    found = None
    playlist_offset = 0
    # Scan paginated playlist metadata without exposing access_key to the browser.
    while playlist_offset < 10_000:
        playlists = await service.get_playlists_by_userid_async(
            user.userid, count=100, offset=playlist_offset
        )
        if not playlists:
            break
        found = next(
            (
                item for item in playlists
                if str(getattr(item, "owner_id", "")) == owner_id
                and str(getattr(item, "playlist_id", "")) == playlist_id
            ),
            None,
        )
        if found is not None or len(playlists) < 100:
            break
        playlist_offset += len(playlists)
    if found is None:
        raise LookupError("Плейлист не найден в библиотеке VK")
    songs = await service.get_songs_by_playlist_id_async(
        found.owner_id,
        found.playlist_id,
        getattr(found, "access_key", "") or "",
        count=limit,
        offset=offset,
    )
    return [song_to_dict(song) for song in songs]


async def resolve_track(service: Service, track_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"-?\d+_-?\d+", track_id):
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
