"""Unit tests for realthor.tools."""

import pathlib
import pandas as pd
from realthor.config import load_config, resolve_paths
from realthor.tools import make_tools


CONFIG_PATH = str(pathlib.Path(__file__).parent.parent / "config.yaml")


def _load_data():
    cfg = resolve_paths(load_config(CONFIG_PATH), CONFIG_PATH)
    demand = pd.read_csv(cfg["paths"]["demand_data"])
    supply = pd.read_csv(cfg["paths"]["supply_data"])
    return demand, supply


def test_make_tools_returns_two_tools():
    demand, supply = _load_data()
    tools = make_tools(demand, supply)
    assert len(tools) == 2


def test_get_demand_signals_valid():
    demand, supply = _load_data()
    tools = make_tools(demand, supply)
    get_demand = tools[0]
    result = get_demand.invoke({"region": "west", "property_type": "apartment", "bedrooms": 2})
    assert "0.91" in result  # known demand_score for this segment


def test_get_supply_snapshot_valid():
    demand, supply = _load_data()
    tools = make_tools(demand, supply)
    get_supply = tools[1]
    result = get_supply.invoke({"region": "west", "property_type": "apartment", "bedrooms": 2})
    assert "0.22" in result  # known supply_score for this segment


def test_get_demand_signals_invalid():
    demand, supply = _load_data()
    tools = make_tools(demand, supply)
    get_demand = tools[0]
    result = get_demand.invoke({"region": "west", "property_type": "apartment", "bedrooms": 99})
    assert "No demand data available" in result


def test_get_supply_snapshot_invalid():
    demand, supply = _load_data()
    tools = make_tools(demand, supply)
    get_supply = tools[1]
    result = get_supply.invoke({"region": "west", "property_type": "apartment", "bedrooms": 99})
    assert "No supply data available" in result
