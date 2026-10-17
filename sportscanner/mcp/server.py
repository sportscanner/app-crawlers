"""Public, read-only court and venue tools over Streamable HTTP."""

from fastmcp import FastMCP
from mcp.types import Icon

from sportscanner.mcp.registry import TOOL_FUNCTIONS

# Every registered tool reads publicly available data. Keep account/profile
# operations in their separately authenticated REST routers, never here.
mcp = FastMCP(
    name="Sportscanner Unified MCP",
    version="1.0.0",
    instructions=(
        "Public court and venue search: no account, API key or OAuth required. "
        "Return availability, freshness and provider booking links. "
        "These tools cannot access user profiles, reserve courts or take payment."
    ),
    tools=list(TOOL_FUNCTIONS.values()),
    auth=None,
    website_url="https://www.sportscanner.co.uk",
    icons=[Icon(src="https://www.sportscanner.co.uk/sportscanner.svg")],
)

if __name__ == "__main__":
    mcp.run(transport="http", port=8080)
