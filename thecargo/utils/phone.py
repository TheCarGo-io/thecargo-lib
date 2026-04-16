import re


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"[^\d]", "", phone)
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) > 10:
        return f"+{digits}"
    return None


def is_valid_us_phone(phone: str | None) -> bool:
    if not phone:
        return False
    normalized = normalize_phone(phone)
    if not normalized:
        return False
    return bool(re.match(r"^\+1[2-9]\d{9}$", normalized))


def format_phone(phone: str | None) -> str | None:
    normalized = normalize_phone(phone)
    if not normalized or len(normalized) != 12:
        return normalized
    return f"+1 ({normalized[2:5]}) {normalized[5:8]}-{normalized[8:]}"
