import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


class InvalidPhoneError(ValueError):
    pass


def normalize_us_phone(value: str | None) -> str | None:
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
