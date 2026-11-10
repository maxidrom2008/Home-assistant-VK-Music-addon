"""Restrict add-on traffic to Home Assistant Ingress and loopback.

Home Assistant Ingress/Supervisor traffic comes from 172.30.32.2.
Home Assistant Core runs on the host network and reaches add-ons through
the hassio bridge gateway (172.30.32.1). The health endpoint remains
available to Supervisor watchdog checks.
"""
from starlette.responses import JSONResponse


class IngressOnlyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        client = scope.get("client")
        host = client[0] if client else ""
        allowed = host in {"172.30.32.1", "172.30.32.2", "127.0.0.1", "::1", "testclient"}
        if path == "/health" and scope["type"] == "http":
            allowed = True

        if allowed:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        response = JSONResponse(
            {"detail": "Access is available through Home Assistant Ingress only."},
            status_code=403,
        )
        await response(scope, receive, send)
