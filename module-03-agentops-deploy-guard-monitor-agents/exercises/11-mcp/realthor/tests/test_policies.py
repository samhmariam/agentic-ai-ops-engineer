import pytest
from realthor.policies import PolicyDecision, evaluate_channel_policy

THRESHOLD = 500_000


def test_marketplace_never_requires_approval():
    decision = evaluate_channel_policy("marketplace", 1_000_000, "analyst", THRESHOLD)
    assert not decision.requires_approval


def test_marketplace_risk_level_is_low():
    decision = evaluate_channel_policy("marketplace", 600_000, "analyst", THRESHOLD)
    assert decision.risk_level == "low"


def test_ibuyer_below_threshold_no_approval():
    decision = evaluate_channel_policy("ibuyer", 400_000, "analyst", THRESHOLD)
    assert not decision.requires_approval


def test_ibuyer_below_threshold_risk_level_is_medium():
    decision = evaluate_channel_policy("ibuyer", 400_000, "analyst", THRESHOLD)
    assert decision.risk_level == "medium"


def test_ibuyer_above_threshold_requires_approval():
    decision = evaluate_channel_policy("ibuyer", 610_000, "analyst", THRESHOLD)
    assert decision.requires_approval


def test_ibuyer_above_threshold_risk_level_is_high():
    decision = evaluate_channel_policy("ibuyer", 610_000, "analyst", THRESHOLD)
    assert decision.risk_level == "high"


def test_ibuyer_above_threshold_reason_includes_amounts():
    decision = evaluate_channel_policy("ibuyer", 610_000, "analyst", THRESHOLD)
    assert "610,000" in decision.reason
    assert "500,000" in decision.reason


def test_ibuyer_exactly_at_threshold_no_approval():
    # Boundary: > threshold triggers, == threshold does not
    decision = evaluate_channel_policy("ibuyer", THRESHOLD, "analyst", THRESHOLD)
    assert not decision.requires_approval


def test_unknown_channel_no_approval():
    decision = evaluate_channel_policy("unknown_channel", 1_000_000, "analyst", THRESHOLD)
    assert not decision.requires_approval
