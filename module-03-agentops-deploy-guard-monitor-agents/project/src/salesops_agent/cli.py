"""Command-line entry point.

Installed as `salesops-agent` (and the short alias `salesops`); also runnable as
`python -m salesops_agent`. Commands: ask | eval | compare | experiments | report | versions.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import click
from dotenv import load_dotenv

from salesops_agent.config import PROJECT_ROOT, ConfigError, load_config

config_option = click.option(
    "--config", "config_path", default=None,
    help="Config file (default: config.yaml; experiments live in configs/).",
)


@click.group()
@click.version_option(package_name="agentops-deploy-guard", prog_name="salesops-agent")
def app():
    """SalesOps Agent for UdaCenture."""
    load_dotenv(PROJECT_ROOT / ".env")


def _load(config_path):
    try:
        return load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc))


def _require_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        raise click.ClickException(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key "
            "(plus OPENAI_BASE_URL if you use a proxy)."
        )



def _confirm_action(request) -> bool:
    """Interactive reviewer for --approval prompt: show the exact action, ask y/n."""
    action = request["action"]
    click.echo("\n=== Approval required ===", err=True)
    click.echo(f"Action: {action['tool']} (approval id {request['approval_id']})", err=True)
    for key, value in action["args"].items():
        click.echo(f"{key}: {value}", err=True)
    return click.confirm("Approve this action?", default=False, err=True)

@app.command()
@click.argument("question")
@config_option
@click.option("--json", "as_json", is_flag=True, help="Print the full run result as JSON.")
@click.option("--role", default=None,
              help="Run as this role for the tool/action guardrail (default: policy default_role).")
@click.option("--approval", type=click.Choice(["approve", "reject", "pending", "prompt"]), default="pending",
              show_default=True,
              help="Human-in-the-loop decision for high-risk actions (send_email): simulate a reviewer "
                   "approving or rejecting, leave it pending, or prompt interactively.")
def ask(question, config_path, as_json, role, approval):
    """Ask the agent a single QUESTION and print its final answer.

    Loads the config and its versioned prompt, initializes the pinned tools, invokes
    the agent, and writes a structured log entry (logs/) and a trace file (traces/).
    High-risk actions such as sending an email go through the approval gate and
    only run when approved (--approval). The answer goes to stdout; run details go
    to stderr.
    """
    from salesops_agent.guardrails.approval import make_approver
    from salesops_agent.runner import run_question

    if not question.strip():
        raise click.UsageError("QUESTION must not be empty.")
    cfg = _load(config_path)
    _require_api_key()
    approver = make_approver(approval, prompt_fn=_confirm_action if approval == "prompt" else None)
    try:
        result = run_question(cfg, question.strip(), source="cli", role=role,
                              approval=approval, approver=approver)
    except Exception as exc:  # agent could not be built: prompt hash, tool pin, data schema...
        raise click.ClickException(f"Could not start the agent: {type(exc).__name__}: {exc}")

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    elif result.success:
        click.echo(result.answer)
    if not result.success:
        raise click.ClickException(f"Run {result.run_id} failed: {result.error} (trace: {result.trace_path})")
    if not as_json:
        log_path = cfg["paths"]["logs_dir"] / cfg["logging"]["file"]
        guard_line = ""
        if result.blocked:
            g = result.guardrail
            guard_line = f"[input guardrail: blocked by {g['rule_id']} ({g['category']}); agent not invoked]\n"
        for b in result.tools_blocked:
            if b["reason"] not in ("approval_required", "approval_rejected"):   # shown as approvals below
                guard_line += f"[tool guardrail: blocked {b['tool']} ({b['reason']}); not executed]\n"
        for a in result.approvals:
            outcome = {"approved": "executed", "rejected": "not executed",
                       "pending": "not executed, awaiting approval"}[a["decision"]]
            guard_line += (f"[approval: {a['tool']} requested (id {a['approval_id']}) -> {a['decision']} "
                           f"by {a['decided_by']}; {outcome}]\n")
        out = result.output_guardrail
        if out:
            detail = {"block": "response replaced by refusal",
                      "review": f"response withheld for human review (id {out['review_id']})",
                      "redact": f"{out['redactions']} sensitive value(s) redacted"}[out["action"]]
            guard_line += f"[output guardrail: {out['action']} by {', '.join(out['rule_ids'])}; {detail}]\n"
        click.echo(
            f"\n[run {result.run_id} | {cfg['experiment']['name']} | role {result.role or 'n/a'} | "
            f"{result.latency_s:.1f}s | "
            f"{result.input_tokens}+{result.output_tokens} tokens | "
            f"tools: {', '.join(result.tools_called) or 'none'}]\n"
            f"{guard_line}[run log: {cfg['paths']['logs_dir'] / cfg['logging']['runs_file']}]\n"
            f"[event log: {log_path}]\n[trace: {result.trace_path}]\n"
            f"[inspect: uv run salesops-agent inspect {result.run_id}]",
            err=True,
        )


@app.command()
@click.option("--json", "as_json", is_flag=True, help="Print the full manifest as JSON.")
@config_option
def versions(as_json, config_path):
    """Show the versions of prompt, config, schemas, tools and code in use."""
    import json

    from salesops_agent.agent import describe_versions
    from salesops_agent.versions import short_manifest

    manifest = describe_versions(_load(config_path))
    click.echo(json.dumps(manifest, indent=2) if as_json else "\n".join(short_manifest(manifest)))


def _eval_options(f):
    f = click.option(
        "--probes", is_flag=True,
        help="Run only the control probes (P-tasks): deterministic runtime-control evidence, no model calls.",
    )(f)
    f = click.option(
        "--workers", type=click.IntRange(1, 16), default=2, show_default=True,
        help="Tasks evaluated concurrently (1 = sequential). The course proxy throttles above ~2.",
    )(f)
    f = click.option(
        "--min-pass-rate", type=click.FloatRange(0, 1), default=0.0, show_default=True,
        help="Exit 1 if any evaluated config scores below this pass rate (CI gate).",
    )(f)
    f = click.option(
        "--config", "config_paths", multiple=True,
        help="Config(s) to evaluate, e.g. configs/candidate-v2.yaml (repeatable; default: config.yaml).",
    )(f)
    return click.option("--case", "case_ids", multiple=True, help="Run only these task IDs (repeatable).")(f)


def _run_evaluations(case_ids, config_paths, min_pass_rate, workers=2, probes=False):
    """Shared body of `salesops-agent eval` and the standalone `evaluate` command."""
    from salesops_agent.evaluation import run_evaluation

    def show(result):
        run = result.run
        mark = "PASS" if result.passed else "FAIL"
        line = f"{mark}  {result.case_id}  {result.task[:56]:<56}  {run['latency_s']:6.2f}s  ${run['cost_usd']:.5f}"
        click.echo(line + (f"  -> {'; '.join(result.failures)}" if result.failures else ""))

    _require_api_key()
    below = []
    for config_path in config_paths or (None,):
        cfg = _load(config_path)
        name = cfg["experiment"]["name"]
        click.echo(f"\n== {name}: {cfg['experiment']['description']}")
        click.echo(f"{'':4}  {'ID':<4}  {'Task':<56}  {'Latency':>7}  {'Est. cost'}")
        started = time.perf_counter()
        selected = list(case_ids)
        if probes:
            from salesops_agent.evaluation import load_cases
            selected += [c.id for c in load_cases(cfg["paths"]["eval_cases"]) if c.probe]
        out = run_evaluation(cfg, selected or None, on_result=show, workers=workers)
        wall = time.perf_counter() - started
        s, t = out.summary, out.summary["totals"]
        click.echo(
            f"\n{name}: {s['passed']}/{s['total']} passed ({s['pass_rate']:.0%}) | "
            f"total latency {t['latency_s_total']:.1f}s (avg {t['latency_s_avg']:.2f}s) | "
            f"est. cost ${t['cost_usd']:.4f} | wall time {wall:.1f}s ({workers} workers)"
        )
        click.echo(f"Report: {', '.join(str(p) for p in out.report_paths)}")
        click.echo(f"Result: {out.result_path}")
        if s["pass_rate"] < min_pass_rate:
            below.append(f"{name} {s['pass_rate']:.0%}")
    if below:
        raise click.ClickException(f"Pass rate below {min_pass_rate:.0%}: {', '.join(below)}")


@app.command("eval")
@_eval_options
def eval_cmd(case_ids, config_paths, min_pass_rate, workers, probes):
    """Run the evaluation suite for one or more experiment configs.

    Prints success/failure, latency, estimated cost and failure reason per task, and
    writes reports/evaluation_report.{md,csv,json} plus reports/eval_<experiment>_<ts>.json.
    """
    _run_evaluations(case_ids, config_paths, min_pass_rate, workers, probes)


@click.command()
@_eval_options
def evaluate(case_ids, config_paths, min_pass_rate, workers, probes):
    """Run the SalesOps evaluation suite (same as `salesops-agent eval`).

    Prints success/failure, latency, estimated cost and failure reason per task, and
    writes reports/evaluation_report.{md,csv,json} plus reports/eval_<experiment>_<ts>.json.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    _run_evaluations(case_ids, config_paths, min_pass_rate, workers, probes)


