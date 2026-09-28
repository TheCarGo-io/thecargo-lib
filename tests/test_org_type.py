import asyncio
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from thecargo.dependencies import auth as auth_dep
from thecargo.permissions import (
    PHONE_ONLY_RESOURCES,
    PHONE_RESOURCES,
    RESOURCE_SET,
    build_permission_groups,
    resources_for,
)
from thecargo.role_templates import PHONE_TEMPLATES, SUPERUSER, TEMPLATES, templates_for

SECRET = "test-secret-at-least-thirty-two-bytes"


def _keys(groups: list[dict]) -> set[str]:
    keys = set()
    for group in groups:
        for node in group["resources"]:
            keys.add(node["key"])
            keys.update(child["key"] for child in node.get("children") or [])
    return keys


def test_broker_and_carrier_never_see_phone_only_resources():
    assert resources_for("broker") == RESOURCE_SET - PHONE_ONLY_RESOURCES
    assert resources_for("carrier") == resources_for("broker")
    assert not _keys(build_permission_groups({}, "broker")) & PHONE_ONLY_RESOURCES


def test_phone_editor_shows_only_phone_resources():
    assert _keys(build_permission_groups({}, "phone")) == PHONE_RESOURCES


def test_unfiltered_groups_keep_the_full_catalog():
    assert _keys(build_permission_groups({})) == RESOURCE_SET


def test_broker_superuser_gains_nothing_phone_only():
    assert not {key.split(".")[0] for key in SUPERUSER} & PHONE_ONLY_RESOURCES


def test_templates_follow_org_type():
    assert templates_for("broker") is TEMPLATES
    assert templates_for(None) is TEMPLATES
    assert templates_for("phone") is PHONE_TEMPLATES


def test_phone_templates_stay_inside_phone_resources():
    for template in PHONE_TEMPLATES.values():
        assert {key.split(".")[0] for key in template} <= PHONE_RESOURCES


def _token(**extra) -> HTTPAuthorizationCredentials:
    payload = {"user_id": str(uuid4()), "org_id": str(uuid4()), "type": "access", "p": {}, **extra}
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(payload, SECRET, algorithm="HS256"))


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)

    async def _state(user, check_role):
        return [None, 0, None, None, None]

    monkeypatch.setattr(auth_dep, "_token_state", _state)


def test_token_without_ot_is_a_broker(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORG_TYPES", raising=False)
    user = asyncio.run(auth_dep.get_current_user(_token()))
    assert user.org_type == "broker"


def test_allowed_org_types_rejects_phone(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORG_TYPES", "broker,carrier")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_dep.get_current_user(_token(ot="phone")))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "org_type_not_allowed"


def test_allowed_org_types_lets_legacy_token_through(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORG_TYPES", "broker,carrier")
    assert asyncio.run(auth_dep.get_current_user(_token())).org_type == "broker"
    assert asyncio.run(auth_dep.get_current_user(_token(ot="carrier"))).org_type == "carrier"


def test_empty_allowed_org_types_is_off(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORG_TYPES", "")
    assert asyncio.run(auth_dep.get_current_user(_token(ot="phone"))).org_type == "phone"
