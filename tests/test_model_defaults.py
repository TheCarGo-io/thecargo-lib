"""Every model reads the timestamps the database sets back through the write's own statement.

``updated_at`` is set by the database on every UPDATE. The ORM used to expire it after the flush, so the next access
cost one more SELECT, and on the GCP stack that SELECT ran inside the write transaction and held its pooled server
connection a round trip longer. With ``eager_defaults`` the UPDATE's RETURNING brings the value back; the shipment suite
checks the statements on Postgres.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from thecargo.models.base import BaseModel, ReferenceModel, SoftDeleteModel


class Widget(BaseModel):
    __tablename__ = "widgets_model_defaults"

    name: Mapped[str] = mapped_column(String(40))


class Gadget(SoftDeleteModel):
    __tablename__ = "gadgets_model_defaults"


class Place(ReferenceModel):
    __tablename__ = "places_model_defaults"


def test_every_model_base_reads_server_set_timestamps_back_with_the_write():
    assert all(model.__mapper__.eager_defaults is True for model in (Widget, Gadget, Place))
