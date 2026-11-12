"""Tests for the companion Home Assistant integration setup lifecycle."""
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class FakeVKMusicServerApiError(Exception):
    pass


class FakeConfigEntryNotReady(Exception):
    pass


def _load_integration(monkeypatch: pytest.MonkeyPatch, api_client_class):
    """Load the integration against tiny Home Assistant API stubs."""
    homeassistant = ModuleType("homeassistant")
    homeassistant.__path__ = []

    config_entries = ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})

    const = ModuleType("homeassistant.const")
    const.Platform = type("Platform", (), {"MEDIA_PLAYER": "media_player"})

    core = ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})

    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.ConfigEntryNotReady = FakeConfigEntryNotReady

    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.config_entries", config_entries)
    monkeypatch.setitem(sys.modules, "homeassistant.const", const)
    monkeypatch.setitem(sys.modules, "homeassistant.core", core)
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", exceptions)

    api = ModuleType("custom_components.vk_music_server.api")
    api.VKMusicServerApiClient = api_client_class
    api.VKMusicServerApiError = FakeVKMusicServerApiError
    const_module = ModuleType("custom_components.vk_music_server.const")
    const_module.DOMAIN = "vk_music_server"
    monkeypatch.setitem(sys.modules, api.__name__, api)
    monkeypatch.setitem(sys.modules, const_module.__name__, const_module)

    package_name = "custom_components.vk_music_server"
    package_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "vk_music_server"
        / "__init__.py"
    )
    spec = importlib.util.spec_from_file_location(
        package_name,
        package_path,
        submodule_search_locations=[str(package_path.parent)],
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, package_name, package)
    spec.loader.exec_module(package)
    return package


def test_integration_setup_requests_retry_when_addon_is_temporarily_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableApiClient:
        def __init__(self, base_url, hass) -> None:
            self.base_url = base_url

        async def get(self, path: str):
            assert path == "status"
            raise FakeVKMusicServerApiError("connection refused")

    integration = _load_integration(monkeypatch, UnavailableApiClient)
    hass = SimpleNamespace(data={}, config_entries=SimpleNamespace())
    entry = SimpleNamespace(
        data={"base_url": "http://repo-vk-music-server:8099"},
        entry_id="entry-1",
    )

    async def scenario():
        with pytest.raises(
            integration.ConfigEntryNotReady,
            match="VK Music Server is temporarily unavailable",
        ):
            await integration.async_setup_entry(hass, entry)

    asyncio.run(scenario())
    assert hass.data == {}
