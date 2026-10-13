"""A tiny FastMCP server used only by test_mcp.py.

Launched over stdio by the test (a subprocess), so `load_mcp_tools` is exercised
against a real MCP transport with no network, no ports, and no API key.
"""

from fastmcp import FastMCP

mcp = FastMCP("stub")


@mcp.tool
def echo_demand(region: str) -> str:
    """Return a canned demand value for a region."""
    return f"demand for {region} is 0.42"


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
