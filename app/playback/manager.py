"""FFmpeg output to the Home Assistant shared PulseAudio server."""
from __future__ import annotations

import asyncio
import signal
import time
import logging
import json
import os
from typing import Any, Awaitable, Callable

import httpx


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
        self._output_device = "default"
        self._output_label = "По умолчанию"
        self._state: dict[str, Any] = {
            "state": "idle",
            "mode": "server",
            "track": None,
            "output": self._output_label,
            "error": None,
        }
        self._position = 0.0
        self._position_mark: float | None = None

    async def _supervisor_outputs(self) -> tuple[list[dict[str, str]], str | None]:
        """Read host audio outputs from the Supervisor audio API."""
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            return [], None
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "http://supervisor/audio/info",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", payload)
        audio = data.get("audio", {}) if isinstance(data, dict) else {}
        raw_outputs = audio.get("output", []) if isinstance(audio, dict) else []
        outputs = [
            {
                "id": str(item.get("name") or ""),
                "name": str(item.get("description") or item.get("name") or "Аудиоустройство"),
            }
            for item in raw_outputs
            if isinstance(item, dict) and item.get("name")
        ]
        default_sink = next(
            (str(item.get("name")) for item in raw_outputs if isinstance(item, dict) and item.get("default") and item.get("name")),
            None,
        )
        return outputs, default_sink

    async def list_outputs(self) -> dict[str, Any]:
        """List output devices from Supervisor, falling back to PulseAudio sinks."""
        supervisor_error = None
        try:
            outputs, default_sink = await self._supervisor_outputs()
            if outputs:
                return {
                    "outputs": [{"id": "default", "name": "По умолчанию"}, *outputs],
                    "selected": self._output_device,
                    "default_sink": default_sink,
                    "device_count": len(outputs),
                    "notice": (
                        "Список получен у аудиослужбы Home Assistant. "
                        "Bluetooth-колонка появится здесь после сопряжения и подключения как аудиовыход A2DP."
                    ),
                }
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            supervisor_error = str(exc)
            _LOGGER.warning("Could not read Supervisor audio outputs: %s", exc)
        try:
            process = await asyncio.create_subprocess_exec(
                "pactl", "-f", "json", "list", "sinks",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            if process.returncode != 0:
                raise PlaybackError(stderr.decode("utf-8", "replace")[-1000:].strip() or "pactl не смог получить список устройств")
            sinks = json.loads(stdout.decode("utf-8", "replace"))
            outputs = [
                {"id": str(sink.get("name") or ""), "name": str(sink.get("description") or sink.get("name") or "Аудиоустройство")}
                for sink in sinks if isinstance(sink, dict) and sink.get("name")
            ]
            default_process = await asyncio.create_subprocess_exec(
                "pactl", "get-default-sink",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            default_stdout, _ = await asyncio.wait_for(default_process.communicate(), timeout=3.0)
            default_sink = default_stdout.decode("utf-8", "replace").strip() if default_process.returncode == 0 else None
        except FileNotFoundError:
            raise PlaybackError("Утилита pactl не найдена в контейнере add-on")
        except (asyncio.TimeoutError, json.JSONDecodeError) as exc:
            raise PlaybackError("Не удалось прочитать список аудиоустройств PulseAudio") from exc
        except OSError as exc:
            raise PlaybackError(f"Не удалось запросить PulseAudio: {exc.strerror}") from exc
        return {
            "outputs": [{"id": "default", "name": "По умолчанию"}, *outputs],
            "selected": self._output_device,
            "default_sink": default_sink,
            "device_count": len(outputs),
            "notice": (
                "Показаны только устройства, доступные PulseAudio add-on. "
                "Для Bluetooth-колонки требуется подключение как A2DP-аудиовыход в HAOS."
            ),
            "supervisor_error": supervisor_error,
        }

    async def select_output(self, device: str) -> dict[str, Any]:
        available = await self.list_outputs()
        choices = {item["id"]: item["name"] for item in available["outputs"]}
        if device not in choices:
            raise PlaybackError("Выбранное аудиоустройство больше недоступно. Обновите список.")
        self._output_device = device
        self._output_label = choices[device]
        return {"selected": device, "name": self._output_label}

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
                "-ac",
                "2",
                "-ar",
                "48000",
                "-sample_fmt",
                "s16",
                "-f",
                "pulse",
                "-name",
                "VK Music Server",
                "default",
            ]
            if self._output_device != "default":
                output_index = command.index("-name")
                command[output_index:output_index] = ["-device", self._output_device]
            try:
                diagnostics = await self._pulse_diagnostics()
                _LOGGER.info("PulseAudio output diagnostics before playback:\n%s", diagnostics)
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
                "output": self._output_label,
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

    async def _pulse_diagnostics(self) -> str:
        """Collect PulseAudio server and sink state for actionable logs."""
        details: list[str] = []
        for args in (("pactl", "info"), ("pactl", "list", "short", "sinks")):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                output, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
                details.append("$ " + " ".join(args) + "\n" + output.decode("utf-8", "replace")[-4000:].strip())
            except (OSError, asyncio.TimeoutError) as exc:
                details.append("$ " + " ".join(args) + "\n" + str(exc))
        return "\n".join(details)

    async def _watch(self, process: asyncio.subprocess.Process) -> None:
        return_code = await process.wait()
        stderr = await process.stderr.read() if process.stderr is not None else b""
        if return_code:
            diagnostics = await self._pulse_diagnostics()
            _LOGGER.error(
                "Server playback FFmpeg exited (%s): %s\nPulseAudio diagnostics:\n%s",
                return_code,
                stderr.decode("utf-8", "replace")[-2000:].strip(),
                diagnostics,
            )
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
                        "HAOS не принял аудиопоток через PulseAudio. Проверьте выбранный выход и журнал add-on."
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
