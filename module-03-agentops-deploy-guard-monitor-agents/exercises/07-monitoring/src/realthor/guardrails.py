import json
import re
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd
from langchain.agents.middleware import AgentMiddleware, AgentState, HumanInTheLoopMiddleware, hook_config
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime

from realthor.policies import evaluate_channel_policy


# ---------------------------------------------------------------------------
# Identity context
# ---------------------------------------------------------------------------

@dataclass
class UserContext:
    """Resolved from users.csv — never trusted from the caller."""
    user_id: str = ""
    role: str = "guest"
    region_access: str = ""  # "all" for analysts; pipe-separated for brokers; "" for guest

    def can_access_region(self, region: str) -> bool:
        if self.region_access == "all":
            return True
        return region in self.region_access.split("|")


GUEST_CONTEXT = UserContext()


# ---------------------------------------------------------------------------
# Input guardrail — policy word lists
# ---------------------------------------------------------------------------

DEMOGRAPHIC_TERMS = [
    "income area", "low-income", "high-income", "credit access",
    "ethnicity", "ethnic", "race", "racial", "demographic",
    "gentrification", "underserved neighborhood", "socioeconomic",
    "poverty rate", "wealth distribution", "income distribution",
]

PERSONA_ESCALATION_PHRASES = [
    "pretend you are", "act as an", "act as a ", "you are now",
    "act like an analyst", "ignore your role", "forget your instructions",
    "override your", "bypass your", "as an internal analyst",
    "as if you were an analyst", "with full access",
]

TOPIC_DEVIATION_TERMS = [
    "who won", "who is winning", "who beat", "score of",
    "world cup", "soccer", "football", "nba", "basketball",
    "stock", "weather", "forecast", "python", "recipe",
    "news", "celebrity", "movie", "music", "tips", "review",
]

GEOGRAPHY_TERMS = [
    "new york", "los angeles", "london", "paris", "barcelona",
    "madrid", "berlin", "dubai", "singapore", "sydney",
    "toronto", "chicago", "miami", "boston", "amsterdam",
    "tokyo", "hong kong", "new york city",
]


# ---------------------------------------------------------------------------
# Tool guardrail — policy lists
# ---------------------------------------------------------------------------

SENSITIVE_FIELDS = [
    "demographic_notes",
    "seller_name", "seller_motivation",
    "owner_contact", "acquisition_strategy", "internal_score",
    "buyer_name", "credit_score_band", "pre_approval_status",
    "commission_amount", "agent_performance_score",
]

ACTION_TOOLS = {"flag_segment_for_review", "create_segment_report", "submit_channel_recommendation"}

MUTATION_TOOLS = {
    "update_listing", "delete_record", "overwrite_dataset", "add_record",
    "update_asking_price", "delete_lead", "overwrite_csv",
}

# Reasons that must terminate the run — the model must not fall back to a
# different tool call to work around the block. Extend this set when adding
# new user-context access restrictions.
TERMINAL_ACCESS_REASONS = {"region_access", "dataset_mutation", "broker_action_restriction"}


# ---------------------------------------------------------------------------
# Output guardrail — policy lists
# ---------------------------------------------------------------------------

SENSITIVE_OUTPUT_PHRASES = [
    "demographic transition",
    "underserved area",
    "underserved neighborhood",
    "minority neighborhood",
    "credit-challenged",
    "low income concentration",
    "seller's motivation",
    "seller motivation is",
    "seller contact",
    "owner contact",
]

PROFANITY_OUTPUT_MARKERS = [
    "incompetent", "terrible brokers", "useless agents", "pathetic",
    "disgusting", "horrible performance", "worst ever",
    "stupid", "idiotic",
]

DATA_MUTATION_PATTERNS = [
    r"\bdelete\b.*\b(listing|lead|record|row|csv|file|data)\b",
    r"\bupdate\b.*\b(csv|file|listing|price|record)\b",
    r"\boverwrite\b.*\b(csv|data|file)\b",
    r"\bdrop\b.*\b(table|column|csv)\b",
    r"\bremove\b.*\b(listing|record|file|csv)\b",
]

SENSITIVE_FIELD_QUERY_TERMS = [
    "internal_score",
    "commission_amount",
    "seller_motivation",
    "seller's motivation",
    "owner_contact",
    "acquisition_strategy",
    "agent_performance_score",
]

