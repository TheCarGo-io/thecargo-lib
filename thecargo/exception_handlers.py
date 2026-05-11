"""Shared FastAPI exception handlers for domain errors raised by thecargo models.

Register on each service's FastAPI app right after construction:

.. code-block:: python

    from thecargo.exception_handlers import register_model_validation_handlers

    app = FastAPI(...)
    register_model_validation_handlers(app)

Without these, :class:`thecargo.models.base.FieldTooLongError` bubbles up
as an unhandled 500 because FastAPI does not auto-convert ``ValueError``.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from thecargo.models.base import FieldTooLongError


async def _field_too_long_handler(request: Request, exc: FieldTooLongError) -> JSONResponse:
    """Translate model-layer length overflow into a 422 mirroring Pydantic's shape."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "type": "string_too_long",
                    "loc": ["body", exc.column],
                    "msg": (f"String should have at most {exc.max_length} characters (got {exc.actual_length})"),
                    "ctx": {"max_length": exc.max_length, "actual_length": exc.actual_length},
                }
            ]
        },
    )


def register_model_validation_handlers(app: FastAPI) -> None:
    """Wire up handlers for every domain error raised by thecargo models."""
    app.add_exception_handler(FieldTooLongError, _field_too_long_handler)
