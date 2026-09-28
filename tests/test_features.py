from thecargo.features import FEATURES, GATED_RESOURCES, allowed_resources
from thecargo.permissions import PHONE_ONLY_RESOURCES, RESOURCE_SET


def test_every_feature_resource_is_a_permission():
    assert GATED_RESOURCES <= RESOURCE_SET


def test_all_features_keep_every_resource():
    assert allowed_resources(set(FEATURES)) == RESOURCE_SET


def test_start_plan_loses_reports_campaigns_and_dialer_only():
    allowed = allowed_resources({"phone", "recording", "ai"})
    assert {"telephony", "conversation", "wallet", "subscription", "user", "role"} <= allowed
    assert not {"analytics", "campaign", "automation", "power_dialer"} & allowed


def test_broker_resources_are_never_gated():
    broker_only = RESOURCE_SET - PHONE_ONLY_RESOURCES - GATED_RESOURCES
    assert broker_only <= allowed_resources(set())
    assert {"shipment", "lead", "order", "carrier", "loadboard"} <= broker_only
