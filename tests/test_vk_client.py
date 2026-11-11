import asyncio

import pytest

from app.vk.client import resolve_track


def test_track_resolution_rejects_malformed_ids_before_calling_vk() -> None:
    class UnexpectedService:
        async def get_songs_by_id_async(self, track_ids):
            raise AssertionError("VK must not be called for malformed track IDs")

    async def scenario():
        for track_id in ("", "1", "1_two", "1_2_extra", "1_2?url=https://evil"):
            with pytest.raises(ValueError, match="идентификатор"):
                await resolve_track(UnexpectedService(), track_id)

    asyncio.run(scenario())
