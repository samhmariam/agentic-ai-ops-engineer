"""Human-in-the-loop approval gate for high-risk actions.

Called by the tool guardrail for every tool the data access policy marks
`requires_approval` (today: send_email). Because it runs inside the wrapper every
tool call passes through, the agent cannot reach the action without it.

For each proposed action the gate:
  1. records an approval request (log `approval_requested`, trace span, audit file),
  2. asks the run's approver for a decision: approved | rejected | pending,
  3. records the decision (log `approval_decision`, trace span, audit file).
Only `approved` lets the action execute. `rejected` and `pending` return an
explicit result to the agent instead; nothing is sent.

Approvers are simulated from the CLI (`--approval approve|reject|pending|prompt`);
`prompt` asks the operator interactively in the terminal.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional, Tuple

from salesops_agent.logging_utils import log_event

Decision = Literal["approved", "rejected", "pending"]
APPROVAL_MODES = ("approve", "reject", "pending", "prompt")
# approver(request) -> (decision, decided_by)
Approver = Callable[[Dict[str, Any]], Tuple[Decision, str]]

_AUDIT_LOCK = threading.Lock()


@dataclass
class ApprovalRecord:
    approval_id: str
    run_id: Optional[str]
    tool: str
    decision: Decision
    decided_by: str
    requested_at: str
    decided_at: str
    preapproved: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def action_summary(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """What logs and traces may show about an action: no recipient address or body."""
    summary: Dict[str, Any] = {"tool": tool, "arg_names": sorted(args)}
    to = args.get("to")
    if isinstance(to, str) and "@" in to:
        summary["recipient_domain"] = to.rsplit("@", 1)[1]
    return summary


def make_approver(mode: str, prompt_fn: Optional[Callable[[Dict[str, Any]], bool]] = None) -> Approver:
    """Simulated reviewer for a run. `prompt` needs prompt_fn (e.g. a terminal confirm)."""
    if mode not in APPROVAL_MODES:
        raise ValueError(f"approval mode must be one of {APPROVAL_MODES}, got {mode!r}")
    if mode == "approve":
        return lambda request: ("approved", "simulated reviewer (--approval approve)")
    if mode == "reject":
        return lambda request: ("rejected", "simulated reviewer (--approval reject)")
    if mode == "pending":
        return lambda request: ("pending", "no reviewer decision (default --approval pending)")
    if prompt_fn is None:
        raise ValueError("approval mode 'prompt' requires an interactive prompt function")
    return lambda request: (("approved" if prompt_fn(request) else "rejected"), "interactive reviewer (--approval prompt)")


def resolve_approval(ctx: Any, tool: str, args: Dict[str, Any], approval_id: str) -> Decision:
    """Run the approval gate for one proposed action and return the decision.

    `ctx` is the tool guardrail's RunContext (approvals, approver, approvals_log,
    logger, on_approval, approval_records). The caller holds ctx.lock.
    """
    requested_at = _now()
    summary = action_summary(tool, args)
    request = {"approval_id": approval_id, "run_id": ctx.run_id, "action": {"tool": tool, "args": args}}

    if ctx.logger:
        log_event(ctx.logger, "approval_requested", run_id=ctx.run_id, approval_id=approval_id, **summary)

    if approval_id in ctx.approvals:          # approved earlier, for exactly this action
        decision, decided_by, preapproved = "approved", "pre-approved action id", True
    else:
        approver: Approver = ctx.approver or make_approver("pending")
        decision, decided_by = approver(request)
        preapproved = False

    record = ApprovalRecord(approval_id, ctx.run_id, tool, decision, decided_by, requested_at, _now(), preapproved)
    ctx.approval_records.append(record)
    if ctx.logger:
        log_event(ctx.logger, "approval_decision",
                  level=logging.INFO if decision == "approved" else logging.WARNING,
                  run_id=ctx.run_id, approval_id=approval_id, tool=tool, decision=decision, decided_by=decided_by)
    if ctx.on_approval:
        ctx.on_approval(asdict(record))
    if ctx.approvals_log:                     # audit trail with the full action, for reviewers
        path = Path(ctx.approvals_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOCK, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**asdict(record), "action": {"tool": tool, "args": args}}) + "\n")
    return decision
