"""Command-line entry point: `salesops ask | eval | report | versions`."""

from __future__ import annotations

import click
from dotenv import load_dotenv

from salesops_agent.config import PROJECT_ROOT, load_config

config_option = click.option(
    "--config", "config_path", default=None, help="Path to config.yaml (default: project root)."
)


@click.group()
def app():
    """SalesOps Agent for UdaCenture."""
    load_dotenv(PROJECT_ROOT / ".env")


@app.command()
@click.argument("question")
@config_option
def ask(question, config_path):
    """Ask the agent a single QUESTION."""
    from salesops_agent.runner import run_question

    cfg = load_config(config_path)
    result = run_question(cfg, question, source="cli")
    if not result.success:
        raise click.ClickException(f"Run {result.run_id} failed: {result.error}")
    click.echo(result.answer)
    click.echo(
        f"\n[run {result.run_id} | {result.latency_s:.1f}s | "
        f"{result.input_tokens}+{result.output_tokens} tokens | "
        f"tools: {', '.join(result.tools_called) or 'none'} | trace: {result.trace_path}]",
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

    manifest = describe_versions(load_config(config_path))
    click.echo(json.dumps(manifest, indent=2) if as_json else "\n".join(short_manifest(manifest)))


@app.command("eval")
@click.option("--case", "case_ids", multiple=True, help="Run only these case IDs (repeatable).")
@config_option
def eval_cmd(case_ids, config_path):
    """Run the evaluation suite and write reports/eval_<ts>.json."""
    from salesops_agent.evaluation import run_evaluation

    def show(result):
        mark = "PASS" if result.passed else "FAIL"
        click.echo(f"{mark}  {result.case_id}  [{result.category}]  {'; '.join(result.failures)}")

    out = run_evaluation(load_config(config_path), list(case_ids) or None, on_result=show)
    click.echo(f"\nResults written to {out}")


@app.command()
@config_option
def report(config_path):
    """Build a Markdown report from logs and the latest evaluation."""
    from salesops_agent.reporting import build_report

    out = build_report(load_config(config_path))
    click.echo(f"Report written to {out}")


if __name__ == "__main__":
    app()