@app.command()
@click.argument("baseline")
@click.argument("candidate")
@click.option("--fail-on-regression", is_flag=True, help="Exit 1 if any case passing in BASELINE fails in CANDIDATE.")
@config_option
def compare(baseline, candidate, fail_on_regression, config_path):
    """Compare two eval results: BASELINE and CANDIDATE are experiment names
    (latest run of each) or eval result file paths."""
    from salesops_agent.comparison import write_comparison

    reports_dir = _load(config_path)["paths"]["reports_dir"]
    try:
        out, comp = write_comparison(baseline, candidate, reports_dir)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"{comp.baseline} -> {comp.candidate}: "
               f"{len(comp.fixes)} fixed {comp.fixes}, {len(comp.regressions)} regressed {comp.regressions}")
    if not comp.dataset_match:
        click.echo("Warning: runs used different eval datasets; deltas are not like-for-like.", err=True)
    click.echo(f"Comparison written to {out}")
    if fail_on_regression and comp.regressions:
        raise SystemExit(1)


@app.command()
def experiments():
    """List the baseline and experiment configs under configs/."""
    for path in [PROJECT_ROOT / "config.yaml", *sorted((PROJECT_ROOT / "configs").glob("*.yaml"))]:
        cfg = load_config(path)
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        click.echo(f"{cfg['experiment']['name']:<16} {rel:<28} {cfg['experiment']['description']}")


