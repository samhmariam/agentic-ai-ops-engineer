"""Policy evaluation for RealThor channel recommendations.

Policies evaluate conditions and return decisions — they are conditional.
Guardrails enforce constraints unconditionally.
"""

from dataclasses import dataclass


@dataclass
class PolicyDecision:
    requires_approval: bool
    reason: str = ""
    risk_level: str = "low"  # "low" | "medium" | "high"


def evaluate_channel_policy(
    channel: str,
    estimated_value: float,
    role: str,
    threshold: float,
) -> PolicyDecision:
    """Evaluate whether a channel recommendation requires human approval.

    Args:
        channel: Recommended channel ("marketplace" or "ibuyer").
        estimated_value: Estimated investment value for the opportunity.
        role: Caller's role (passed to support future per-role thresholds).
        threshold: Investment amount above which iBuyer requires approval.

    Returns:
        PolicyDecision with requires_approval, reason, and risk_level.
    """
    if channel == "marketplace":
        return PolicyDecision(requires_approval=False, risk_level="low")

    if channel == "ibuyer":
        if estimated_value > threshold:
            return PolicyDecision(
                requires_approval=True,
                reason=(
                    f"iBuyer investment of ${estimated_value:,.0f} exceeds "
                    f"${threshold:,.0f} approval threshold"
                ),
                risk_level="high",
            )
        return PolicyDecision(requires_approval=False, risk_level="medium")

    return PolicyDecision(requires_approval=False, risk_level="low")
