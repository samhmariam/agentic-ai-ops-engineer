import pathlib

import pandas as pd
import pytest
from realthor.config import load_config, resolve_paths
from realthor.tools import make_tools

CONFIG_PATH = str(pathlib.Path(__file__).parent.parent / "config.yaml")


def _load_data():
    cfg = resolve_paths(load_config(CONFIG_PATH), CONFIG_PATH)
    demand = pd.read_csv(cfg["paths"]["demand_data"])
    supply = pd.read_csv(cfg["paths"]["supply_data"])
    neighborhoods = pd.read_csv(cfg["paths"]["neighborhood_data"])
    velocity = pd.read_csv(cfg["paths"]["velocity_data"])
    supply_opps = pd.read_csv(cfg["paths"]["supply_opportunities_data"])
    listings = pd.read_csv(cfg["paths"]["listings_data"])
    sales = pd.read_csv(cfg["paths"]["sales_data"])
    return demand, supply, neighborhoods, velocity, supply_opps, listings, sales


def test_make_tools_returns_fourteen_tools():
    tools = make_tools(*_load_data())
    assert len(tools) == 14


def test_get_demand_signals_valid():
    tools = make_tools(*_load_data())
    get_demand = tools[0]
    result = get_demand.invoke({"region": "west", "property_type": "apartment", "bedrooms": 2})
    assert "0.91" in result


def test_get_supply_snapshot_valid():
    tools = make_tools(*_load_data())
    get_supply = tools[1]
    result = get_supply.invoke({"region": "west", "property_type": "apartment", "bedrooms": 2})
    assert "0.22" in result


def test_get_demand_signals_invalid_segment():
    tools = make_tools(*_load_data())
    result = tools[0].invoke({"region": "west", "property_type": "apartment", "bedrooms": 99})
    assert "No demand data available" in result


def test_get_supply_snapshot_invalid_segment():
    tools = make_tools(*_load_data())
    result = tools[1].invoke({"region": "west", "property_type": "apartment", "bedrooms": 99})
    assert "No supply data available" in result


def test_get_neighborhood_profile_valid():
    tools = make_tools(*_load_data())
    get_nbhd = tools[2]
    result = get_nbhd.invoke({"neighborhood": "Westgate"})
    assert "Westgate" in result
    assert "avg_price_index" in result


def test_get_neighborhood_profile_invalid():
    tools = make_tools(*_load_data())
    result = tools[2].invoke({"neighborhood": "DoesNotExist"})
    assert "No profile found" in result


def test_get_listing_velocity_valid():
    tools = make_tools(*_load_data())
    get_vel = tools[3]
    result = get_vel.invoke({"region": "west", "property_type": "apartment", "bedrooms": 2})
    assert "velocity_score" in result


def test_get_listing_velocity_invalid():
    tools = make_tools(*_load_data())
    result = tools[3].invoke({"region": "west", "property_type": "apartment", "bedrooms": 99})
    assert "No velocity data available" in result
