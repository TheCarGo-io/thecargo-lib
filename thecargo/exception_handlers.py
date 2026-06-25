from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from thecargo.models.base import FieldTooLongError


async def _field_too_long_handler(request: Request, exc: FieldTooLongError) -> JSONResponse:
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
    app.add_exception_handler(FieldTooLongError, _field_too_long_handler)
