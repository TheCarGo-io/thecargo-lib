"""SQLAlchemy column types shared across services."""

from sqlalchemy.types import String, TypeDecorator

from thecargo.utils.phone import InvalidPhoneError, normalize_us_phone


class USPhoneType(TypeDecorator):
    """String column that stores US phones as E.164.

    Serves as a safety-net normalizer for writes that bypass the Pydantic
    :class:`~thecargo.schemas.types.USPhone` validator (Celery tasks, event
    handlers, bulk imports, internal admin writes). The canonical validation
    still happens at the API boundary — this type just guarantees storage
    consistency when someone assigns a raw string via the ORM.

    Column length is kept at 50 to match the existing schema so adopting this
    type does not require an ``ALTER COLUMN TYPE`` on tables that already
    stored looser strings.

    Query-time safety: values containing SQL ``LIKE`` wildcards (``%`` / ``_``)
    pass through unchanged so ``phone.ilike('%323%')`` patterns are not
    mangled by normalization. Unparseable plain strings also pass through so
    that a stale-data read path never crashes the query; writes coming from
    validated schemas will already be E.164 before they reach this layer.
    """

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
