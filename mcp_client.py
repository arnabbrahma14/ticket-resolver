# mcp_client.py
# This is a lightweight MCP client.
# It starts your MCP server as a subprocess and talks to it.

import asyncio
import json
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def get_mcp_tools():
    """
    Connects to the MCP server and fetches the list of available tools.
    Returns them in Groq-compatible tool format.
    """
    # StdioServerParameters tells the client HOW to start the server
    # It runs: python -m mcp_server.server
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server.server"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Do the MCP handshake
            await session.initialize()

            # Ask the server: "what tools do you have?"
            tools_result = await session.list_tools()

            # Convert MCP tool format → Groq tool format
            groq_tools = []
            for tool in tools_result.tools:
                groq_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    }
                })

            return groq_tools


async def call_mcp_tool(tool_name: str, tool_args: dict) -> str:
    """
    Connects to the MCP server and calls a specific tool with given arguments.
    Returns the result as a string.
    """
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_server.server"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Call the tool on the MCP server
            result = await session.call_tool(tool_name, tool_args)

            # result.content is a list of TextContent objects
            # We grab the first one's text
            return result.content[0].text
