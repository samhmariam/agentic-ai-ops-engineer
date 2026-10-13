"""Command-line entry point.

Installed as `salesops-agent` (and the short alias `salesops`); also runnable as
`python -m salesops_agent`. Commands: ask | eval | compare | experiments | report | versions.
"""

from __future__ import annotations

import json
import os

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


@app.command()
@click.argument("question")
@config_option
@click.option("--json", "as_json", is_flag=True, help="Print the full run result as JSON.")
def ask(question, config_path, as_json):
    """Ask the agent a single QUESTION and print its final answer.

    Loads the config and its versioned prompt, initializes the pinned tools, invokes
    the agent, and writes a structured log entry (logs/) and a trace file (traces/).
    The answer goes to stdout; run details go to stderr.
    """
    from salesops_agent.runner import run_question

    if not question.strip():
        raise click.UsageError("QUESTION must not be empty.")
    cfg = _load(config_path)
    _require_api_key()
    try:
        result = run_question(cfg, question.strip(), source="cli")
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
        click.echo(
            f"\n[run {result.run_id} | {cfg['experiment']['name']} | {result.latency_s:.1f}s | "
            f"{result.input_tokens}+{result.output_tokens} tokens | "
            f"tools: {', '.join(result.tools_called) or 'none'}]\n"
            f"[log: {log_path}]\n[trace: {result.trace_path}]",
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


@app.command("eval")
@click.option("--case", "case_ids", multiple=True, help="Run only these case IDs (repeatable).")
@click.option(
    "--config", "config_paths", multiple=True,
    help="Config(s) to evaluate, e.g. configs/prompt-v2.yaml (repeatable; default: config.yaml).",
)
def eval_cmd(case_ids, config_paths):
    """Run the evaluation suite for one or more experiment configs.

    Writes reports/eval_<experiment>_<ts>.json per config.
    """
    from salesops_agent.evaluation import run_evaluation

    def show(result):
        mark = "PASS" if result.passed else "FAIL"
        click.echo(f"{mark}  {result.case_id}  [{result.category}]  {'; '.join(result.failures)}")

    _require_api_key()
    for config_path in config_paths or (None,):
        cfg = _load(config_path)
        click.echo(f"\n== {cfg['experiment']['name']}: {cfg['experiment']['description']}")
        out = run_evaluation(cfg, list(case_ids) or None, on_result=show)
        click.echo(f"Results written to {out}")


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


if __name__ == "__main__":
    app()
