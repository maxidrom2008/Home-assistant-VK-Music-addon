from app.playback.stream import ffmpeg_command


def test_browser_stream_transcodes_hls_to_mp3() -> None:
    command = ffmpeg_command("https://cdn.vk.example/index.m3u8", "VK test UA")
    assert command[0] == "ffmpeg"
    assert command[command.index("-user_agent") + 1] == "VK test UA"
    assert command[command.index("-i") + 1].endswith(".m3u8")
    assert command[command.index("-codec:a") + 1] == "libmp3lame"
    assert command[-2:] == ["mp3", "pipe:1"]
