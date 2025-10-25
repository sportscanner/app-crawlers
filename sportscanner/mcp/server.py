
# """Geoapify MCP Server implementation using FastMCP and streamable HTTP."""

import asyncio
from sportscanner.logger import logging
from fastmcp import FastMCP
from fastmcp.tools import Tool

from sportscanner.mcp.registry import TOOL_FUNCTIONS

mcp = FastMCP(
    name="Sportscanner Unified MCP",
    tools=[func for func in TOOL_FUNCTIONS.values()],
)

'''Following code block doesn't register tools with some clients like DeepChat'''
# Register each function as a tool (loop over your dict for convenience)
# for tool_name, func in TOOL_FUNCTIONS.items():
#     tool = Tool.from_function(func, name=tool_name)
#     mcp.add_tool(tool)

if __name__ == "__main__":
    async def list_tools():
        tools = await mcp.get_tools()  # Or mcp.list_tools() in older versions
        print("Registered tools:", [tool.name for tool in tools.values()])  # Use .values() for Tool objects
    asyncio.run(list_tools())
    mcp.run(transport="http", port=8080)  # Change 8080 to your desired port