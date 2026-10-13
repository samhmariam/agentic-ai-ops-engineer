"""Connect RealThor to the MCP data service.

RealThor no longer builds its market-data tools in-process. It fetches them from
the running MCP server over the Model Context Protocol, so the exact same tools
are callable by any MCP client — not just RealThor. This module builds the
client from ``cfg["mcp"]`` and returns the server's tools as LangChain tools;
the rest of the app treats them like any other tool.

``load_mcp_tools`` is the one piece students implement — the connection that
makes RealThor a client of the standard tool service.
"""

from langchain_mcp_adapters.client import MultiServerMCPClient


async def load_mcp_tools(cfg: dict) -> list:
    """Build the MCP client from config and return the server's tools.

    ``cfg["mcp"]`` selects the transport:
      * streamable HTTP → connect to a running server at ``url``
      * stdio           → launch the server as a subprocess (``command`` + ``args``)
    """
    mcp = cfg["mcp"]
    transport = mcp["transport"].replace("-", "_")  # "streamable-http" → "streamable_http"
    if transport == "stdio":
        server = {"transport": "stdio", "command": mcp["command"], "args": mcp["args"]}
    else:
        server = {"transport": transport, "url": mcp["url"]}

    client = MultiServerMCPClient({"proptech-data": server})
    return await client.get_tools()
