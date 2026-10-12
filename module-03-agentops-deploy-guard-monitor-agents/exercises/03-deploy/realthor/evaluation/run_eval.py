"""
Evaluation script for RealThor v0.3.

Runs the agent against eval_scenarios.csv and checks that each response
contains required terms and avoids forbidden terms.

Usage:
    uv run python evaluation/run_eval.py
"""

import sys
import pandas as pd
from pathlib import Path
from langchain_core.messages import HumanMessage
from realthor.agent import build_agent

CONFIG = str(Path(__file__).parent.parent / "config.yaml")


def run_eval():
    print("Loading agent...")
    agent = build_agent(CONFIG)
    df = pd.read_csv(Path(__file__).parent / "eval_scenarios.csv")
    failures = []

    print(f"Running {len(df)} scenarios...\n")
    for _, row in df.iterrows():
        question = (
            f"What's the listing priority for {int(row['bedrooms'])}-bedroom "
            f"{row['property_type']} in the {row['region']} region?"
        )
        result = agent.invoke({"messages": [HumanMessage(question)]})
        output = result["messages"][-1].content.lower()

        must_have = [t.strip() for t in row["must_mention"].split(";")]
        must_not = [t.strip() for t in row["must_not_mention"].split(";")]

        missing = [t for t in must_have if t not in output]
        forbidden = [t for t in must_not if t in output]
        passed = not missing and not forbidden

        status = "PASS" if passed else "FAIL"
        print(f"  {row['scenario_id']} [{status}]  {row['region']}/{row['property_type']}/{row['bedrooms']}br")
        if not passed:
            if missing:
                print(f"    missing: {missing}")
            if forbidden:
                print(f"    forbidden terms found: {forbidden}")
            failures.append(row["scenario_id"])

    total = len(df)
    passed_count = total - len(failures)
    print(f"\n{passed_count}/{total} scenarios passed")

    if failures:
        print(f"Failed: {failures}")
        sys.exit(1)
    else:
        print("All scenarios passed.")


if __name__ == "__main__":
    run_eval()
