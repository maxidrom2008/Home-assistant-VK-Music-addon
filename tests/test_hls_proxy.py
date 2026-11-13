import asyncio

import httpx
import pytest

from app.vk.hls_proxy import HlsProxy, HlsProxyError


def test_rewrite_master_playlist_and_uri_attributes() -> None:
    proxy = HlsProxy()
    session, resource = proxy.create_session(
        "https://cdn.vk.example/master.m3u8?sig=secret", "VK UA", "account"
    )
    source = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,URI="audio/index.m3u8"\n'
        "#EXT-X-STREAM-INF:BANDWIDTH=128000\n"
        "variant/index.m3u8\n"
    )
    rewritten = proxy.rewrite_playlist(
        session, "account", "https://cdn.vk.example/master.m3u8?sig=secret", source
    )
    assert "#EXTM3U" in rewritten
    assert "https://cdn.vk.example" not in rewritten
    assert "sig=secret" not in rewritten
    assert "URI=" in rewritten
    assert len(proxy._sessions[session].resources) == 3
    assert resource


def test_rejects_external_playlist_uri() -> None:
    proxy = HlsProxy()
    session, _ = proxy.create_session("https://cdn.vk.example/master.m3u8", "UA", "account")
    with pytest.raises(HlsProxyError):
        proxy.rewrite_playlist(
            session, "account", "https://cdn.vk.example/master.m3u8",
            "#EXTM3U\nhttps://attacker.example/steal.m3u8\n",
        )


def test_session_is_scoped_to_account_and_expires() -> None:
    now = [10.0]
    proxy = HlsProxy(ttl_seconds=5, clock=lambda: now[0])
    session, resource = proxy.create_session("https://cdn.vk.example/a.m3u8", "UA", "account-a")
    with pytest.raises(KeyError):
        proxy._session(session, "account-b")
    now[0] += 6
    with pytest.raises(KeyError):
        proxy._session(session, "account-a")


def test_fetch_proxies_playlist_and_range_segment(monkeypatch) -> None:
    proxy = HlsProxy()
    session, playlist_id = proxy.create_session(
        "https://cdn.vk.example/master.m3u8", "VK UA", "account"
    )
    segment_id = "segment"
    proxy._sessions[session].resources[segment_id] = "https://cdn.vk.example/segment.ts"

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            assert headers["User-Agent"] == "VK UA"
            if url.endswith("master.m3u8"):
                return httpx.Response(
                    200, text="#EXTM3U\nsegment.ts\n",
                    headers={"content-type": "application/vnd.apple.mpegurl"},
                )
            assert headers["Range"] == "bytes=0-99"
            return httpx.Response(
                206, content=b"segment",
                headers={"content-type": "video/mp2t", "content-range": "bytes 0-6/7"},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    async def scenario():
        playlist = await proxy.fetch(session, playlist_id, "account")
        assert playlist.content_type == "application/vnd.apple.mpegurl"
        assert playlist.body.decode().strip().splitlines()[-1] != "segment.ts"\n        assert "https://" not in playlist.body.decode()
        segment = await proxy.fetch(session, segment_id, "account", "bytes=0-99")
        assert segment.status_code == 206
        assert segment.body == b"segment"
        assert segment.headers["content-range"] == "bytes 0-6/7"

    asyncio.run(scenario())
