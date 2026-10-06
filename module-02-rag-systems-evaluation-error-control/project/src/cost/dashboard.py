"""FastAPI router exposing GET /cost-dashboard as a simple HTML report.

Every value interpolated into the HTML is run through ``html.escape`` even
though the cost log is currently operator-controlled. The escape calls
are defense in depth: if a future version filters by query type or model
name from a request parameter, the existing template stays safe.
"""

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from src.cost.tracker import load_log, summarize

router = APIRouter()


def _row(label: str, value: str) -> str:
    """Render one ``<tr>`` for the totals table, escaping both columns."""
    return f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"


def render_html(summary: dict) -> str:
    """Render the summary dict as a small standalone HTML page."""
    by_model_rows = "".join(
        f"<tr>"
        f"<td>{html.escape(model)}</td>"
        f"<td>{stats['requests']}</td>"
        f"<td>${stats['cost_usd']:.4f}</td>"
        f"<td>${stats['avg_cost_usd']:.6f}</td>"
        f"</tr>"
        for model, stats in sorted(summary["by_model"].items())
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Cost Dashboard</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; margin-top: 1rem; }}
    th, td {{ padding: 0.4rem 0.8rem; border: 1px solid #ddd; text-align: left; }}
    th {{ background: #f5f5f5; }}
    h1 {{ margin-bottom: 0; }}
  </style>
</head>
<body>
  <h1>Cost Dashboard</h1>
  <p>Aggregate cost data from the local JSONL request log.</p>
  <table>
    {_row("Total requests", str(summary["total_requests"]))}
    {_row("Total cost (USD)", f"${summary['total_cost_usd']:.4f}")}
  </table>
  <h2>Per-model breakdown</h2>
  <table>
    <thead>
      <tr><th>Model</th><th>Requests</th><th>Cost (USD)</th><th>Avg cost / request</th></tr>
    </thead>
    <tbody>
      {by_model_rows or '<tr><td colspan="4">No requests logged yet.</td></tr>'}
    </tbody>
  </table>
</body>
</html>
"""


@router.get("/cost-dashboard", response_class=HTMLResponse)
async def cost_dashboard() -> str:
    """Serve a small HTML report of total + per-model cost.

    Reads the JSONL log at ``settings.cost_log_path`` on every request.
    No caching, no pagination — the log is operator-scale (one append
    per HTTP query). For the kind of historical trending you'd build in
    a production deployment, either query the log directly or replace
    this endpoint with a Grafana/Prometheus integration.
    """
    return render_html(summarize(load_log()))
