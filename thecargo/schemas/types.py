"""Pydantic type aliases shared across services."""

from typing import Annotated

from pydantic import BeforeValidator

from thecargo.utils.phone import normalize_us_phone

USPhone = Annotated[str | None, BeforeValidator(normalize_us_phone)]
"""Pydantic field that normalizes any US phone format to E.164 on input.

Use at the API boundary::

    class CustomerCreate(AppSchema):
        phone: USPhone = None

Invalid values raise :class:`~thecargo.utils.phone.InvalidPhoneError`, which
Pydantic surfaces as a 422 with field-level attribution.
"""
