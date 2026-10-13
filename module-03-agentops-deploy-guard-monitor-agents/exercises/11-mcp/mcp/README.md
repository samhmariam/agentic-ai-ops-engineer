# RealThor Market-Data Service (MCP)

Serves RealThor's read-only market-data lookups — demand, supply, listing
velocity — as **MCP tools** over the Model Context Protocol. Any compatible
client (RealThor, another agent, an IDE) can discover and call them without
bespoke integration code.

## Setup

```sh
uv sync
```

## Run the server

```sh
uv run proptech-mcp serve                     # streamable HTTP on http://127.0.0.1:8000/mcp
uv run proptech-mcp serve --transport stdio   # subprocess transport (client launches it)
```

Host, port, and default transport come from `config.yaml` (`mcp:` section).

## Tools

| Tool | Args | Returns |
|---|---|---|
| `get_demand_signals` | region, property_type, bedrooms | demand rows for the segment |
| `get_supply_snapshot` | region, property_type, bedrooms | supply rows for the segment |
| `get_listing_velocity` | region, property_type, bedrooms | velocity metrics for the segment |

## Project structure

```
mcp/
├── src/company_mcp/
│   ├── server.py     # build_server() + the `mcp serve` CLI
│   └── config.py     # load/resolve config
├── data/             # the CSVs this service owns (demand, supply, velocity)
├── tests/            # offline, in-memory FastMCP client
├── config.yaml       # transport, host, port, data paths
└── pyproject.toml    # [project.scripts] mcp = company_mcp.server:main
```

## How to verify

```sh
sh ops.sh            # runs the offline test suite (no network, no keys)
```

## Docker

```sh
docker build -t proptech-mcp .
docker run --rm -p 8000:8000 proptech-mcp     # serve on 0.0.0.0:8000
```
