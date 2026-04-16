from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AppSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )


class IDSchema(AppSchema):
    id: UUID


class MessageSchema(AppSchema):
    message: str
