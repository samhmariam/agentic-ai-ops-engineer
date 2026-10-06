"""Tests for src.cost.dashboard."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cost.dashboard import render_html, router


def test_render_html_includes_aggregate_and_per_model():
    summary = {
        "total_requests": 5,
        "total_cost_usd": 0.1234,
        "by_model": {
            "gpt-4o": {"requests": 2, "cost_usd": 0.10, "avg_cost_usd": 0.05},
            "gpt-4o-mini": {"requests": 3, "cost_usd": 0.0234, "avg_cost_usd": 0.0078},
        },
    }

    html = render_html(summary)

    assert "<title>Cost Dashboard</title>" in html
    assert "Total requests" in html and ">5<" in html
    assert "$0.1234" in html
    assert "gpt-4o" in html and "gpt-4o-mini" in html


def test_render_html_handles_empty_log():
    html = render_html({"total_requests": 0, "total_cost_usd": 0.0, "by_model": {}})
    assert "No requests logged yet." in html


def test_router_endpoint_returns_html():
    app = FastAPI()
    app.include_router(router)

    fake_records = [
        {"model": "gpt-4o", "cost_usd": 0.05, "prompt_tokens": 1, "completion_tokens": 1},
    ]
    with patch("src.cost.dashboard.load_log", return_value=fake_records):
        client = TestClient(app)
        response = client.get("/cost-dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Cost Dashboard</title>" in response.text
    assert "gpt-4o" in response.text
    assert "$0.0500" in response.text
