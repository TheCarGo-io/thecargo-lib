from collections.abc import MutableMapping
from typing import Any

import jwt

_SCOPE_KEY = "thecargo.decoded_jwt"


def decode_once(
    scope: MutableMapping[str, Any] | None, token: str, secret: str, algorithm: str = "HS256"
) -> dict[str, Any]:
    """Decode a bearer token at most once per request.

    The audit and rate-limit middlewares and `get_current_user` each read the same token, so every request verified
    its signature three times. The decoded claims ride on the ASGI scope, keyed by token, secret and algorithm, so a
    reader with a different key still decodes on its own. A token that fails is not cached and fails again.
    """
    if scope is None:
        return jwt.decode(token, secret, algorithms=[algorithm])
    key = (token, secret, algorithm)
    cached = scope.get(_SCOPE_KEY)
    if cached is not None and cached[0] == key:
        return cached[1]
    payload = jwt.decode(token, secret, algorithms=[algorithm])
    scope[_SCOPE_KEY] = (key, payload)
    return payload
