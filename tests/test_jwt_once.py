import jwt
import pytest

from thecargo import jwt_once
from thecargo.jwt_once import decode_once

SECRET = "s" * 32


def _counting(monkeypatch) -> list[str]:
    calls: list[str] = []
    real = jwt.decode

    def _decode(token, *args, **kwargs):
        calls.append(token)
        return real(token, *args, **kwargs)

    monkeypatch.setattr(jwt_once.jwt, "decode", _decode)
    return calls


def test_one_request_decodes_its_token_once(monkeypatch):
    calls = _counting(monkeypatch)
    token = jwt.encode({"user_id": "u"}, SECRET, algorithm="HS256")
    scope: dict = {}

    first = decode_once(scope, token, SECRET)
    second = decode_once(scope, token, SECRET)

    assert first == second == {"user_id": "u"}
    assert len(calls) == 1


def test_another_token_or_secret_is_decoded_again(monkeypatch):
    calls = _counting(monkeypatch)
    scope: dict = {}
    decode_once(scope, jwt.encode({"n": 1}, SECRET, algorithm="HS256"), SECRET)
    decode_once(scope, jwt.encode({"n": 2}, SECRET, algorithm="HS256"), SECRET)
    with pytest.raises(jwt.InvalidSignatureError):
        decode_once(scope, jwt.encode({"n": 2}, SECRET, algorithm="HS256"), "x" * 32)

    assert len(calls) == 3


def test_a_bad_token_raises_every_time(monkeypatch):
    calls = _counting(monkeypatch)
    scope: dict = {}
    for _ in range(2):
        with pytest.raises(jwt.PyJWTError):
            decode_once(scope, "not-a-token", SECRET)

    assert len(calls) == 2


def test_without_a_scope_it_just_decodes():
    token = jwt.encode({"user_id": "u"}, SECRET, algorithm="HS256")

    assert decode_once(None, token, SECRET) == {"user_id": "u"}
