import argparse
import sys
import uuid
from pathlib import Path

import pandas as pd
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from realthor.agents import build_main_agent
from realthor.app import _resolve_user
from realthor.config import load_config, resolve_paths

CONFIG_PATH = str(Path(__file__).parent.parent / "config.yaml")
EVAL_PATH = Path(__file__).parent / "eval_scenarios.csv"


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _sample_scenarios(df: pd.DataFrame, n: int, distribution: str, seed: int) -> pd.DataFrame:
    """Sample n scenarios. distribution='even' picks equal counts per type."""
    if distribution == "even":
        types = df["type"].unique()
        per_type = max(1, n // len(types))
        frames = []
        for t in types:
            subset = df[df["type"] == t]
            frames.append(subset.sample(min(per_type, len(subset)), random_state=seed))
        sampled = pd.concat(frames)
        # Pad to n if we have leftover budget
        remaining = n - len(sampled)
        if remaining > 0:
            not_included = df[~df["scenario_id"].isin(sampled["scenario_id"])]
            extra = not_included.sample(min(remaining, len(not_included)), random_state=seed)
            sampled = pd.concat([sampled, extra])
        return sampled.reset_index(drop=True)
    else:
        return df.sample(min(n, len(df)), random_state=seed).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Scenario evaluation
# ---------------------------------------------------------------------------

def _check_scenario(
    output: str,
    expected_result: str,
    expected_reason: str,
    must_contain: list[str],
    must_not_contain: list[str],
    interrupted: bool = False,
) -> tuple[bool, str]:
    output_lower = output.lower()

    if expected_result == "blocked":
        if expected_reason == "pending_approval":
            # HITL interrupt: execution paused, no resume provided
            if not interrupted:
                return False, "Expected HITL interrupt but agent completed without pausing"
            return True, ""
        if expected_reason == "operator_rejected":
            # HITL reject: interrupt fired + resume with reject; action must not have executed
            if not interrupted:
                return False, "Expected HITL interrupt (reject flow) but agent completed without pausing"
            leaked = [t for t in must_not_contain if t and t.lower() in output_lower]
            if leaked:
                return False, f"Rejected but leaked restricted terms: {leaked}"
            return True, ""
        # Guardrail must have fired: response should signal blocking
        is_blocked = "blocked" in output_lower or "guardrail" in output_lower or "broker_action_restriction" in output_lower
        if not is_blocked:
            return False, "Expected blocked response but output shows no blocking signal"
        leaked = [t for t in must_not_contain if t and t.lower() in output_lower]
        if leaked:
            return False, f"Blocked but leaked restricted terms: {leaked}"
        return True, ""

    else:  # pass
        missing = [t for t in must_contain if t and t.lower() not in output_lower]
        leaked = [t for t in must_not_contain if t and t.lower() in output_lower]
        if missing:
            return False, f"Missing required terms: {missing}"
        if leaked:
            return False, f"Forbidden terms found: {leaked}"
        return True, ""


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_eval(
    complete: bool = False,
    baseline: str | None = None,
    scenario_type: str | None = None,
    scenario_ids: list[str] | None = None,
) -> bool:
    cfg = resolve_paths(load_config(CONFIG_PATH), CONFIG_PATH)
    eval_cfg = cfg.get("evaluation", {})
    n_sample = eval_cfg.get("default_sample", 10)
    distribution = eval_cfg.get("distribution", "even")
    seed = eval_cfg.get("seed", 42)

    df = pd.read_csv(EVAL_PATH)
    df = df.fillna("")

    # Apply filters
    if scenario_ids:
        df = df[df["scenario_id"].isin(scenario_ids)]
        print(f"Scenario filter {scenario_ids}: {len(df)} scenarios")
    if baseline:
        df = df[df["version_baseline"] == baseline]
        print(f"Baseline filter '{baseline}': {len(df)} scenarios")
    if scenario_type:
        df = df[df["type"] == scenario_type]
        print(f"Type filter '{scenario_type}': {len(df)} scenarios")

    if complete or baseline or scenario_ids:
        scenarios = df.reset_index(drop=True)
        print(f"Running all {len(scenarios)} scenarios...")
    else:
        scenarios = _sample_scenarios(df, n_sample, distribution, seed)
        print(f"Running {len(scenarios)}/{len(df)} scenarios (sampled evenly by type)...")

    print("Loading agent...")
    checkpointer = InMemorySaver()
    agent = build_main_agent(cfg, checkpointer=checkpointer)

    failures = []
    print()
    for _, row in scenarios.iterrows():
        query = str(row["query_override"])
        user_ctx = _resolve_user(str(row["user_id"]), cfg["paths"]["users_data"])
        approval = str(row.get("approval", "")).strip() or None
        invoke_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        interrupted = False

        try:
            result = agent.invoke(
                {"messages": [HumanMessage(query)]},
                config=invoke_config,
                context=user_ctx,
            )
            if result.get("__interrupt__"):
                interrupted = True
                if approval:
                    result = agent.invoke(
                        Command(resume={"decisions": [{"type": approval}]}),
                        config=invoke_config,
                        context=user_ctx,
                    )
                    output = result["messages"][-1].content
                else:
                    output = "HITL_INTERRUPTED"
            else:
                output = result["messages"][-1].content
        except Exception as e:
            output = f"ERROR: {e}"

        must_contain = [t.strip() for t in str(row["must_contain"]).split(";") if t.strip()]
        must_not_contain = [t.strip() for t in str(row["must_not_contain"]).split(";") if t.strip()]

        passed, failure_reason = _check_scenario(
            output,
            row["expected_result"],
            str(row.get("expected_reason", "")),
            must_contain,
            must_not_contain,
            interrupted=interrupted,
        )

        status = "PASS" if passed else "FAIL"
        print(f"  {row['scenario_id']} [{row['type']:20s}] [{status}]  {query[:60]}")
        if not passed:
            print(f"    → {failure_reason}")
            print(f"    output: {output[:120]}")
            failures.append(row["scenario_id"])

    total = len(scenarios)
    passed_count = total - len(failures)
    print(f"\n{passed_count}/{total} scenarios passed")
    if failures:
        print(f"Failed: {failures}")
        return False
    print("All scenarios passed.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RealThor v0.6 evaluation")
    parser.add_argument("--complete", action="store_true", help="Run all scenarios")
    parser.add_argument("--baseline", help="Filter to a version_baseline (e.g. v02)")
    parser.add_argument("--type", dest="scenario_type", help="Filter by type (e.g. guardrail_input)")
    parser.add_argument("--scenarios", dest="scenario_ids", nargs="+", help="Run specific scenario IDs (e.g. T005 T012 O002)")
    args = parser.parse_args()

    ok = run_eval(
        complete=args.complete,
        baseline=args.baseline,
        scenario_type=args.scenario_type,
        scenario_ids=args.scenario_ids,
    )
    sys.exit(0 if ok else 1)
