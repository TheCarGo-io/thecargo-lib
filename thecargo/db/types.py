from sqlalchemy.types import String, TypeDecorator

from thecargo.utils.phone import InvalidPhoneError, normalize_us_phone


class USPhoneType(TypeDecorator):
    impl = String(50)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        if "%" in value or "_" in value:
            return value
        try:
            return normalize_us_phone(value)
        except InvalidPhoneError:
            return value

    def process_result_value(self, value, dialect):
        return value


class EmailType(TypeDecorator):
    impl = String(255)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        return normalized or None

    def process_result_value(self, value, dialect):
        return value
