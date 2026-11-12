"""Short-lived in-memory cache for resolved VK audio stream URLs."""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable


class StreamUrlCache:
    """Reuse a signed VK URL during a track's active playback session."""

    def __init__(
        self,
        ttl_seconds: float = 600.0,
        max_entries: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[tuple[str, str], tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _token_key(access_token: str) -> str:
        return hashlib.sha256(access_token.encode("utf-8")).hexdigest()

    async def get_or_resolve(
        self,
        access_token: str,
        track_id: str,
        resolver: Callable[[], Awaitable[str]],
        *,
        force_refresh: bool = False,
    ) -> str:
        """Return a cached URL for seeks, or resolve a fresh URL for new playback."""
        key = (self._token_key(access_token), track_id)
        async with self._lock:
            now = self._clock()
            cached = self._entries.get(key)
            if not force_refresh and cached is not None and cached[0] > now:
                return cached[1]

            url = await resolver()
            if not url:
                raise ValueError("VK вернул пустой адрес аудиопотока")

            expires_at = self._clock() + self._ttl_seconds
            self._entries[key] = (expires_at, url)
            self._remove_expired(self._clock())
            while len(self._entries) > self._max_entries:
                oldest_key = min(self._entries, key=lambda item: self._entries[item][0])
                self._entries.pop(oldest_key, None)
            return url

    def clear_for_token(self, access_token: str) -> None:
        """Remove cached signed URLs belonging to a disconnected VK account."""
        token_key = self._token_key(access_token)
        for key in list(self._entries):
            if key[0] == token_key:
                self._entries.pop(key, None)

    def _remove_expired(self, now: float) -> None:
        for key, (expires_at, _) in list(self._entries.items()):
            if expires_at <= now:
                self._entries.pop(key, None)
