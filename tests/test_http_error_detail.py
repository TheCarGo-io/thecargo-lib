"""A generic translation is a fallback, not an override.

`common.http_409` is "Conflict", and translating unconditionally turned
"This invoice is already settled — there is nothing to chase" into that one
word. Every 400/404/409/500/502 on the platform lost the sentence that told the
user what to do; 422 escaped only because the catalogue has no entry for it.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from thecargo.handlers import register_handlers

pytestmark = pytest.mark.asyncio

LOCALES = Path(__file__).resolve().parent.parent / "thecargo" / "locale"


def _app() -> FastAPI:
    app = FastAPI()
    register_handlers(app, locale_dir=LOCALES)

    @app.get("/settled")
    async def settled():
        raise HTTPException(409, "This invoice is already settled — there is nothing to chase")

    @app.get("/missing")
    async def missing():
        raise HTTPException(400, "Payment not found")

    @app.get("/gateway")
    async def gateway():
        raise HTTPException(502, "The gateway refused the refund")

    @app.get("/unprocessable")
    async def unprocessable():
        raise HTTPException(422, "Refund amount is not valid for this payment")

    @app.get("/bare-conflict")
    async def bare_conflict():
        raise HTTPException(409)

    @app.get("/bare-forbidden")
    async def bare_forbidden():
        raise HTTPException(403)

    @app.get("/structured")
    async def structured():
        raise HTTPException(502, detail={"detail": "Upstream refused it", "code": "GATEWAY"})

    return app


async def _get(path: str, lang: str = "en") -> tuple[int, dict]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as client:
        response = await client.get(path, headers={"Accept-Language": lang})
    return response.status_code, response.json()


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/settled", "This invoice is already settled — there is nothing to chase"),
        ("/missing", "Payment not found"),
        ("/gateway", "The gateway refused the refund"),
        ("/unprocessable", "Refund amount is not valid for this payment"),
    ],
)
async def test_a_message_the_raiser_wrote_reaches_the_client(path, expected):
    status, body = await _get(path)
    assert body["message"] == expected
    assert body["detail"] == expected, "both fields carry it — old clients read `detail`"


async def test_the_status_code_is_untouched():
    assert (await _get("/settled"))[0] == 409
    assert (await _get("/gateway"))[0] == 502


async def test_saying_nothing_still_gets_the_catalogue_wording():
    _, body = await _get("/bare-forbidden")
    assert body["message"] == "Insufficient permissions", "not the bare HTTP phrase"


async def test_saying_nothing_still_localises():
    _, body = await _get("/bare-conflict", lang="ru")
    assert body["message"] == "Конфликт состояния"


async def test_a_written_message_is_not_replaced_by_a_translation_of_its_status():
    """The trade-off, made explicit.

    A sentence someone wrote in English cannot be translated at runtime, so it
    is returned as written. Losing it entirely was the worse of the two.
    """
    _, body = await _get("/settled", lang="ru")
    assert body["message"].startswith("This invoice is already settled")


async def test_the_envelope_keeps_its_shape():
    _, body = await _get("/settled")
    assert set(body) == {"code", "key", "message", "params", "detail"}
    assert body["code"] == "HTTP_409"
    assert body["key"] == "common.http_409"


async def test_a_structured_detail_still_unwraps_to_its_message():
    _, body = await _get("/structured")
    assert body["message"] == "Upstream refused it"
    assert body["params"] == {"code": "GATEWAY"}, "the extra keys stay addressable as params"
