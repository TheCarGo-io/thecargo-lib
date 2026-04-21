from typing import Generic, TypeVar

from fastapi_pagination import Page
from fastapi_pagination.customization import CustomizedPage, UseParamsFields

from thecargo.schemas.base import AppSchema

T = TypeVar("T")

CustomPage = CustomizedPage[
    Page,
    UseParamsFields(size=50),
]


class PaginatedResponse(AppSchema, Generic[T]):
    count: int
    results: list[T]
