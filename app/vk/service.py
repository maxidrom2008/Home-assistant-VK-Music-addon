"""Thin async adapter around the supported vkpymusic Service API."""
from __future__ import annotations

from typing import Any

from vkpymusic import Service

from app.storage.credentials import load_credentials


class VKService:
    def __init__(self, service: Service) -> None:
        self._service = service

    @classmethod
    def from_storage(cls) -> "VKService | None":
        credentials = load_credentials()
        if not credentials:
            return None
        user_agent, token = credentials[1], credentials[0]
        return cls(Service(user_agent, token))

    async def search_tracks(self, query: str, limit: int, offset: int) -> list[dict[str, Any]]:
        songs = await self._service.search_songs_by_text_async(query, count=limit, offset=offset)
        return [song.to_dict() for song in songs]

    async def user_info(self) -> dict[str, Any]:
        info = await self._service.get_user_info_async()
        return info.to_dict() if hasattr(info, "to_dict") else vars(info)
