"""SportScanner MCP server entrypoint."""

import asyncio

from fastmcp import FastMCP
from fastmcp.tools import Tool

from sportscanner.mcp.registry import TOOL_FUNCTIONS

INSTRUCTIONS = (
    "SportScanner MCP server exposing typed tools for SportScanner API routes. "
    "These tools wrap venue discovery, slot search, geolocation, health checks, "
    "user profile operations, and notification operations."
)

mcp = FastMCP(name="SportScanner API MCP", instructions=INSTRUCTIONS)

for tool_name, tool_fn in TOOL_FUNCTIONS.items():
    mcp.add_tool(Tool.from_function(tool_fn, name=tool_name))


if __name__ == "__main__":

    async def list_tools() -> None:
        tools = await mcp.list_tools(run_middleware=False)
        print("Registered tools:", [tool.name for tool in tools])

    asyncio.run(list_tools())
    mcp.run(transport="http", port=8080)