GEOGRAPHY_LEAK_TERMS = [
    "new york", "los angeles", "london", "paris", "barcelona",
    "madrid", "berlin", "dubai", "singapore", "sydney",
    "toronto", "chicago", "miami", "boston",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blocked_response(reason: str, message: str) -> str:
    return json.dumps({"status": "blocked", "reason": reason, "message": message})


def _redact_sensitive_fields(text: str) -> tuple[str, list[str]]:
    """Strip sensitive field values from tool output. Returns (cleaned_text, redacted_fields)."""
    redacted = []
    for field in SENSITIVE_FIELDS:
        pattern = rf"(?i)({re.escape(field)})\s*[:=][^\n,]+"
        if re.search(pattern, text):
            text = re.sub(pattern, rf"\1: [REDACTED]", text)
            redacted.append(field)
    return text, redacted


# ---------------------------------------------------------------------------
# Layer 1 — Input guardrail
# ---------------------------------------------------------------------------

class InputGuardrails(AgentMiddleware):
    """Block prohibited queries before the agent runs."""

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if not state["messages"]:
            return None
        first_msg = state["messages"][0]
        if first_msg.type != "human":
            return None
        query = first_msg.content.lower()

        # demographic_query: Ciudaty datasets have no demographic dimension;
        # answering from training data produces fabricated analysis.
        if any(term in query for term in DEMOGRAPHIC_TERMS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "demographic_query",
                    "RealThor does not analyze demographic or socioeconomic data. "
                    "Please ask about market signals, listing velocity, or supply/demand for Ciudaty segments.",
                ))],
                "jump_to": "end",
            }

        # persona_escalation: the model is susceptible to identity manipulation;
        # system-level enforcement is required.
        if any(phrase in query for phrase in PERSONA_ESCALATION_PHRASES):
            return {
                "messages": [AIMessage(_blocked_response(
                    "persona_escalation",
                    "Identity and access level are enforced by the system. "
                    "Your role cannot be changed via the conversation.",
                ))],
                "jump_to": "end",
            }

        # topic_adherence: off-topic queries waste API cost; tools are Ciudaty-specific.
        if any(term in query for term in TOPIC_DEVIATION_TERMS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "topic_adherence",
                    "RealThor is a Ciudaty listing intelligence tool. This query is outside its scope.",
                ))],
                "jump_to": "end",
            }

        # geography_restriction: all datasets are Ciudaty-specific; cross-market
        # recommendations are fabricated from training data.
        if any(term in query for term in GEOGRAPHY_TERMS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "geography_restriction",
                    "RealThor operates exclusively in Ciudaty. "
                    "Data for other markets is not available.",
                ))],
                "jump_to": "end",
            }

        # profanity_toxicity: block abusive or toxic input language.
        if any(marker in query for marker in PROFANITY_OUTPUT_MARKERS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "profanity_toxicity",
                    "This query contains inappropriate language and cannot be processed.",
                ))],
                "jump_to": "end",
            }

        # sensitive_field_read: block queries that explicitly name restricted fields.
        if any(term in query for term in SENSITIVE_FIELD_QUERY_TERMS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "sensitive_field_read",
                    "That field is restricted and cannot be queried directly.",
                ))],
                "jump_to": "end",
            }

        # data_mutation_instruction: datasets are read-only reference data;
        # block instructions that try to modify or delete them via natural language.
        if any(re.search(pattern, query) for pattern in DATA_MUTATION_PATTERNS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "data_mutation_instruction",
                    "RealThor datasets are read-only. "
                    "Modifications, deletions, and overwrites are not permitted.",
                ))],
                "jump_to": "end",
            }

        return None


# ---------------------------------------------------------------------------
# Layer 2 — Tool/access guardrail
# ---------------------------------------------------------------------------

