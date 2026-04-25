from uuid import UUID, uuid4

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from thecargo.context import AuditContext, set_audit_context


def _get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _resolve_request_id(incoming: str | None) -> UUID:
    """Reuse a valid caller-supplied X-Request-ID so audit rows across
    microservices share a correlation id; otherwise mint a fresh one."""
    if not incoming:
        return uuid4()
    try:
        return UUID(incoming)
    except ValueError:
        return uuid4()


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, jwt_secret: str, jwt_algorithm: str = "HS256"):
        super().__init__(app)
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm

    async def dispatch(self, request: Request, call_next):
        request_id = _resolve_request_id(request.headers.get("x-request-id"))

        # Some bots and SDKs ship multi-kilobyte User-Agent strings; the
        # audit_logs column is capped at 500 so truncate at the edge instead
        # of letting a DB error blow up the request.
        ua = request.headers.get("user-agent")
        ctx = AuditContext(
            ip_address=_get_client_ip(request),
            user_agent=(ua[:500] if ua else None),
            request_id=request_id,
        )

        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                payload = jwt.decode(auth[7:], self.jwt_secret, algorithms=[self.jwt_algorithm])
                ctx.actor_id = UUID(payload["user_id"]) if payload.get("user_id") else None
                ctx.actor_email = payload.get("email")
                ctx.organization_id = UUID(payload["org_id"]) if payload.get("org_id") else None
            except Exception:
                pass

        set_audit_context(ctx)
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        return response
