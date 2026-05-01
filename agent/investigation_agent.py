# agent/investigation_agent.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import asyncio

from groq import Groq
# PHASE 6: Tool functions are no longer imported directly.
# They now live in the MCP server and are called via the MCP protocol.
from mcp_client import get_mcp_tools, call_mcp_tool
from agent.memory import ShortTermMemory, get_service_history, save_investigation
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# TOOL DEFINITIONS
# PHASE 6: Tools are no longer defined statically here.
# They are fetched dynamically from the MCP server at runtime via get_mcp_tools().
# This means if you add/change a tool in mcp_server/server.py,
# the agent automatically picks it up — no changes needed here.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# TOOL EXECUTOR
# Now accepts short_term_memory so it can note key findings
# and truncate large results before they go into the messages list
# ─────────────────────────────────────────────────────────────────────────────

async def execute_tool(
    tool_name:         str,
    tool_input:        dict,
    short_term_memory: ShortTermMemory
) -> str:
    """
    PHASE 6: Now async — calls tools via the MCP server instead of directly.
    All tool logic lives in mcp_server/tools/*.py and is accessed over MCP protocol.
    Short-term memory noting and truncation logic is unchanged from Phase 5.
    """
    print(f"\n  🔧 Calling: {tool_name}({json.dumps(tool_input)})")

    if tool_name == "fetch_logs":
        # PHASE 6: was fetch_logs(**tool_input), now goes via MCP
        result = await call_mcp_tool("fetch_logs", tool_input)

        if "ERROR" in result:
            first_error = next(
                (line for line in result.splitlines() if "ERROR" in line),
                ""
            )
            short_term_memory.add_finding(f"Logs: {first_error[:120]}")

        return result[:1500]

    elif tool_name == "check_metrics":
        # PHASE 6: was check_metrics(**tool_input), now goes via MCP
        result = await call_mcp_tool("check_metrics", tool_input)

        if "CRITICAL" in result:
            critical_lines = [
                line for line in result.splitlines()
                if "CRITICAL" in line
            ]
            if critical_lines:
                short_term_memory.add_finding(
                    f"Metrics: {' | '.join(critical_lines[:3])}"
                )

        return result

    elif tool_name == "search_past_incidents":
        # PHASE 6: was search_past_incidents(query=..., top_k=3, service_filter=None)
        # MCP server handles top_k and service_filter internally — we only pass query
        result = await call_mcp_tool(
            "search_past_incidents",
            {"query": tool_input.get("query", "")}
        )

        if "Similarity: 8" in result or "Similarity: 9" in result:
            short_term_memory.add_finding(
                "Strong past incident match found — check resolution steps"
            )

        return result[:2000]

    elif tool_name == "generate_report":
        # PHASE 6: was generate_report(**tool_input), now goes via MCP
        result = await call_mcp_tool("generate_report", tool_input)
        return result

    else:
        return f"Unknown tool: {tool_name}"


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) investigating support tickets.

You will be given a ticket along with triage context (priority, category, affected service).
Use this context to focus your investigation — don't re-classify what triage already determined.
You may also be given past investigation history for the affected service — use it to spot patterns.

Your job is to investigate thoroughly and produce a resolution report.
You NEVER guess. You always gather evidence first.

Follow this investigation process:
1. Fetch logs for the affected service identified in triage
2. Check metrics for that same service
3. Search past incidents using the symptoms and category from triage
4. Once you have enough evidence, generate the resolution report

