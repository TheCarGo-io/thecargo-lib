from __future__ import annotations

from typing import TypeVar

from fastapi import HTTPException

T = TypeVar("T")


def or_400(obj: T | None, message: str = "Not found", *, status_code: int = 400) -> T:
    if obj is None:
        raise HTTPException(status_code, message)
    return obj
