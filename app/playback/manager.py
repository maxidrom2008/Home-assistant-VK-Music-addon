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


class _PlaybackZone:
    """Own one FFmpeg process connected to a single PulseAudio output."""

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
        self._volume = 0.8
        self._equalizer: dict[str, float] = {"bass": 0.0, "low_mid": 0.0, "mid": 0.0, "high_mid": 0.0, "treble": 0.0}

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
            and "dummy" not in str(item.get("name", "")).lower()
            and "dummy" not in str(item.get("description", "")).lower()
            and str(item.get("name", "")).lower() != "auto_null"
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
                and "dummy" not in str(sink.get("name", "")).lower()
                and "dummy" not in str(sink.get("description", "")).lower()
                and str(sink.get("name", "")).lower() != "auto_null"
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

    async def set_volume(self, volume: float) -> dict[str, Any]:
        """Set the selected HAOS audio output volume."""
        value = max(0.0, min(1.0, float(volume)))
        token = os.environ.get("SUPERVISOR_TOKEN")
        if token:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = {"Authorization": f"Bearer {token}"}
                    info = await client.get("http://supervisor/audio/info", headers=headers)
                    info.raise_for_status()
                    payload = info.json()
                    data = payload.get("data", payload) if isinstance(payload, dict) else {}
                    audio = data.get("audio", {}) if isinstance(data, dict) else {}
                    sinks = audio.get("output", []) if isinstance(audio, dict) else []

                    # Match an explicitly selected sink first. Only use the
                    # Supervisor default when the user selected "default".
                    if self._output_device == "default":
                        sink = next(
                            (item for item in sinks if isinstance(item, dict) and item.get("default")),
                            None,
                        )
                    else:
                        sink = next(
                            (
                                item for item in sinks
                                if isinstance(item, dict) and item.get("name") == self._output_device
                            ),
                            None,
                        )

                    if sink is not None and sink.get("index") is not None:
                        response = await client.post(
                            "http://supervisor/audio/volume/output",
                            headers=headers,
                            json={"index": int(sink["index"]), "volume": value},
                        )
                        response.raise_for_status()
                        self._volume = value
                        return {"volume": value}
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
                # Supervisor can be temporarily unavailable; retain the
                # PulseAudio fallback instead of returning an unexpected 500.
                _LOGGER.warning("Could not set volume through Supervisor API: %s", exc)

        target = self._output_device if self._output_device != "default" else "@DEFAULT_SINK@"
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                "pactl",
                "set-sink-volume",
                target,
                f"{round(value * 100)}%",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
        except FileNotFoundError as exc:
            raise PlaybackError("Утилита pactl не найдена в контейнере add-on") from exc
        except asyncio.TimeoutError as exc:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            raise PlaybackError("Превышено время ожидания ответа PulseAudio при изменении громкости") from exc
        except OSError as exc:
            raise PlaybackError(f"Не удалось изменить громкость через PulseAudio: {exc.strerror}") from exc

        if process.returncode:
            detail = stderr.decode("utf-8", "replace")[-500:].strip()
            raise PlaybackError(detail or "Не удалось изменить громкость")

        self._volume = value
        return {"volume": value}

    def get_state(self) -> dict[str, Any]:
        state = dict(self._state)
        if self._position_mark is not None and state["state"] == "playing":
            state["position"] = round(
                self._position + time.monotonic() - self._position_mark, 1
            )
        else:
            state["position"] = round(self._position, 1)
        state["output_device"] = self._output_device
        state["equalizer"] = dict(self._equalizer)
        return state

    async def play(
        self,
        stream_url: str,
        user_agent: str,
        track: dict[str, Any],
        start_seconds: float = 0.0,
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
                *( ["-ss", f"{max(0.0, float(start_seconds)):.3f}"] if start_seconds > 0 else [] ),
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
                "-af",
                ",".join([
                    f"volume={self._volume}",
                    *[
                        f"equalizer=f={frequency}:t=q:w=1:g={self._equalizer[band]:.1f}"
                        for band, frequency in (("bass", 60), ("low_mid", 250), ("mid", 1000), ("high_mid", 4000), ("treble", 12000))
                        if abs(self._equalizer[band]) >= 0.05
                    ],
                ]),
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
            self._position = max(0.0, float(start_seconds))
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
                "output_device": self._output_device,
                "equalizer": dict(self._equalizer),
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
            except (OSError, asyncio.TimeoutError, AttributeError) as exc:
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

    async def set_equalizer(self, bands: dict[str, float]) -> dict[str, Any]:
        """Store a safe five-band equalizer profile for this output."""
        allowed = {"bass", "low_mid", "mid", "high_mid", "treble"}
        for name, value in bands.items():
            if name not in allowed:
                raise PlaybackError(f"Неизвестная полоса эквалайзера: {name}")
            self._equalizer[name] = max(-12.0, min(12.0, float(value)))
        self._state["equalizer"] = dict(self._equalizer)
        return self.get_state()

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



class ServerPlaybackManager(_PlaybackZone):
    """Coordinate independent playback processes for each HAOS output."""

    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        on_state_change: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(ffmpeg_binary=ffmpeg_binary, on_state_change=on_state_change)
        self._zones: dict[str, _PlaybackZone] = {"default": self}
        self._zone_labels: dict[str, str] = {"default": "По умолчанию"}
        self._selected_output = "default"

    def _zone(self, output_device: str | None = None) -> _PlaybackZone:
        device = str(output_device or self._selected_output or "default")
        zone = self._zones.get(device)
        if zone is None:
            zone = _PlaybackZone(
                ffmpeg_binary=self.ffmpeg_binary,
                on_state_change=lambda state, key=device: self._publish_zone_state(key, state),
            )
            zone._output_device = device
            zone._output_label = self._zone_labels.get(device, device)
            self._zones[device] = zone
        return zone

    async def _publish_zone_state(self, device: str, state: dict[str, Any]) -> None:
        if self._on_state_change is not None:
            payload = {**state, "output_device": device}
            try:
                await self._on_state_change(payload)
            except Exception:
                pass

    async def list_outputs(self) -> dict[str, Any]:
        data = await super().list_outputs()
        outputs = data.get("outputs", [])
        self._zone_labels.update({
            str(item["id"]): str(item["name"])
            for item in outputs if isinstance(item, dict) and item.get("id")
        })
        for device, zone in self._zones.items():
            if device != "default" and device in self._zone_labels:
                zone._output_label = self._zone_labels[device]
        data["selected"] = self._selected_output
        data["active"] = self.get_states()
        return data

    async def select_output(self, device: str) -> dict[str, Any]:
        data = await super().list_outputs()
        choices = {str(item["id"]): str(item["name"]) for item in data.get("outputs", []) if item.get("id")}
        if device not in choices:
            raise PlaybackError("Выбранное аудиоустройство больше недоступно. Обновите список.")
        self._selected_output = device
        self._zone_labels[device] = choices[device]
        zone = self._zone(device)
        zone._output_label = choices[device]
        return {"selected": device, "name": choices[device], "active": self.get_states()}

    def get_state(self, output_device: str | None = None) -> dict[str, Any]:
        device = str(output_device or self._selected_output or "default")
        zone = self._zone(device)
        return {**zone.get_state(), "output_device": device}

    def get_states(self) -> list[dict[str, Any]]:
        return [
            {**zone.get_state(), "output_device": device}
            for device, zone in self._zones.items()
        ]

    async def play(
        self,
        stream_url: str,
        user_agent: str,
        track: dict[str, Any],
        output_device: str | None = None,
        start_seconds: float = 0.0,
    ) -> dict[str, Any]:
        device = str(output_device or self._selected_output or "default")
        state = await self._zone(device).play(stream_url, user_agent, track, start_seconds)
        return {**state, "output_device": device}

    async def set_volume(self, volume: float, output_device: str | None = None) -> dict[str, Any]:
        device = str(output_device or self._selected_output or "default")
        result = await self._zone(device).set_volume(volume)
        return {**result, "output_device": device}

    async def set_equalizer(
        self, bands: dict[str, float], output_device: str | None = None
    ) -> dict[str, Any]:
        device = str(output_device or self._selected_output or "default")
        return await self._zone(device).set_equalizer(bands)

    async def pause(self, output_device: str | None = None) -> dict[str, Any]:
        device = str(output_device or self._selected_output or "default")
        return await self._zone(device).pause()

    async def resume(self, output_device: str | None = None) -> dict[str, Any]:
        device = str(output_device or self._selected_output or "default")
        return await self._zone(device).resume()

    async def stop(self, output_device: str | None = None) -> dict[str, Any]:
        device = str(output_device or self._selected_output or "default")
        return await self._zone(device).stop()

    async def stop_all(self) -> None:
        for device, zone in list(self._zones.items()):
            if device == "default":
                await _PlaybackZone.stop(zone)
            else:
                await zone.stop()
