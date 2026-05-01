# mcp_server/server.py

import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# FIXED: import names now match actual filenames and function names in your project
from mcp_server.tools.fetch_logs import fetch_logs
from mcp_server.tools.check_metrics import check_metrics
from mcp_server.tools.search_incidents import search_past_incidents   # FIXED function name
from mcp_server.tools.generate_report import generate_report           # FIXED file + function name

app = Server("support-ticket-mcp")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="fetch_logs",
            description="Fetch recent log entries for a specific service.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service":  {"type": "string", "description": "The service name, e.g. auth-service"},
                    "severity": {"type": "string", "description": "Filter by log level: ERROR, WARN, INFO, or ALL"},
                    "limit":    {"type": "integer", "description": "Max number of log lines to return. Default 20."}
                },
                "required": ["service"]
            },
        ),
        types.Tool(
            name="check_metrics",
            description="Get CPU, memory, error rate and latency metrics for a service.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "The service name to check metrics for"}
                },
                "required": ["service"]
            },
        ),
        # FIXED: name changed from "search_incidents" to "search_past_incidents"
        # to match what investigation_agent.py expects
        # In mcp_server/server.py — replace the search_past_incidents Tool definition with this:

         types.Tool(
            name="search_past_incidents",
            description="Search the knowledge base of past resolved incidents using semantic similarity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language description of the current issue"}
                },
                "required": ["query"]   # query is the ONLY parameter — no optional ones
            },
        ),
        # FIXED: name changed from "create_report" to "generate_report"
        types.Tool(
            name="generate_report",
            description="Generate the final structured resolution report. Call only when investigation is complete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id":         {"type": "string"},
                    "service":           {"type": "string"},
                    "priority":          {"type": "string"},
                    "category":          {"type": "string"},
                    "root_cause":        {"type": "string"},
                    "confidence":        {"type": "string"},
                    "resolution_summary":{"type": "string"},
                    "evidence_summary":  {"type": "string"}
                },
                "required": [
                    "ticket_id", "service", "priority", "category",
                    "root_cause", "confidence", "resolution_summary", "evidence_summary"
                ]
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "fetch_logs":
        result = fetch_logs(**arguments)

    elif name == "check_metrics":
        result = check_metrics(**arguments)

    # FIXED: route name matches the registered tool name above
    elif name == "search_past_incidents":
        result = search_past_incidents(
            query=arguments["query"],
            top_k=3,
            service_filter=None
        )

    # FIXED: route name matches the registered tool name above
    elif name == "generate_report":
        result = generate_report(**arguments)

    else:
        result = {"error": f"Unknown tool: {name}"}

    import json
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())