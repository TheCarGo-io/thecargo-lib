"""US phone normalization backed by Google's libphonenumber.

Canonical storage format is E.164 (`+13231234567`). All API entry points should
apply :func:`normalize_us_phone` (via the Pydantic :class:`~thecargo.schemas.types.USPhone`
type alias) before persistence so downstream code can assume one shape.

For display, :func:`format_us_phone` returns the national layout
``(323) 123-4567`` — it is non-throwing and falls back to the raw value if
normalization fails.
"""

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


class InvalidPhoneError(ValueError):
    """Raised when a value cannot be parsed as a valid US phone number."""


def normalize_us_phone(value: str | None) -> str | None:
    """Parse any US phone format into E.164.

    Returns ``None`` for empty inputs. Raises :class:`InvalidPhoneError` for
    values that cannot be parsed or are not valid US numbers, so schema-level
    validators can surface a clear 422 to the client.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        value = stripped
    try:
        num = phonenumbers.parse(value, "US")
    except NumberParseException as exc:
        raise InvalidPhoneError(f"Invalid phone: {exc}") from exc
    if not phonenumbers.is_valid_number(num):
        raise InvalidPhoneError("Invalid US phone number")
    return phonenumbers.format_number(num, PhoneNumberFormat.E164)


def format_us_phone(value: str | None) -> str | None:
    """Render ``value`` in national display layout (``(323) 123-4567``).

    Non-throwing: returns the raw value when normalization fails so legacy
    data passes through views unchanged.
    """
    if value is None:
        return None
    try:
        normalized = normalize_us_phone(value)
    except InvalidPhoneError:
        return value
    if not normalized:
        return None
    num = phonenumbers.parse(normalized, "US")
    return phonenumbers.format_number(num, PhoneNumberFormat.NATIONAL)


def normalize_phone(value: str | None) -> str | None:
    """Legacy alias — returns ``None`` on invalid input instead of raising.

    Kept for communication-service callers (``webhooks.py``, ``send.py``,
    ``ringcentral.py``) that use the ``normalize_phone(x) or fallback`` pattern
    and expect silent failure. New code should import
    :func:`normalize_us_phone` and handle :class:`InvalidPhoneError` explicitly.
    """
    try:
        return normalize_us_phone(value)
    except InvalidPhoneError:
        return None


format_phone = format_us_phone


def is_valid_us_phone(value: str | None) -> bool:
    if not value:
        return False
    try:
        normalize_us_phone(value)
    except InvalidPhoneError:
        return False
    return True
