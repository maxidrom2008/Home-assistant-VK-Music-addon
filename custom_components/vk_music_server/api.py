"""Async client for the private Home Assistant add-on API."""
from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession


class VKMusicServerApiError(Exception):
    """The VK Music Server API returned an error or could not be reached."""


class VKMusicServerApiClient:
    """Use the HA shared aiohttp session to contact the add-on over hassio DNS."""

    def __init__(self, base_url: str, hass: HomeAssistant) -> None:
        self.base_url = base_url.rstrip("/")
        self.session: ClientSession = async_get_clientsession(hass)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1/{path.lstrip('/')}"
        try:
            async with self.session.request(
                method,
                url,
                json=json,
                timeout=12,
            ) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    detail = (
                        payload.get("detail", f"HTTP {response.status}")
                        if isinstance(payload, dict)
                        else f"HTTP {response.status}"
                    )
                    raise VKMusicServerApiError(str(detail))
        except VKMusicServerApiError:
            raise
        except (ClientError, TimeoutError, ValueError) as exc:
            raise VKMusicServerApiError(
                f"Не удалось связаться с VK Music Server: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise VKMusicServerApiError("VK Music Server вернул неверный формат JSON")
        return payload

    async def get(self, path: str) -> dict[str, Any]:
        return await self.request("GET", path)

    async def post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("POST", path, json=json)
