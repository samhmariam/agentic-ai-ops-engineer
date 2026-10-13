import pathlib

import yaml


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def resolve_paths(cfg: dict, config_path: str) -> dict:
    """Resolve data paths relative to the config file, not CWD."""
    base = pathlib.Path(config_path).resolve().parent
    cfg["paths"] = {k: str(base / v) for k, v in cfg["paths"].items()}
    return cfg
