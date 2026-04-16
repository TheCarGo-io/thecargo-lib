from typing import Generic, TypeVar

from thecargo.schemas.base import AppSchema

T = TypeVar("T")


class PaginatedResponse(AppSchema, Generic[T]):
    count: int
    results: list[T]
