import asyncio
import signal

import pytest

import app.playback.manager as playback
from app.playback.manager import PlaybackError, ServerPlaybackManager


class FakeProcess:
    def __init__(self, returncode=None) -> None:
        self.returncode = returncode
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
        args = captured[0][0]
        assert "-f" in args
        assert args[args.index("-f") + 1] == "pulse"
        assert args[-1] == "default"
        assert "VK Music Server" in args
        assert captured[0][1]["stderr"] == asyncio.subprocess.DEVNULL

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
