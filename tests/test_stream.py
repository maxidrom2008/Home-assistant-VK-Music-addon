import asyncio

from app.playback.stream import ffmpeg_command
from app.vk.stream_cache import StreamUrlCache


def test_browser_stream_transcodes_hls_to_mp3() -> None:
    command = ffmpeg_command("https://cdn.vk.example/index.m3u8", "VK test UA")
    assert command[0] == "ffmpeg"
    assert command[command.index("-user_agent") + 1] == "VK test UA"
    assert command[command.index("-i") + 1].endswith(".m3u8")
    assert command.index("-i") < command.index("-codec:a")
    assert command[command.index("-codec:a") + 1] == "libmp3lame"
    assert command[-2:] == ["mp3", "pipe:1"]
    assert "-ss" not in command


def test_browser_stream_uses_input_side_seek() -> None:
    command = ffmpeg_command(
        "https://cdn.vk.example/index.m3u8", "VK test UA", start_seconds=93.0
    )
    assert command[command.index("-ss") + 1] == "93.000"
    assert command.index("-ss") < command.index("-i")


def test_stream_url_cache_reuses_url_for_seeks_and_refreshes_for_new_playback() -> None:
    async def scenario() -> None:
        now = [100.0]
        calls = 0

        async def resolve() -> str:
            nonlocal calls
            calls += 1
            return f"https://cdn.vk.example/stream-{calls}.m3u8"

        cache = StreamUrlCache(ttl_seconds=60, clock=lambda: now[0])

        first_play = await cache.get_or_resolve("token-a", "123_456", resolve)
        seek_one = await cache.get_or_resolve("token-a", "123_456", resolve)
        seek_two = await cache.get_or_resolve("token-a", "123_456", resolve)

        assert first_play == seek_one == seek_two
        assert calls == 1

        next_play = await cache.get_or_resolve(
            "token-a", "123_456", resolve, force_refresh=True
        )
        assert next_play != first_play
        assert calls == 2

        now[0] += 61
        after_expiry = await cache.get_or_resolve("token-a", "123_456", resolve)
        assert after_expiry != next_play
        assert calls == 3

        other_account = await cache.get_or_resolve("token-b", "123_456", resolve)
        assert other_account != after_expiry
        assert calls == 4

        cache.clear_for_token("token-b")
        after_disconnect = await cache.get_or_resolve("token-b", "123_456", resolve)
        assert after_disconnect != other_account
        assert calls == 5

    asyncio.run(scenario())
