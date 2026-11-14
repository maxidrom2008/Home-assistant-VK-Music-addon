"""Home Assistant media player for the VK Music Server."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.components.media_player.const import (
    MediaClass,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player.errors import BrowseError, SearchError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import VKMusicServerApiClient, VKMusicServerApiError
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the VK Music Server media player."""
    api: VKMusicServerApiClient = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VKMusicServerMediaPlayer(api, entry)])


class VKMusicServerMediaPlayer(MediaPlayerEntity):
    """A controllable player that outputs audio through the add-on's PulseAudio sink."""

    _attr_name = "VK Music Server"
    _attr_media_content_type = MediaType.MUSIC
    _attr_should_poll = True
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.SEARCH_MEDIA
    )

    def __init__(
        self,
        api: VKMusicServerApiClient,
        entry: ConfigEntry,
    ) -> None:
        self.api = api
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="VK Music Server",
            manufacturer="VK",
            model="Standalone music server",
            configuration_url=entry.data["base_url"],
        )
        self._connected = True
        self._state = MediaPlayerState.IDLE
        self._track: dict[str, Any] | None = None
        self._position = 0.0
        self._position_updated_at = datetime.now(timezone.utc)
        self._output = "Home Assistant Audio (PulseAudio)"
        self._output_device = "default"
        self._volume = 0.8
        self._error: str | None = None

    @property
    def available(self) -> bool:
        return self._connected

    @property
    def state(self) -> MediaPlayerState:
        return self._state

    @property
    def volume_level(self) -> float | None:
        return self._volume

    @property
    def media_title(self) -> str | None:
        return str(self._track.get("title") or "") if self._track else None

    @property
    def media_artist(self) -> str | None:
        return str(self._track.get("artist") or "") if self._track else None

    @property
    def media_duration(self) -> float | None:
        return float(self._track.get("duration") or 0) if self._track else None

    @property
    def media_position(self) -> float | None:
        if self._state == MediaPlayerState.PLAYING:
            return self._position + (
                datetime.now(timezone.utc) - self._position_updated_at
            ).total_seconds()
        return self._position

    @property
    def media_position_updated_at(self) -> datetime | None:
        return self._position_updated_at

    @property
    def media_content_id(self) -> str | None:
        return str(self._track.get("id")) if self._track else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"output": self._output, "output_device": self._output_device, "mode": "server", "error": self._error}

    async def async_update(self) -> None:
        """Refresh server playback state."""
        try:
            # This entity owns one selected HAOS zone. Do not follow the
            # add-on UI's global selector when polling the entity state.
            device = quote(self._output_device, safe="")
            data = await self.api.get(f"playback/state?output_device={device}")
        except VKMusicServerApiError as exc:
            self._connected = False
            self._error = str(exc)
            return

        self._connected = True
        state = data.get("state", "idle")
        self._state = {
            "playing": MediaPlayerState.PLAYING,
            "paused": MediaPlayerState.PAUSED,
            "buffering": MediaPlayerState.BUFFERING,
            "error": MediaPlayerState.IDLE,
        }.get(state, MediaPlayerState.IDLE)
        track = data.get("track")
        self._track = track if isinstance(track, dict) else None
        self._position = float(data.get("position") or 0)
        self._position_updated_at = datetime.now(timezone.utc)
        self._output = str(data.get("output") or "Home Assistant Audio (PulseAudio)")
        self._output_device = str(data.get("output_device") or "default")
        self._volume = float(data.get("volume", 0.8))
        self._error = data.get("error")

    async def async_media_play(self) -> None:
        await self.api.post(f"playback/server/resume?output_device={self._output_device}")
        await self.async_update()

    async def async_media_pause(self) -> None:
        await self.api.post(f"playback/server/pause?output_device={self._output_device}")
        await self.async_update()

    async def async_media_stop(self) -> None:
        await self.api.post(f"playback/server/stop?output_device={self._output_device}")
        await self.async_update()

    async def async_turn_off(self) -> None:
        await self.async_media_stop()

    async def async_media_seek(self, position: float) -> None:
        await self.api.post("playback/server/seek", {
            "position": max(0.0, float(position)), "output_device": self._output_device,
        })
        await self.async_update()

    async def async_set_volume(self, volume: float) -> None:
        await self.api.post("playback/volume", {
            "volume": max(0.0, min(1.0, float(volume))), "output_device": self._output_device,
        })
        await self.async_update()

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Start a VK track by the stable owner_id_track_id value."""
        if media_type not in (MediaType.MUSIC, "music"):
            raise ValueError("VK Music Server supports music tracks only")
        track_id = media_id.removeprefix("track:")
        if not re.fullmatch(r"-?\d+_-?\d+", track_id):
            raise ValueError("Unsupported VK track id")
        requested_output = kwargs.get("output_device")
        if isinstance(requested_output, str) and requested_output:
            self._output_device = requested_output
        await self.api.post("playback/server/play", {
            "track_id": track_id, "output_device": self._output_device,
        })
        await self.async_update()

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse the personal library and playlists."""
        try:
            if media_content_id in (None, "root"):
                return BrowseMedia(
                    title="VK Music",
                    media_class=MediaClass.DIRECTORY,
                    media_content_id="root",
                    media_content_type="library",
                    can_play=False,
                    can_expand=True,
                    children=[
                        BrowseMedia(
                            title="Моя музыка",
                            media_class=MediaClass.DIRECTORY,
                            media_content_id="library",
                            media_content_type=MediaType.MUSIC,
                            can_play=False,
                            can_expand=True,
                        ),
                        BrowseMedia(
                            title="Плейлисты",
                            media_class=MediaClass.DIRECTORY,
                            media_content_id="playlists",
                            media_content_type=MediaType.PLAYLIST,
                            can_play=False,
                            can_expand=True,
                        ),
                    ],
                )

            if media_content_id == "library":
                data = await self.api.get("library/tracks?limit=100&offset=0")
                return self._track_directory(
                    "Моя музыка", "library", data.get("items", [])
                )

            if media_content_id == "playlists":
                data = await self.api.get("playlists?limit=100&offset=0")
                children = [
                    BrowseMedia(
                        title=str(item.get("title") or "Плейлист"),
                        media_class=MediaClass.PLAYLIST,
                        media_content_id=f"playlist:{item['id']}",
                        media_content_type=MediaType.PLAYLIST,
                        can_play=False,
                        can_expand=True,
                        thumbnail=item.get("photo") or None,
                    )
                    for item in data.get("items", [])
                    if item.get("id")
                ]
                return BrowseMedia(
                    title="Плейлисты",
                    media_class=MediaClass.DIRECTORY,
                    media_content_id="playlists",
                    media_content_type=MediaType.PLAYLIST,
                    can_play=False,
                    can_expand=True,
                    children=children,
                )

            if media_content_id.startswith("playlist:"):
                playlist_id = media_content_id.removeprefix("playlist:")
                if not re.fullmatch(r"-?\d+_-?\d+", playlist_id):
                    raise BrowseError("Некорректный идентификатор плейлиста")
                data = await self.api.get(
                    f"playlists/{playlist_id}/tracks?limit=100&offset=0"
                )
                return self._track_directory(
                    "Треки плейлиста", media_content_id, data.get("items", [])
                )

        except VKMusicServerApiError as exc:
            raise BrowseError(str(exc)) from exc

        raise BrowseError("Неизвестный раздел VK Music")


    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        """Search VK audio and return playable media-browser results."""
        search_query = query.search_query.strip()
        if (
            not search_query
            or query.media_content_type not in (None, MediaType.MUSIC, "music")
            or (
                query.media_filter_classes
                and MediaClass.TRACK not in query.media_filter_classes
            )
        ):
            return SearchMedia(result=[])

        from urllib.parse import urlencode

        params = urlencode({"q": search_query, "limit": 100, "offset": 0})
        try:
            data = await self.api.get(f"search?{params}")
        except VKMusicServerApiError as exc:
            raise SearchError(str(exc)) from exc

        results = [
            BrowseMedia(
                title=(
                    f"{item.get('artist') or 'Неизвестный исполнитель'} — "
                    f"{item.get('title') or 'Без названия'}"
                ),
                media_class=MediaClass.TRACK,
                media_content_id=f"track:{item['id']}",
                media_content_type=MediaType.MUSIC,
                can_play=True,
                can_expand=False,
            )
            for item in data.get("items", [])
            if item.get("id")
        ]
        return SearchMedia(result=results)

    @staticmethod
    def _track_directory(
        title: str,
        media_content_id: str,
        tracks: list[dict[str, Any]],
    ) -> BrowseMedia:
        children = [
            BrowseMedia(
                title=(
                    f"{item.get('artist') or 'Неизвестный исполнитель'} — "
                    f"{item.get('title') or 'Без названия'}"
                ),
                media_class=MediaClass.TRACK,
                media_content_id=f"track:{item['id']}",
                media_content_type=MediaType.MUSIC,
                can_play=True,
                can_expand=False,
            )
            for item in tracks
            if item.get("id")
        ]
        return BrowseMedia(
            title=title,
            media_class=MediaClass.DIRECTORY,
            media_content_id=media_content_id,
            media_content_type=MediaType.MUSIC,
            can_play=False,
            can_expand=True,
            children=children,
        )
