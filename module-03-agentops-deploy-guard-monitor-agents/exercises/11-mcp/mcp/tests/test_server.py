"""Offline tests for the MCP data service.

Uses FastMCP's in-memory client (``Client(server)``) — no network, no ports,
no API key. Confirms the server publishes exactly the expected tools and that
each returns the same rows the underlying CSV holds.
"""

import asyncio
from pathlib import Path

import pandas as pd
import pytest
from fastmcp import Client

from company_mcp.config import load_config, resolve_paths
from company_mcp.server import build_server

ROOT = Path(__file__).resolve().parents[1]
CONFIG = str(ROOT / "config.yaml")

EXPECTED_TOOLS = ["get_demand_signals", "get_listing_velocity", "get_supply_snapshot"]


def _cfg():
    return resolve_paths(load_config(CONFIG), CONFIG)


def _server():
    return build_server(_cfg())


def _text(result):
    """FastMCP call_tool result → the tool's string return."""
    data = getattr(result, "data", None)
    if isinstance(data, str):
        return data
    return result.content[0].text


async def _list_tool_names():
    async with Client(_server()) as client:
        return sorted(t.name for t in await client.list_tools())


async def _call(name, args):
    async with Client(_server()) as client:
        return _text(await client.call_tool(name, args))


def test_registers_expected_tools():
    assert asyncio.run(_list_tool_names()) == EXPECTED_TOOLS


def test_demand_signals_returns_row():
    cfg = _cfg()
    demand = pd.read_csv(cfg["paths"]["demand_data"])
    seg = {"region": "west", "property_type": "apartment", "bedrooms": 2}
    expected = demand[
        (demand["region"] == "west")
        & (demand["property_type"] == "apartment")
        & (demand["bedrooms"] == 2)
    ].to_string(index=False)
    assert asyncio.run(_call("get_demand_signals", seg)) == expected


def test_supply_snapshot_returns_row():
    cfg = _cfg()
    supply = pd.read_csv(cfg["paths"]["supply_data"])
    seg = {"region": "west", "property_type": "apartment", "bedrooms": 2}
    expected = supply[
        (supply["region"] == "west")
        & (supply["property_type"] == "apartment")
        & (supply["bedrooms"] == 2)
    ].to_string(index=False)
    assert asyncio.run(_call("get_supply_snapshot", seg)) == expected


def test_velocity_returns_row():
    cfg = _cfg()
    velocity = pd.read_csv(cfg["paths"]["velocity_data"])
    seg = {"region": "west", "property_type": "apartment", "bedrooms": 2}
    expected = velocity[
        (velocity["region"] == "west")
        & (velocity["property_type"] == "apartment")
        & (velocity["bedrooms"] == 2)
    ].to_string(index=False)
    assert asyncio.run(_call("get_listing_velocity", seg)) == expected


def test_unknown_segment_returns_no_data_message():
    seg = {"region": "west", "property_type": "apartment", "bedrooms": 99}
    assert asyncio.run(_call("get_demand_signals", seg)) == "No demand data available for this segment."


def test_tool_call_via_in_memory_client():
    seg = {"region": "west", "property_type": "apartment", "bedrooms": 2}
    text = asyncio.run(_call("get_demand_signals", seg))
    assert "west" in text and "apartment" in text
