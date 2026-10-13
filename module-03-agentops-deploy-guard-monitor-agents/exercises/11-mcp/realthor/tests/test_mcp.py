"""Tests for the student deliverable: connecting RealThor to the MCP server.

Offline — `load_mcp_tools` is pointed at a tiny FastMCP stub launched over stdio
(a subprocess), so no network, no running HTTP server, and no API key are
needed. These fail in the starter until `load_mcp_tools` is implemented.
"""

import asyncio
import sys
from pathlib import Path

from langchain_core.tools import BaseTool

from realthor.mcp_client import load_mcp_tools

STUB = str(Path(__file__).parent / "fixtures" / "stub_mcp_server.py")


def _stdio_cfg():
    # Launch the stub server as a subprocess over stdio (uses this venv's python).
    return {"mcp": {"transport": "stdio", "command": sys.executable, "args": [STUB]}}


def test_client_maps_mcp_tools_to_langchain_tools():
    tools = asyncio.run(load_mcp_tools(_stdio_cfg()))
    assert len(tools) == 1
    assert all(isinstance(t, BaseTool) for t in tools)


def test_client_tool_names_match_server():
    tools = asyncio.run(load_mcp_tools(_stdio_cfg()))
    assert {t.name for t in tools} == {"echo_demand"}


def test_mapped_tool_invokes_over_mcp():
    tools = asyncio.run(load_mcp_tools(_stdio_cfg()))
    tool = {t.name: t for t in tools}["echo_demand"]
    result = asyncio.run(tool.ainvoke({"region": "west"}))
    text = result if isinstance(result, str) else str(result)
    assert "west" in text and "0.42" in text
