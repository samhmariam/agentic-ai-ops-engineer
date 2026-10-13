"""RealThor's market-data service, exposed over MCP with FastMCP.

The read-only lookups — demand, supply, listing velocity — used to live inside
RealThor's own process. Here they are published as MCP tools any compatible
client can discover and call. The tool logic is identical to RealThor's original
local tools; the only thing that changed is the transport: a standard protocol
instead of an in-process function list.

Run it: ``uv run proptech-mcp serve`` (streamable HTTP on the configured host/port),
or ``uv run proptech-mcp serve --transport stdio`` for a client that launches it directly.
"""

import click
import pandas as pd
from fastmcp import FastMCP

from company_mcp.config import load_config, resolve_paths


def build_server(cfg: dict) -> FastMCP:
    """Build the MCP server, registering the read-only data tools over the CSVs."""
    mcp = FastMCP("proptech-data")

    demand = pd.read_csv(cfg["paths"]["demand_data"])
    supply = pd.read_csv(cfg["paths"]["supply_data"])
    velocity = pd.read_csv(cfg["paths"]["velocity_data"])

    @mcp.tool
    def get_demand_signals(region: str, property_type: str, bedrooms: int) -> str:
        """Get demand signals for a real estate segment in Ciudaty.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        d = demand[
            (demand["region"] == region)
            & (demand["property_type"] == property_type)
            & (demand["bedrooms"] == bedrooms)
        ]
        if d.empty:
            return "No demand data available for this segment."
        return d.to_string(index=False)

    @mcp.tool
    def get_supply_snapshot(region: str, property_type: str, bedrooms: int) -> str:
        """Get supply snapshot for a real estate segment in Ciudaty.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        s = supply[
            (supply["region"] == region)
            & (supply["property_type"] == property_type)
            & (supply["bedrooms"] == bedrooms)
        ]
        if s.empty:
            return "No supply data available for this segment."
        return s.to_string(index=False)

    @mcp.tool
    def get_listing_velocity(region: str, property_type: str, bedrooms: int) -> str:
        """Get listing velocity metrics for a real estate segment in Ciudaty.

        Returns average days to offer, days to close, velocity score, and confidence.

        Args:
            region: Ciudaty region (west, north, south, east, center)
            property_type: Property type (apartment, house, studio)
            bedrooms: Number of bedrooms
        """
        v = velocity[
            (velocity["region"] == region)
            & (velocity["property_type"] == property_type)
            & (velocity["bedrooms"] == bedrooms)
        ]
        if v.empty:
            return "No velocity data available for this segment."
        return v.to_string(index=False)

    return mcp


@click.group()
def main():
    """RealThor market-data service (MCP)."""


@main.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True)
@click.option(
    "--transport",
    default=None,
    help="Override the transport: streamable-http (default) or stdio.",
)
@click.option("--host", default=None, help="Override the HTTP bind host (e.g. 0.0.0.0 in Docker).")
@click.option("--port", default=None, type=int, help="Override the HTTP port.")
def serve(config_path, transport, host, port):
    """Start the MCP server on the configured transport."""
    cfg = resolve_paths(load_config(config_path), config_path)
    mcp = build_server(cfg)
    chosen = transport or cfg["mcp"]["transport"]
    if chosen == "stdio":
        mcp.run(transport="stdio", show_banner=False)
    else:
        # allowed_hosts relaxes FastMCP's DNS-rebinding protection (which by
        # default only permits localhost) so a client on another host — e.g. the
        # `realthor` container reaching `http://mcp:8000` over the compose network —
        # is accepted. Default "*" is fine for this unauthenticated dev service; a
        # production server would pin real hostnames and add a token.
        mcp.run(
            transport="http",
            host=host or cfg["mcp"]["host"],
            port=port or cfg["mcp"]["port"],
            allowed_hosts=cfg["mcp"].get("allowed_hosts", ["*"]),
            show_banner=False,
        )
