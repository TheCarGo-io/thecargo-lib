"""Route-level guard helpers.

Common one-liners that fold ``fetch -> None check -> HTTPException`` into a
single expression, so handlers stop repeating the same 3-line block.

**Project convention**: missing-resource errors return **HTTP 400** with a
descriptive ``detail`` string. ``404`` is reserved for unknown URL paths
(FastAPI's own default); a request that names a non-existent record is
treated as a client bad-request, not a routing failure. The frontend
branches on the response body, not the status code.
"""

from __future__ import annotations

from typing import TypeVar

from fastapi import HTTPException

T = TypeVar("T")


def or_400(obj: T | None, message: str = "Not found", *, status_code: int = 400) -> T:
    """Return ``obj`` unchanged; raise :class:`HTTPException` when it is ``None``.

    Typical use::

        payment = or_400(await repo.get_by_id(payment_id), "Payment not found")

    ``status_code`` defaults to 400 per project convention - override for
    the rare endpoint that genuinely should return a different code.
    """
    if obj is None:
        raise HTTPException(status_code, message)
    return obj
