"""FFmpeg output to the Home Assistant shared PulseAudio server."""
from __future__ import annotations

import asyncio
import signal
import time
import logging
from typing import Any, Awaitable, Callable


class PlaybackError(Exception):
    """A server-side playback operation could not be completed."""


_LOGGER = logging.getLogger(__name__)

PLAYBACK_STARTUP_GRACE_SECONDS = 1.0


class ServerPlaybackManager:
    """Own one FFmpeg process connected to the Supervisor audio service."""

    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        on_state_change: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self._on_state_change = on_state_change
        self._process: asyncio.subprocess.Process | None = None
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._state: dict[str, Any] = {
            "state": "idle",
            "mode": "server",
            "track": None,
            "output": "Home Assistant Audio (PulseAudio)",
            "error": None,
        }
        self._position = 0.0
        self._position_mark: float | None = None

    def get_state(self) -> dict[str, Any]:
        state = dict(self._state)
        if self._position_mark is not None and state["state"] == "playing":
            state["position"] = round(
                self._position + time.monotonic() - self._position_mark, 1
            )
        else:
            state["position"] = round(self._position, 1)
        return state

    async def play(
        self,
        stream_url: str,
        user_agent: str,
        track: dict[str, Any],
    ) -> dict[str, Any]:
        if not stream_url.startswith("https://"):
            raise PlaybackError("VK вернул неподдерживаемый адрес аудиопотока")
        async with self._lock:
            await self._stop_locked()
            command = [
                self.ffmpeg_binary,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
                "-user_agent",
                user_agent,
                "-i",
                stream_url,
                "-vn",
                "-sn",
                "-dn",
                "-f",
                "pulse",
                "-name",
                "VK Music Server",
                "default",
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise PlaybackError("FFmpeg не найден в контейнере add-on") from exc
            except OSError as exc:
                raise PlaybackError(f"Не удалось запустить FFmpeg: {exc.strerror}") from exc

            self._process = process
            self._position = 0.0
            self._position_mark = time.monotonic()
            self._state = {
                "state": "playing",
                "mode": "server",
                "track": {
                    "id": str(track.get("id") or ""),
                    "title": str(track.get("title") or ""),
                    "artist": str(track.get("artist") or ""),
                    "duration": int(track.get("duration") or 0),
                },
                "output": "Home Assistant Audio (PulseAudio)",
                "error": None,
            }
            self._monitor_task = asyncio.create_task(self._watch(process))
            # Give FFmpeg a brief opportunity to open its input and PulseAudio sink.
            # A process that exits immediately must not be reported as playing.
            await asyncio.sleep(PLAYBACK_STARTUP_GRACE_SECONDS)
            if process.returncode is not None:
                stderr = await process.stderr.read() if getattr(process, "stderr", None) is not None else b""
                _LOGGER.error("Server playback FFmpeg exited (%s): %s", process.returncode, stderr.decode("utf-8", "replace")[-2000:].strip())
                self._process = None
                self._position_mark = None
                self._state = {
                    "state": "error",
                    "mode": "server",
                    "track": None,
                    "output": "Home Assistant Audio (PulseAudio)",
                    "error": (
                        "FFmpeg не смог открыть аудиопоток или PulseAudio. "
                        "Подробности смотрите в журнале add-on."
                    ),
                }
                self._position = 0.0
                return self.get_state()
            return self.get_state()

    async def _watch(self, process: asyncio.subprocess.Process) -> None:
        return_code = await process.wait()
        stderr = await process.stderr.read() if process.stderr is not None else b""
        if return_code:
            _LOGGER.error("Server playback FFmpeg exited (%s): %s", return_code, stderr.decode("utf-8", "replace")[-2000:].strip())
        async with self._lock:
            if self._process is not process:
                return
            self._process = None
            self._position_mark = None
            if return_code == 0:
                self._state = {
                    "state": "idle",
                    "mode": "server",
                    "track": None,
                    "output": "Home Assistant Audio (PulseAudio)",
                    "error": None,
                }
                self._position = 0.0
            else:
                self._state = {
                    **self._state,
                    "state": "error",
                    "error": (
                        "FFmpeg завершился с ошибкой. Подробности смотрите в журнале add-on."
                    ),
                }
        if self._on_state_change is not None:
            try:
                await self._on_state_change(self.get_state())
            except Exception:
                # Event delivery must never break playback process monitoring.
                pass

    async def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._position_mark = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._position = 0.0
        self._state = {
            "state": "idle",
            "mode": "server",
            "track": None,
            "output": "Home Assistant Audio (PulseAudio)",
            "error": None,
        }

    async def pause(self) -> dict[str, Any]:
        async with self._lock:
            if self._process is None or self._state["state"] != "playing":
                raise PlaybackError("Серверный плеер сейчас не воспроизводит музыку")
            self._position += time.monotonic() - (
                self._position_mark if self._position_mark is not None else time.monotonic()
            )
            self._position_mark = None
            try:
                self._process.send_signal(signal.SIGSTOP)
            except ProcessLookupError as exc:
                raise PlaybackError("Процесс воспроизведения уже завершился") from exc
            self._state["state"] = "paused"
            return self.get_state()

    async def resume(self) -> dict[str, Any]:
        async with self._lock:
            if self._process is None or self._state["state"] != "paused":
                raise PlaybackError("Серверный плеер не находится на паузе")
            try:
                self._process.send_signal(signal.SIGCONT)
            except ProcessLookupError as exc:
                raise PlaybackError("Процесс воспроизведения уже завершился") from exc
            self._position_mark = time.monotonic()
            self._state["state"] = "playing"
            return self.get_state()

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            await self._stop_locked()
            return self.get_state()
