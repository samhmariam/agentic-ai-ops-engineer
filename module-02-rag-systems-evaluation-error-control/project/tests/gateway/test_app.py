"""Tests for src.gateway.app (FastAPI app factory + lifespan)."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.gateway.app import create_app


def test_app_mounts_health_query_and_cost_dashboard():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/health" in paths
    assert "/query" in paths
    assert "/cost-dashboard" in paths
    assert "/query/stream" in paths  # mounted from src.optimization.routes


def test_app_has_expected_title():
    app = create_app()
    assert app.title == "LLM FAQ Service"


def test_lifespan_flushes_tracing_on_shutdown():
    with patch("src.gateway.app.flush") as flush:
        with TestClient(create_app()):
            pass  # entering and exiting the context manager triggers lifespan

    flush.assert_called_once()


def test_cost_dashboard_endpoint_serves_html():
    with patch("src.cost.dashboard.load_log", return_value=[]):
        client = TestClient(create_app())
        r = client.get("/cost-dashboard")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Cost Dashboard" in r.text
