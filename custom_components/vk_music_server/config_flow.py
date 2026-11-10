"""Config flow for VK Music Server."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VKMusicServerApiClient, VKMusicServerApiError
from .const import CONF_BASE_URL, DOMAIN


def normalize_base_url(value: str) -> str:
    """Validate and normalize the internal add-on URL."""
    value = value.strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError(
            "Enter a valid internal URL such as http://local-vk-music-server:8099"
        )
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("The URL contains an invalid port") from exc
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


class VKMusicServerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up the local VK Music Server add-on."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Ask for the add-on's internal Supervisor DNS URL."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url = normalize_base_url(user_input[CONF_BASE_URL])
                api = VKMusicServerApiClient(base_url, self.hass)
                info = await api.get("status")
                if info.get("product") != "VK Music Server":
                    errors["base"] = "not_vk_music_server"
                else:
                    await self.async_set_unique_id(base_url.casefold())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="VK Music Server",
                        data={CONF_BASE_URL: base_url},
                    )
            except ValueError:
                errors["base"] = "invalid_url"
            except VKMusicServerApiError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL): str,
                }
            ),
            errors=errors,
        )
