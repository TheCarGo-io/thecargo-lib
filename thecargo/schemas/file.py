from uuid import UUID

from pydantic import ConfigDict

from thecargo.schemas.base import AppSchema


class FileRef(AppSchema):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
