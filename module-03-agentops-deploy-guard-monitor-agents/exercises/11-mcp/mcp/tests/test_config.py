from pathlib import Path

from company_mcp.config import load_config, resolve_paths

ROOT = Path(__file__).resolve().parents[1]
CONFIG = str(ROOT / "config.yaml")


def test_load_config_has_mcp_and_paths():
    cfg = load_config(CONFIG)
    assert cfg["mcp"]["transport"] in ("http", "stdio")
    assert cfg["mcp"]["port"] == 8000
    assert "demand_data" in cfg["paths"]


def test_resolve_paths_are_absolute():
    cfg = resolve_paths(load_config(CONFIG), CONFIG)
    for value in cfg["paths"].values():
        assert Path(value).is_absolute()
        assert Path(value).exists()
