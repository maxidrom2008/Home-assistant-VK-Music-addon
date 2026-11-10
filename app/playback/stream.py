"""HTTP proxy for short-lived VK audio URLs."""
from collections.abc import AsyncIterator

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse


async def proxy_audio(url: str, user_agent: str, range_header: str | None = None) -> StreamingResponse:
    # The URL is resolved by vkpymusic for a selected track; clients cannot supply it.
    client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None), follow_redirects=True)
    headers = {"User-Agent": user_agent}
    if range_header:
        headers["Range"] = range_header
    try:
        req = client.build_request("GET", url, headers=headers)
        response = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Не удалось открыть аудиопоток VK") from exc

    if response.status_code >= 400:
        status_code = response.status_code
        await response.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"VK CDN вернул HTTP {status_code}")

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    forwarded = {"cache-control": "no-store"}
    for key in ("content-length", "content-range", "accept-ranges"):
        if value := response.headers.get(key):
            forwarded[key] = value
    return StreamingResponse(
        body(),
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "audio/mpeg"),
        headers=forwarded,
    )
