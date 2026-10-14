from thecargo.features import FEATURES, GATED_RESOURCES, allowed_resources
from thecargo.permissions import CARRIER_RESOURCES, PHONE_RESOURCES, RESOURCE_SET


def test_every_feature_resource_is_a_permission():
    assert GATED_RESOURCES <= RESOURCE_SET


def test_all_features_keep_every_resource():
    assert allowed_resources(set(FEATURES)) == RESOURCE_SET


def test_start_plan_loses_reports_campaigns_and_dialer_only():
    allowed = allowed_resources({"phone", "recording", "ai"})
    assert {"telephony", "conversation", "wallet", "subscription", "user", "role"} <= allowed
    assert not {"analytics", "campaign", "automation", "power_dialer"} & allowed


def test_the_broker_workspace_needs_the_os_feature():
    workspace = {"shipment", "lead", "quote", "order", "customer", "carrier", "loadboard", "payment"}

    assert not workspace & allowed_resources({"phone", "campaign", "analytics"})
    assert workspace <= allowed_resources({"os"})


def test_os_takes_nothing_from_a_carrier_or_a_phone_organization():
    assert not set(FEATURES["os"].resources) & (CARRIER_RESOURCES | PHONE_RESOURCES)


def test_admin_screens_wallet_and_reports_are_never_gated():
    ungated = {"user", "team", "role", "company_info", "audit", "subscription", "wallet", "dashboard", "insight"}
    assert ungated <= allowed_resources(set())
