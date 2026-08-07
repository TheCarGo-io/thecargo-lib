from thecargo.deliverability import (
    DELIVERABILITY_REASON_LABELS,
    DELIVERABILITY_REASON_ORDER,
    TELNYX_ERROR_REASONS,
    DeliverabilityReason,
    classify_error_code,
    deliverability_reason_label,
)


def test_four_reason_buckets_match_figma():
    assert [r.value for r in DELIVERABILITY_REASON_ORDER] == [
        "landline_or_voip",
        "invalid_number",
        "opted_out",
        "hard_bounced",
    ]


def test_every_reason_has_a_label():
    for reason in DeliverabilityReason:
        assert DELIVERABILITY_REASON_LABELS[reason.value]
    assert deliverability_reason_label("landline_or_voip") == "Landline"
    assert deliverability_reason_label("invalid_number") == "Invalid or unreachable"
    assert deliverability_reason_label("opted_out") == "Opted out (STOP)"
    assert deliverability_reason_label("hard_bounced") == "Previously hard-bounced"


def test_telnyx_codes_classify_to_expected_reasons():
    cases = {
        "40001": DeliverabilityReason.LANDLINE,
        "40012": DeliverabilityReason.INVALID,
        "40310": DeliverabilityReason.INVALID,
        "40008": DeliverabilityReason.INVALID,
        "10001": DeliverabilityReason.INVALID,
        "10002": DeliverabilityReason.INVALID,
        "40300": DeliverabilityReason.OPTED_OUT,
        "40004": DeliverabilityReason.HARD_BOUNCED,
    }
    for code, reason in cases.items():
        assert classify_error_code(code) is reason


def test_line_type_overrides_to_landline():
    assert classify_error_code(None, "landline") is DeliverabilityReason.LANDLINE
    assert classify_error_code("40012", "voip") is DeliverabilityReason.LANDLINE


def test_transient_and_sender_codes_never_flag_the_number():
    for code in ("40002", "40003", "40005", "40006", "40011", "40013", "40015", "40017"):
        assert classify_error_code(code) is None


def test_unknown_and_empty_codes_return_none():
    assert classify_error_code(None) is None
    assert classify_error_code("") is None
    assert classify_error_code("99999") is None


def test_every_classified_code_has_a_label():
    for reason in TELNYX_ERROR_REASONS.values():
        assert deliverability_reason_label(reason.value)