class ToolGuardrails(AgentMiddleware):
    """Enforce role-based access on tool calls and redact sensitive fields.

    wrap_tool_call blocks the individual tool call and records the reason in
    the ToolMessage. before_model fires before each model iteration; if any
    blocked ToolMessage in the history has a reason in TERMINAL_ACCESS_REASONS,
    it terminates the run before the model can fall back to a different tool call
    to work around the block.
    """

    def wrap_tool_call(self, request, handler: Callable) -> Any:
        tool_name: str = request.tool_call["name"]
        tool_call_id: str = request.tool_call["id"]
        ctx: UserContext = request.runtime.context
        tool_args: dict = request.tool_call["args"]

        def _blocked_tool(reason: str, msg: str) -> ToolMessage:
            return ToolMessage(
                content=_blocked_response(reason, msg),
                name=tool_name,
                tool_call_id=tool_call_id,
            )

        # dataset_mutation: datasets are read-only reference data.
        if tool_name in MUTATION_TOOLS:
            return _blocked_tool("dataset_mutation", "Datasets are read-only. Mutations are not permitted.")

        # broker_action_restriction: only analysts may trigger internal workflows.
        if tool_name in ACTION_TOOLS and ctx.role != "analyst":
            return _blocked_tool(
                "broker_action_restriction",
                f"Tool '{tool_name}' requires analyst access. "
                f"Your role ({ctx.role}) does not permit this action.",
            )

        # region_access: block the tool call. before_model will detect this in
        # the message history and terminate the run before the next model call.
        requested_region = tool_args.get("region") or tool_args.get("region_name")
        if requested_region and not ctx.can_access_region(requested_region):
            return _blocked_tool(
                "region_access",
                f"Access denied. You are not licensed for the '{requested_region}' region.",
            )

        result = handler(request)

        # sensitive_field_read: strip sensitive values from all tool outputs.
        if isinstance(result, ToolMessage) and isinstance(result.content, str):
            cleaned, redacted = _redact_sensitive_fields(result.content)
            if redacted:
                note = (
                    f"\n[guardrail: sensitive_field_read — "
                    f"blocked fields: {', '.join(redacted)}]"
                )
                return ToolMessage(
                    content=cleaned + note,
                    name=result.name,
                    tool_call_id=result.tool_call_id,
                )

        return result

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Terminate the run if any terminal access block is in the message history."""
        for msg in state.get("messages", []):
            if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                try:
                    payload = json.loads(msg.content)
                    if payload.get("reason") in TERMINAL_ACCESS_REASONS:
                        return {
                            "messages": [AIMessage(_blocked_response(
                                payload["reason"],
                                payload.get("message", "Access denied."),
                            ))],
                            "jump_to": "end",
                        }
                except (json.JSONDecodeError, AttributeError):
                    pass
        return None


# ---------------------------------------------------------------------------
# Layer 3 — Output guardrail
# ---------------------------------------------------------------------------

class OutputGuardrails(AgentMiddleware):
    """Block sensitive content in the final response."""

    @hook_config(can_jump_to=["end"])
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if not state["messages"]:
            return None
        last_msg = state["messages"][-1]
        if last_msg.type != "ai":
            return None
        output = last_msg.content.lower()

        # sensitive_content_output: even when a read was permitted, sensitive
        # phrases must not appear verbatim in user-visible output.
        if any(phrase in output for phrase in SENSITIVE_OUTPUT_PHRASES):
            return {
                "messages": [AIMessage(_blocked_response(
                    "sensitive_content_output",
                    "The response contained restricted content that cannot be shared. "
                    "Please rephrase your query to focus on market signals and listing strategy.",
                ))],
                "jump_to": "end",
            }

        # profanity_toxicity_output: second line of defense for harmful language.
        if any(marker in output for marker in PROFANITY_OUTPUT_MARKERS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "profanity_toxicity_output",
                    "The response contained inappropriate language and was blocked.",
                ))],
                "jump_to": "end",
            }

        # geography_leak: model may silently shift to training-data reasoning
        # without flagging the absence of Ciudaty data.
        if any(term in output for term in GEOGRAPHY_LEAK_TERMS):
            return {
                "messages": [AIMessage(_blocked_response(
                    "geography_leak",
                    "The response referenced non-Ciudaty markets. "
                    "RealThor only operates in Ciudaty.",
                ))],
                "jump_to": "end",
            }

        return None


# ---------------------------------------------------------------------------
# Convenience alias — pass this list to create_agent(middleware=...)
# ---------------------------------------------------------------------------

def make_guardrails() -> list[AgentMiddleware]:
    """Return the three guardrail layers in order."""
    return [InputGuardrails(), ToolGuardrails(), OutputGuardrails()]


# ---------------------------------------------------------------------------
# Layer 4 — HITL policy (conditional — only fires when policy requires it)
# ---------------------------------------------------------------------------

def _get_estimated_value(opp_id: str, opps_df: pd.DataFrame) -> float:
    row = opps_df[opps_df["supply_opportunity_id"] == opp_id]
    return float(row.iloc[0]["estimated_value"]) if not row.empty else 0.0


def make_hitl_policy(cfg: dict) -> HumanInTheLoopMiddleware:
    """Return HITL middleware that gates high-value iBuyer channel recommendations.

    Unlike guardrails (which always block), this middleware is conditional:
    the `when` predicate calls `evaluate_channel_policy()` and only fires
    `interrupt()` when the policy returns `requires_approval=True`.
    """
    opps = pd.read_csv(cfg["paths"]["supply_opportunities_data"])
    threshold = cfg["hitl"]["ibuyer_threshold"]

    def _needs_approval(req: ToolCallRequest) -> bool:
        channel = req.tool_call["args"].get("channel", "")
        opp_id = req.tool_call["args"].get("opportunity_id", "")
        estimated_value = _get_estimated_value(opp_id, opps)
        decision = evaluate_channel_policy(
            channel=channel,
            estimated_value=estimated_value,
            role=getattr(req.runtime.context, "role", "analyst"),
            threshold=threshold,
        )
        return decision.requires_approval

    return HumanInTheLoopMiddleware(
        interrupt_on={
            "submit_channel_recommendation": InterruptOnConfig(
                allowed_decisions=["approve", "reject"],
                when=_needs_approval,
            ),
        }
    )
