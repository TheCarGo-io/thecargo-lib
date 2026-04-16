from uuid import UUID

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from thecargo.context import AuditContext, set_audit_context


def _get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, jwt_secret: str, jwt_algorithm: str = "HS256"):
        super().__init__(app)
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm

    async def dispatch(self, request: Request, call_next):
        ctx = AuditContext(ip_address=_get_client_ip(request))

        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                payload = jwt.decode(
                    auth[7:], self.jwt_secret, algorithms=[self.jwt_algorithm]
                )
                ctx.actor_id = UUID(payload["user_id"]) if payload.get("user_id") else None
                ctx.actor_email = payload.get("email")
                ctx.organization_id = UUID(payload["org_id"]) if payload.get("org_id") else None
            except Exception:
                pass

        set_audit_context(ctx)
        return await call_next(request)
