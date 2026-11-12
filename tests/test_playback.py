import asyncio
import signal

import pytest

import app.playback.manager as playback
from app.playback.manager import PlaybackError, ServerPlaybackManager


class FakeProcess:
    def __init__(self, returncode=None) -> None:
        self.returncode = returncode
        self.stderr = None
        self.signals: list[int] = []
        self._done = asyncio.Event()
        if returncode is not None:
            self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        return int(self.returncode or 0)

    def send_signal(self, value: int) -> None:
        self.signals.append(value)

    def terminate(self) -> None:
        self.returncode = -15
        self._done.set()

    def kill(self) -> None:
        self.returncode = -9
        self._done.set()


def test_server_playback_lifecycle_and_ffmpeg_pulse_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []
    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.append((args, kwargs))
        return process

    monkeypatch.setattr(playback.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def scenario():
        player = ServerPlaybackManager()
        state = await player.play(
            "https://cdn.vk.example/audio.mp3",
            "VK test UA",
            {"id":"1_2","title":"Test","artist":"Artist","duration":180},
        )
        assert state["state"] == "playing"
        assert state["mode"] == "server"
        ffmpeg_call = next(call for call in captured if call[0][0] == "ffmpeg")
        args = ffmpeg_call[0]
        assert "-f" in args
        assert args[args.index("-f") + 1] == "pulse"
        assert "-device" not in args
        assert args[-1] == "default"
        assert "-ar" in args and args[args.index("-ar") + 1] == "48000"
        assert "-ac" in args and args[args.index("-ac") + 1] == "2"
        assert "-sample_fmt" in args and args[args.index("-sample_fmt") + 1] == "s16"
        assert "VK Music Server" in args
        assert ffmpeg_call[1]["stderr"] == asyncio.subprocess.PIPE

        paused = await player.pause()
        assert paused["state"] == "paused"
        assert process.signals[-1] == signal.SIGSTOP

        resumed = await player.resume()
        assert resumed["state"] == "playing"
        assert process.signals[-1] == signal.SIGCONT

        stopped = await player.stop()
        assert stopped["state"] == "idle"
        assert process.returncode == -15
        assert player.get_state()["track"] is None
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_server_playback_rejects_non_https_streams() -> None:
    async def scenario():
        player = ServerPlaybackManager()
        with pytest.raises(PlaybackError):
            await player.play("http://untrusted.example/audio", "ua", {"id":"1_2"})
    asyncio.run(scenario())



def test_server_playback_does_not_report_failed_ffmpeg_start_as_playing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_process = FakeProcess(returncode=1)

    async def fake_create_subprocess_exec(*args, **kwargs):
        return failed_process

    monkeypatch.setattr(playback.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def scenario():
        player = ServerPlaybackManager()
        state = await player.play(
            "https://cdn.vk.example/audio.mp3",
            "VK test UA",
            {"id":"1_2","title":"Test","artist":"Artist","duration":180},
        )
        assert state["state"] == "error"
        assert state["track"] is None
        assert "PulseAudio" in state["error"]
        assert player.get_state()["state"] == "error"

    asyncio.run(scenario())


def test_playback_monitor_publishes_when_ffmpeg_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess()
    states = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    async def on_state_change(state):
        states.append(state)

    monkeypatch.setattr(playback.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def scenario():
        player = ServerPlaybackManager(on_state_change=on_state_change)
        await player.play(
            "https://cdn.vk.example/audio.mp3",
            "VK test UA",
            {"id": "1_2", "title": "Test", "artist": "Artist", "duration": 180},
        )
        process.returncode = 0
        process._done.set()
        await asyncio.sleep(0.01)
        assert states
        assert states[-1]["state"] == "idle"

    asyncio.run(scenario())


def test_set_volume_targets_the_selected_sink_or_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-supervisor-token")
    posted: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload=None) -> None:
            self.payload = payload or {}

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self.payload

    class FakeSupervisorClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, headers=None):
            assert url == "http://supervisor/audio/info"
            return FakeResponse(
                {
                    "data": {
                        "audio": {
                            "output": [
                                {"name": "default_sink", "index": 1, "default": True},
                                {"name": "selected_sink", "index": 2, "default": False},
                            ]
                        }
                    }
                }
            )

        async def post(self, url, headers=None, json=None):
            assert url == "http://supervisor/audio/volume/output"
            posted.append(json)
            return FakeResponse()

    monkeypatch.setattr(playback.httpx, "AsyncClient", FakeSupervisorClient)

    async def scenario():
        player = ServerPlaybackManager()
        player._output_device = "selected_sink"
        assert await player.set_volume(0.35) == {"volume": 0.35}
        player._output_device = "default"
        assert await player.set_volume(0.6) == {"volume": 0.6}

        assert posted == [
            {"index": 2, "volume": 0.35},
            {"index": 1, "volume": 0.6},
        ]

    asyncio.run(scenario())


def test_set_volume_falls_back_to_pactl_when_supervisor_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-supervisor-token")
    captured: list[tuple[object, ...]] = []

    class UnavailableSupervisorClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, headers=None):
            raise playback.httpx.ConnectError("Supervisor is unavailable")

    class SuccessfulProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.append(args)
        return SuccessfulProcess()

    monkeypatch.setattr(playback.httpx, "AsyncClient", UnavailableSupervisorClient)
    monkeypatch.setattr(playback.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def scenario():
        player = ServerPlaybackManager()
        player._output_device = "selected_sink"
        assert await player.set_volume(0.45) == {"volume": 0.45}
        assert captured == [
            ("pactl", "set-sink-volume", "selected_sink", "45%")
        ]

    asyncio.run(scenario())


def test_set_volume_reports_missing_pactl_as_playback_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)

    async def missing_pactl(*args, **kwargs):
        raise FileNotFoundError("pactl")

    monkeypatch.setattr(playback.asyncio, "create_subprocess_exec", missing_pactl)

    async def scenario():
        player = ServerPlaybackManager()
        with pytest.raises(PlaybackError, match="pactl"):
            await player.set_volume(0.5)

    asyncio.run(scenario())