@app.command()
@config_option
def report(config_path):
    """Build a Markdown report from logs and the experiment's latest evaluation."""
    from salesops_agent.reporting import build_report

    out = build_report(_load(config_path))
    click.echo(f"Report written to {out}")


@app.command()
@click.option("--failed", is_flag=True, help="Only runs that errored or failed their evaluation task.")
@click.option("--intervened", is_flag=True, help="Only runs where a guardrail, sandbox or approval intervened.")
@click.option("--task", "task_id", default=None, help="Only runs of this evaluation task id (e.g. E024).")
@click.option("--limit", default=20, show_default=True, help="Most recent N matching runs.")
@config_option
def runs(failed, intervened, task_id, limit, config_path):
    """List recent runs from logs/runs.jsonl (one line per run)."""
    from salesops_agent.inspection import format_run_line, load_runs, select_runs

    cfg = _load(config_path)
    selected = select_runs(load_runs(cfg["paths"]["logs_dir"] / cfg["logging"]["runs_file"]),
                           failed=failed, intervened=intervened, task_id=task_id, limit=limit)
    if not selected:
        click.echo("No matching runs.")
    for run in selected:
        click.echo(format_run_line(run))


@app.command()
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Print the raw (redacted) trace JSON.")
@config_option
def inspect(run_id, as_json, config_path):
    """Show the trace of RUN_ID (prefix allowed): status, input, output, failure reason,
    and the step-by-step trajectory of model calls, tool calls, guardrails and approvals."""
    from salesops_agent.inspection import find_run, format_trace, load_runs

    cfg = _load(config_path)
    record = find_run(load_runs(cfg["paths"]["logs_dir"] / cfg["logging"]["runs_file"]), run_id)
    trace_path = Path(record["trace_path"]) if record and record.get("trace_path") else \
        cfg["paths"]["traces_dir"] / f"{run_id}.json"
    if not trace_path.exists():
        raise click.ClickException(f"No trace found for run {run_id!r} ({trace_path})")
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    click.echo(json.dumps(trace, indent=2) if as_json else format_trace(trace))
    click.echo(f"\n[trace: {trace_path}]", err=True)


if __name__ == "__main__":
    app()