Rules:
- Always call fetch_logs and check_metrics before forming a conclusion
- Always call search_past_incidents with a meaningful query
- Only call generate_report when you have clear evidence for the root cause
- Use the priority from triage in your report — do not change it
- If this looks like a recurring issue based on history, mention it in the report
- The resolution_steps must be specific commands a human can run immediately
- Never take actions — you only investigate and report
"""


# ─────────────────────────────────────────────────────────────────────────────
# THE REACT LOOP — updated for Phase 5 memory
# ─────────────────────────────────────────────────────────────────────────────

async def run_agent(
    ticket_id:     str,
    ticket_text:   str,
    triage_result: dict = None
) -> str:
    """
    PHASE 6: Now async — fetches tools from MCP server and calls them via MCP protocol.
    All memory logic, ReAct loop, and Groq message formatting unchanged from Phase 5.
    Returns the final JSON resolution report.
    """
    client = Groq()

    # ── PHASE 6: Fetch tool definitions dynamically from MCP server ─────────────
    # In Phase 5 this was a static TOOL_DEFINITIONS list defined at the top of the file.
    # Now we ask the MCP server "what tools do you have?" at the start of each run.
    # This means adding a new tool to mcp_server/server.py automatically appears here.
    print(f"\n🔌 Fetching tools from MCP server...")
    tools = await get_mcp_tools()
    print(f"   ✅ {len(tools)} tools loaded: {[t['function']['name'] for t in tools]}")

    # ── Get service name from triage ─────────────────────────────────────────
    service = (
        triage_result.get("affected_service", "unknown")
        if triage_result else "unknown"
    )

    # ── Initialise short-term memory for this investigation ──────────────────
    stm = ShortTermMemory(ticket_id, service)

    print(f"\n{'='*60}")
    print(f"🎫 Investigating ticket: {ticket_id}")
    print(f"{'='*60}")

    # ── Fetch long-term memory for this service ──────────────────────────────
    service_history = get_service_history(service)
    has_history     = "No previous investigations" not in service_history

    if has_history:
        print(f"\n📚 Long-term memory found for '{service}'")
        print(service_history[:300])
    else:
        print(f"\n📭 No previous history for '{service}' — fresh investigation")

    # ── Build first user message ──────────────────────────────────────────────
    if triage_result:
        user_message = (
            f"Please investigate this support ticket and generate a resolution report.\n\n"
            f"Ticket ID: {ticket_id}\n"
            f"Description: {ticket_text}\n\n"
            f"--- Triage Context (already determined) ---\n"
            f"Priority:         {triage_result.get('priority', 'unknown')}\n"
            f"Category:         {triage_result.get('category', 'unknown')}\n"
            f"Affected Service: {service}\n"
            f"Summary:          {triage_result.get('summary', '')}\n"
            f"-------------------------------------------\n\n"
        )
    else:
        user_message = (
            f"Please investigate this support ticket and generate a resolution report.\n\n"
            f"Ticket ID: {ticket_id}\n"
            f"Description: {ticket_text}\n\n"
        )

    # ── Inject long-term memory if available ─────────────────────────────────
    if has_history:
        user_message += (
            f"--- Service History (from long-term memory) ---\n"
            f"{service_history}\n"
            f"Use this history to identify recurring patterns. "
            f"If this looks like a repeat incident, mention it clearly in your report.\n"
            f"-----------------------------------------------\n\n"
        )

    user_message += "Start by fetching logs for the affected service above."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message}
    ]

    final_report  = None
    max_iterations = 10
    iteration      = 0

    # ── ReAct loop ────────────────────────────────────────────────────────────
    while iteration < max_iterations:
        iteration += 1
        print(f"\n--- Iteration {iteration} ---")

        # ── Inject short-term memory summary on even iterations ───────────────
        # This is Strategy 4 from Phase 3 — running summary
        # Instead of keeping full tool outputs in messages, we inject
        # a compact findings summary so the LLM never loses track of key signals
        if iteration > 1 and iteration % 2 == 0:
            # iteration % 2 == 0 means every even number: 2, 4, 6...
            messages.append({
                "role":    "user",
                "content": (
                    f"Quick summary of findings so far:\n"
                    f"{stm.get_summary()}\n"
                    f"Continue the investigation."
                )
            })

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=tools,       # PHASE 6: was TOOL_DEFINITIONS (static), now fetched from MCP
            tool_choice="auto"
        )

        choice = response.choices[0]
        print(f"  Stop reason: {choice.finish_reason}")

        if choice.finish_reason == "stop":
            if choice.message.content:
                print(f"\n💬 Agent: {choice.message.content}")
            break

        if choice.finish_reason != "tool_calls":
            print(f"  Unexpected stop reason: {choice.finish_reason}")
            break

        tool_calls = choice.message.tool_calls
        if not tool_calls:
            break

        # Append assistant message WITH tool calls before adding results
        messages.append({
            "role":       "assistant",
            "content":    choice.message.content,
            "tool_calls": tool_calls
        })

        for tool_call in tool_calls:

            if choice.message.content:
                print(f"\n🧠 Thinking: {choice.message.content[:200]}")

            tool_name = tool_call.function.name

            # Groq returns arguments as a JSON string — must parse
            try:
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                print(f"  ⚠️ Failed to parse tool arguments: {e}")
                tool_input = {}

            # PHASE 6: execute_tool is now async — must await it
            result = await execute_tool(tool_name, tool_input, stm)

            if tool_name == "generate_report":
                final_report = result
                print(f"\n✅ Report generated!")

            # Groq: one message per tool result with role="tool"
            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      result
            })

        if final_report:
            break

    # ── Save to long-term memory when investigation completes ─────────────────
    # At the bottom of run_agent() — replace the save block with this
# In run_agent(), replace the save block with this:

    if final_report:
        try:
            report_dict = json.loads(final_report)
            if isinstance(report_dict, str):        # unwrap MCP's extra JSON layer
                report_dict = json.loads(report_dict)
            save_investigation(
                ticket_id=ticket_id,
                service=service,
                priority=report_dict.get("triage", {}).get("priority", "unknown"),
                category=report_dict.get("triage", {}).get("category", "unknown"),
                root_cause=report_dict.get("diagnosis", {}).get("most_likely_root_cause", ""),
                resolution_type="agent_investigation",
                summary=report_dict.get("diagnosis", {}).get("confidence", "unknown")
            )
        except Exception as e:
            print(f"  ⚠️ Could not save to long-term memory: {e}")

    return final_report or "Investigation did not produce a report."


# ─────────────────────────────────────────────────────────────────────────────
# CLI RUNNER
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # PHASE 6: run_agent is now async, so we wrap it with asyncio.run()
    # asyncio.run() creates the event loop, runs the coroutine, then shuts it down
    report = asyncio.run(run_agent(
        ticket_id="TKT-4821",
        ticket_text=(
            "auth-service is throwing 500 errors on the login endpoint since "
            "approximately 2am. Multiple users cannot log in. Please investigate urgently."
        )
    ))

    print("\n" + "="*60)
    print("📄 FINAL RESOLUTION REPORT")
    print("="*60)
    print(report)
