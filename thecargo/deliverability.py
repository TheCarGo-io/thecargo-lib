from enum import Enum


class DeliverabilityReason(str, Enum):
    LANDLINE = "landline_or_voip"
    INVALID = "invalid_number"


DELIVERABILITY_REASON_LABELS: dict[str, str] = {
    DeliverabilityReason.LANDLINE.value: "Landline / VoIP",
    DeliverabilityReason.INVALID.value: "Invalid number",
}
