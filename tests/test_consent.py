from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from thecargo.consent import (
    ConsentChannel,
    ConsentScope,
    ConsentSource,
    ConsentStatus,
    Decision,
    SendType,
    evaluate,
)

ORG = UUID("00000000-0000-0000-0000-000000000001")
CUSTOMER = "+13235550100"
LINE_A = "+18005550001"
LINE_B = "+18005550002"


def _row(
    *,
    channel: ConsentChannel,
    scope: ConsentScope,
    status: ConsentStatus,
    line_number: str | None = None,
    source: ConsentSource = ConsentSource.KEYWORD,
    minutes_ago: int = 0,
    source_detail: str | None = None,
):
    created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return SimpleNamespace(
        id=uuid4(),
        organization_id=ORG,
        customer_number=CUSTOMER,
        channel=channel.value,
        scope=scope.value,
        line_number=line_number,
        status=status.value,
        source=source.value,
        source_detail=source_detail,
        created_at=created_at,
    )


def test_no_records_allows_everything():
    for ch in ConsentChannel:
        for st in SendType:
            r = evaluate([], channel=ch, our_line=LINE_A, send_type=st)
            assert r.decision is Decision.ALLOW


def test_wrong_number_blocks_all_channels_all_lines():
    rows = [
        _row(
            channel=ConsentChannel.CALL,
            scope=ConsentScope.GLOBAL,
            status=ConsentStatus.WRONG_NUMBER,
            minutes_ago=10,
        )
    ]
    for ch in ConsentChannel:
        for st in SendType:
            for line in (LINE_A, LINE_B, None):
                r = evaluate(rows, channel=ch, our_line=line, send_type=st)
                assert r.decision is Decision.BLOCK
                assert r.reason == "wrong_number"


def test_do_not_call_blocks_call_allows_text():
    rows = [
        _row(
            channel=ConsentChannel.CALL,
            scope=ConsentScope.GLOBAL,
            status=ConsentStatus.DO_NOT_CALL,
            minutes_ago=5,
        )
    ]
    call = evaluate(rows, channel=ConsentChannel.CALL, our_line=LINE_A, send_type=SendType.MASS)
    assert call.decision is Decision.BLOCK
    assert call.reason == "do_not_call"

    text = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_A, send_type=SendType.MASS)
    assert text.decision is Decision.ALLOW


def test_do_not_text_same_line_blocks_all_send_types():
    rows = [
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=LINE_A,
            status=ConsentStatus.DO_NOT_TEXT,
        )
    ]
    for st in SendType:
        r = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_A, send_type=st)
        assert r.decision is Decision.BLOCK
        assert r.reason == "do_not_text_same_line"


def test_do_not_text_other_line_manual_warns_bulk_blocks():
    rows = [
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=LINE_A,
            status=ConsentStatus.DO_NOT_TEXT,
        )
    ]
    manual = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_B, send_type=SendType.MANUAL)
    assert manual.decision is Decision.WARN
    assert manual.reason == "do_not_text_other_line_manual"

    mass = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_B, send_type=SendType.MASS)
    assert mass.decision is Decision.BLOCK
    assert mass.reason == "do_not_text_other_line_bulk"

    auto = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_B, send_type=SendType.AUTOMATED)
    assert auto.decision is Decision.BLOCK
    assert auto.reason == "do_not_text_other_line_bulk"


def test_do_not_text_does_not_affect_calls():
    rows = [
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=LINE_A,
            status=ConsentStatus.DO_NOT_TEXT,
        )
    ]
    r = evaluate(rows, channel=ConsentChannel.CALL, our_line=LINE_A, send_type=SendType.MASS)
    assert r.decision is Decision.ALLOW


def test_allowed_supersedes_earlier_block_same_line():
    rows = [
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=LINE_A,
            status=ConsentStatus.DO_NOT_TEXT,
            source=ConsentSource.KEYWORD,
            minutes_ago=60,
        ),
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=LINE_A,
            status=ConsentStatus.ALLOWED,
            source=ConsentSource.AGENT,
            minutes_ago=5,
        ),
    ]
    for st in SendType:
        r = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_A, send_type=st)
        assert r.decision is Decision.ALLOW


def test_earlier_allowed_then_later_block_still_blocks():
    rows = [
        _row(
            channel=ConsentChannel.CALL,
            scope=ConsentScope.GLOBAL,
            status=ConsentStatus.ALLOWED,
            minutes_ago=120,
        ),
        _row(
            channel=ConsentChannel.CALL,
            scope=ConsentScope.GLOBAL,
            status=ConsentStatus.DO_NOT_CALL,
            minutes_ago=10,
        ),
    ]
    r = evaluate(rows, channel=ConsentChannel.CALL, our_line=LINE_A, send_type=SendType.MASS)
    assert r.decision is Decision.BLOCK
    assert r.reason == "do_not_call"


def test_legacy_null_line_blocks_all_lines_all_send_types():
    rows = [
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=None,
            status=ConsentStatus.DO_NOT_TEXT,
            source=ConsentSource.IMPORT,
            source_detail="legacy_sms_opt_outs",
        )
    ]
    for line in (LINE_A, LINE_B):
        for st in SendType:
            r = evaluate(rows, channel=ConsentChannel.TEXT, our_line=line, send_type=st)
            assert r.decision is Decision.BLOCK
            assert r.reason == "do_not_text_legacy_any_line"


def test_wrong_number_overrides_allowed_do_not_text():
    rows = [
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=LINE_A,
            status=ConsentStatus.ALLOWED,
            minutes_ago=5,
        ),
        _row(
            channel=ConsentChannel.CALL,
            scope=ConsentScope.GLOBAL,
            status=ConsentStatus.WRONG_NUMBER,
            minutes_ago=1,
        ),
    ]
    r = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_A, send_type=SendType.MANUAL)
    assert r.decision is Decision.BLOCK
    assert r.reason == "wrong_number"


def test_result_carries_source_metadata_on_block():
    rows = [
        _row(
            channel=ConsentChannel.TEXT,
            scope=ConsentScope.LINE,
            line_number=LINE_A,
            status=ConsentStatus.DO_NOT_TEXT,
            source=ConsentSource.KEYWORD,
            source_detail="stop",
            minutes_ago=15,
        )
    ]
    r = evaluate(rows, channel=ConsentChannel.TEXT, our_line=LINE_A, send_type=SendType.MASS)
    assert r.decision is Decision.BLOCK
    assert r.source == ConsentSource.KEYWORD.value
    assert r.source_detail == "stop"
    assert r.line_number == LINE_A
    assert r.recorded_at is not None


@pytest.mark.parametrize(
    "existing_status,expected",
    [
        (ConsentStatus.DO_NOT_CALL, Decision.BLOCK),
        (ConsentStatus.WRONG_NUMBER, Decision.BLOCK),
        (ConsentStatus.ALLOWED, Decision.ALLOW),
    ],
)
def test_global_call_status_matrix(existing_status, expected):
    rows = [
        _row(
            channel=ConsentChannel.CALL,
            scope=ConsentScope.GLOBAL,
            status=existing_status,
            minutes_ago=1,
        )
    ]
    r = evaluate(rows, channel=ConsentChannel.CALL, our_line=LINE_A, send_type=SendType.MASS)
    assert r.decision is expected
