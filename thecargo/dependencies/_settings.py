import os

_jwt_secret: str | None = None


def set_jwt_secret(secret: str):
    global _jwt_secret
    _jwt_secret = secret


def get_jwt_secret() -> str:
    if _jwt_secret:
        return _jwt_secret
    return os.environ.get("JWT_SECRET_KEY", "change-me")
