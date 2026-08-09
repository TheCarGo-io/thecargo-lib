from enum import Enum


class DeliverabilityReason(str, Enum):
    LANDLINE = "landline_or_voip"
    INVALID = "invalid_number"
    OPTED_OUT = "opted_out"
    HARD_BOUNCED = "hard_bounced"


DELIVERABILITY_REASON_ORDER: tuple[DeliverabilityReason, ...] = (
    DeliverabilityReason.LANDLINE,
    DeliverabilityReason.INVALID,
    DeliverabilityReason.OPTED_OUT,
    DeliverabilityReason.HARD_BOUNCED,
)

DELIVERABILITY_REASON_LABELS: dict[str, str] = {
    DeliverabilityReason.LANDLINE.value: "Landline",
    DeliverabilityReason.INVALID.value: "Invalid or unreachable",
    DeliverabilityReason.OPTED_OUT.value: "Opted out (STOP)",
    DeliverabilityReason.HARD_BOUNCED.value: "Previously hard-bounced",
}

TELNYX_ERROR_REASONS: dict[str, DeliverabilityReason] = {
    "40001": DeliverabilityReason.LANDLINE,
    "40301": DeliverabilityReason.LANDLINE,
    "40021": DeliverabilityReason.LANDLINE,
    "30006": DeliverabilityReason.LANDLINE,
    "40012": DeliverabilityReason.INVALID,
    "40310": DeliverabilityReason.INVALID,
    "30005": DeliverabilityReason.INVALID,
    "10001": DeliverabilityReason.INVALID,
    "10002": DeliverabilityReason.INVALID,
    "40300": DeliverabilityReason.OPTED_OUT,
    "40004": DeliverabilityReason.HARD_BOUNCED,
}

_LANDLINE_LINE_TYPES = frozenset({"landline", "voip", "fixed_voip", "non_fixed_voip", "fixedvoip", "nonfixedvoip"})


def classify_error_code(code: str | None, line_type: str | None = None) -> DeliverabilityReason | None:
    if line_type and line_type.strip().lower() in _LANDLINE_LINE_TYPES:
        return DeliverabilityReason.LANDLINE
    if not code:
        return None
    return TELNYX_ERROR_REASONS.get(str(code).strip())


def deliverability_reason_label(reason: str | None) -> str | None:
    if reason is None:
        return None
    return DELIVERABILITY_REASON_LABELS.get(reason, reason)
