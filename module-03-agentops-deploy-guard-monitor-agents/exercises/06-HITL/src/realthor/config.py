import os
import pathlib

import pandas as pd
import yaml


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_prompt(path: str) -> str:
    with open(path) as f:
        return f.read()


def resolve_paths(cfg: dict, config_path: str) -> dict:
    """Resolve data/prompt paths relative to the config file, not CWD."""
    base = pathlib.Path(config_path).resolve().parent
    cfg["paths"] = {k: str(base / v) for k, v in cfg["paths"].items()}
    return cfg


VOCAREUM_BASE_URL = "https://openai.vocareum.com/v1"


def make_chat_model(cfg: dict):
    """Build the chat model, choosing the provider from the LLM_PROVIDER env var.

    LLM_PROVIDER=openai   -> OpenAI directly (OPENAI_API_KEY). Default.
    LLM_PROVIDER=vocareum -> Vocareum's OpenAI-compatible proxy
                             (VOCAREUM_API_KEY + VOCAREUM_BASE_URL).
    """
    from langchain_openai import ChatOpenAI

    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    kwargs = {"model": cfg["model"]["name"], "temperature": cfg["model"]["temperature"]}
    if provider == "vocareum":
        kwargs["base_url"] = VOCAREUM_BASE_URL
        try:
            kwargs["api_key"] = os.environ["VOCAREUM_API_KEY"]
        except KeyError:
            raise RuntimeError(
                "LLM_PROVIDER=vocareum but VOCAREUM_API_KEY is not set. "
                "Copy .env.example to .env and paste your Vocareum key."
            )
    return ChatOpenAI(**kwargs)
