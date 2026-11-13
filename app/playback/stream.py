"""Browser-friendly audio transcoding for VK streams, including HLS playlists."""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

_LOGGER = logging.getLogger(__name__)


def ffmpeg_command(url: str, user_agent: str, start_seconds: float = 0.0) -> list[str]:
    """Build a command that turns VK audio/HLS into a browser-safe MP3 stream."""
    return [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-user_agent", user_agent,
        *(["-ss", f"{max(0.0, float(start_seconds)):.3f}"] if start_seconds > 0 else []),
        "-i", url,
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-codec:a", "libmp3lame", "-q:a", "4", "-f", "mp3", "pipe:1",
    ]


async def proxy_audio(url: str, user_agent: str, range_header: str | None = None, start_seconds: float = 0.0) -> StreamingResponse:
    """Transcode the resolved VK source so browsers never need to fetch VK HLS segments."""
    if not url.startswith("https://"):
        raise HTTPException(status_code=502, detail="VK вернул неподдерживаемый адрес аудиопотока")
    command = ffmpeg_command(url, user_agent, start_seconds)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="FFmpeg не найден в контейнере add-on") from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail="Не удалось запустить обработчик аудиопотока") from exc

    # Give the child process one event-loop turn to report an immediate failure.
    # Avoid a fixed 200 ms delay on every initial play and seek request.
    await asyncio.sleep(0)
    if process.returncode is not None:
        error = (await process.stderr.read()).decode("utf-8", "replace")[-1200:]
        _LOGGER.warning("VK browser stream FFmpeg exited (%s): %s", process.returncode, error.strip())
        raise HTTPException(status_code=502, detail="FFmpeg не смог открыть аудиопоток VK")

    async def body():
        try:
            assert process.stdout is not None
            while chunk := await process.stdout.read(64 * 1024):
                yield chunk
            return_code = await process.wait()
            if return_code:
                assert process.stderr is not None
                error = (await process.stderr.read()).decode("utf-8", "replace")[-1200:]
                _LOGGER.warning("VK browser stream FFmpeg exited (%s): %s", return_code, error.strip())
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    return StreamingResponse(
        body(),
        media_type="audio/mpeg",
        headers={"cache-control": "no-store", "accept-ranges": "none"},
    )
