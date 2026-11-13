"""Opaque, same-origin proxy for VK HLS playlists, segments and encryption keys."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx


class HlsProxyError(ValueError):
    """A playlist or upstream resource cannot be safely proxied."""


@dataclass
class HlsResource:
    body: bytes
    content_type: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _Session:
    origin_host: str
    user_agent: str
    token_fingerprint: str
    resources: dict[str, str]
    expires_at: float


_URI_ATTRIBUTE = re.compile(r'URI=(["\'])(.*?)\1', re.IGNORECASE)
_PLAYLIST_TYPES = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl")


class HlsProxy:
    """Stores upstream URLs server-side and exposes only opaque local resource IDs."""

    def __init__(self, ttl_seconds: int = 3600, max_sessions: int = 64, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.clock = clock
        self._sessions: dict[str, _Session] = {}

    def create_session(self, url: str, user_agent: str, token_fingerprint: str) -> tuple[str, str]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise HlsProxyError("VK вернул некорректный HLS URL")
        self._prune()
        if len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions, key=lambda key: self._sessions[key].expires_at)
            self._sessions.pop(oldest, None)
        session_id = uuid.uuid4().hex
        resource_id = uuid.uuid4().hex
        self._sessions[session_id] = _Session(
            origin_host=parsed.hostname.lower(),
            user_agent=user_agent,
            token_fingerprint=token_fingerprint,
            resources={resource_id: url},
            expires_at=self.clock() + self.ttl_seconds,
        )
        return session_id, resource_id

    def clear_for_token(self, token_fingerprint: str) -> None:
        self._sessions = {
            key: value for key, value in self._sessions.items()
            if value.token_fingerprint != token_fingerprint
        }

    def _prune(self) -> None:
        now = self.clock()
        self._sessions = {
            key: value for key, value in self._sessions.items()
            if value.expires_at > now
        }

    def _session(self, session_id: str, token_fingerprint: str) -> _Session:
        self._prune()
        session = self._sessions.get(session_id)
        if session is None or session.token_fingerprint != token_fingerprint:
            raise KeyError("HLS session not found")
        return session

    @staticmethod
    def _is_playlist(url: str, content_type: str) -> bool:
        return urlsplit(url).path.lower().endswith(".m3u8") or any(
            value in content_type.lower() for value in _PLAYLIST_TYPES
        )

    def _local_url(self, session_id: str, session: _Session, base_url: str, reference: str) -> str:
        target = urljoin(base_url, reference.strip())
        parsed = urlsplit(target)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname.lower() != session.origin_host
            or parsed.username
            or parsed.password
        ):
            raise HlsProxyError("HLS playlist содержит внешний или небезопасный URL")
        resource_id = uuid.uuid4().hex
        session.resources[resource_id] = target
        return f"/api/v1/hls/{session_id}/{resource_id}"

    def rewrite_playlist(self, session_id: str, token_fingerprint: str, base_url: str, text: str) -> str:
        session = self._session(session_id, token_fingerprint)
        rewritten: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                rewritten.append(line)
            elif stripped.startswith("#"):
                def replace_uri(match: re.Match[str]) -> str:
                    local = self._local_url(session_id, session, base_url, match.group(2))
                    return f"URI={match.group(1)}{local}{match.group(1)}"
                rewritten.append(_URI_ATTRIBUTE.sub(replace_uri, line))
            else:
                rewritten.append(self._local_url(session_id, session, base_url, stripped))
        return "\n".join(rewritten) + ("\n" if text.endswith("\n") else "")

    async def fetch(
        self,
        session_id: str,
        resource_id: str,
        token_fingerprint: str,
        range_header: str | None = None,
    ) -> HlsResource:
        session = self._session(session_id, token_fingerprint)
        url = session.resources.get(resource_id)
        if not url:
            raise KeyError("HLS resource not found")
        headers = {"User-Agent": session.user_agent}
        if range_header:
            headers["Range"] = range_header
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=False) as client:
            response = await client.get(url, headers=headers)
        if response.status_code not in (200, 206):
            raise HlsProxyError(f"VK CDN вернул HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "application/octet-stream")
        body = response.content
        result_headers = {
            key: response.headers[key]
            for key in ("content-range", "accept-ranges", "content-length")
            if key in response.headers
        }
        if self._is_playlist(url, content_type):
            playlist = self.rewrite_playlist(
                session_id, token_fingerprint, url, body.decode("utf-8-sig")
            )
            body = playlist.encode("utf-8")
            content_type = "application/vnd.apple.mpegurl"
            result_headers.pop("content-length", None)
        return HlsResource(body, content_type, response.status_code, result_headers)
