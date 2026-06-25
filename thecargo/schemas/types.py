from typing import Annotated

from pydantic import BeforeValidator

from thecargo.utils.phone import normalize_us_phone

USPhone = Annotated[str | None, BeforeValidator(normalize_us_phone)]
