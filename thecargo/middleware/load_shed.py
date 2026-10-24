from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from thecargo.handlers import _envelope
from thecargo.i18n import get_language

SKIP_PREFIXES = ("/health", "/metrics", "/api/internal")


class LoadShedMiddleware:
    """Answer 503 at once when this process is already serving ``limit`` requests.

    One uvicorn process runs one event loop on one core. Past that, every extra request
    only stretches the wait for all of them, each holding its pooled connection while it
    waits for the loop, until the pools drain into timeouts and 500s seconds later.
    Turning the excess away up front keeps the admitted requests fast, and the client
    retries a 503 that cost nothing.

    Health probes are never shed, or a pod under load would be pulled out of rotation
    exactly when it is needed. Internal calls are not shed either: each belongs to a
    request that this or another pod already admitted.
    """

    def __init__(self, app: ASGIApp, *, limit: int, skip_prefixes: tuple[str, ...] = SKIP_PREFIXES) -> None:
        self.app = app
        self.limit = limit
        self.skip_prefixes = skip_prefixes
        self.in_flight = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(self.skip_prefixes):
            await self.app(scope, receive, send)
            return
        if self.in_flight >= self.limit:
            lang = get_language(Request(scope))
            response = JSONResponse(
                _envelope("SERVER_BUSY", "common.server_busy", lang, {}, "Server busy, retry shortly"),
                status_code=503,
                headers={"Retry-After": "1"},
            )
            await response(scope, receive, send)
            return
        self.in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_flight -= 1
