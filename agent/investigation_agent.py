# agent/investigation_agent_groq.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from groq import Groq
from tools.fetch_logs import fetch_logs
from tools.check_metrics import check_metrics
from tools.search_incidents import search_past_incidents
from tools.generate_report import generate_report
from dotenv import load_dotenv

load_dotenv()

# Tool definitions stay EXACTLY the same as Anthropic version
# Groq format — note the wrapper and the renamed key
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_logs",
            "description": (
                "Fetch recent log entries for a specific service. "
                "Use this first when investigating any incident to understand "
                "what errors appeared and when. Filter by severity to focus on errors."
            ),
            "parameters": {                    # ← was input_schema in Anthropic
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "The service name, e.g. 'auth-service', 'payment-service'"
                    },
                    "severity": {
                        "type": "string",
                        "description": "Filter by log level: ERROR, WARN, INFO, or ALL",
                        "enum": ["ERROR", "WARN", "INFO", "ALL"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of log lines to return. Default 20."
                    }
                },
                "required": ["service"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_metrics",
            "description": (
                "Get infrastructure metrics for a service: CPU, memory, DB connections, "
                "error rate, latency. Use this to spot resource exhaustion or performance "
                "anomalies. Anomalies are clearly flagged in the output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "The service name to check metrics for"
                    }
                },
                "required": ["service"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_past_incidents",
            "description": (
                "Search the knowledge base of past resolved incidents for ones similar "
                "to the current issue. Always call this after you have a hypothesis — "
                "past incidents often contain the exact resolution steps needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of the current issue"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of similar incidents to return. Default 3."
                    },
                    "service_filter": {
                        "type": "string",
                        "description": "Optional: limit search to a specific service name"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": (
                "Generate the final structured resolution report. Call this ONLY when "
                "you have completed your investigation and have enough evidence to "
                "diagnose the root cause and recommend resolution steps. "
                "This ends the investigation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id":           {"type": "string"},
                    "service":             {"type": "string"},
                    "priority":            {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "category":            {"type": "string"},
                    "root_cause":          {"type": "string"},
                    "confidence":          {"type": "string", "enum": ["high", "medium", "low"]},
                    "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                    "resolution_steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step":            {"type": "integer"},
                                "action":          {"type": "string"},
                                "command":         {"type": "string"},
                                "expected_result": {"type": "string"}
                            }
                        }
                    },
                    "similar_incidents": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":                  {"type": "string"},
                                "similarity":          {"type": "string"},
                                "resolution_summary":  {"type": "string"}
                            }
                        }
                    },
                    "fallback_advice": {"type": "string"}
                },
                "required": [
                    "ticket_id", "service", "priority", "category",
                    "root_cause", "confidence", "supporting_evidence",
                    "resolution_steps", "similar_incidents"
                ]
            }
        }
    }
]

# execute_tool is IDENTICAL to the Anthropic version — no changes needed
def execute_tool(tool_name: str, tool_input: dict) -> str:
    print(f"\n  🔧 Calling: {tool_name}({json.dumps(tool_input)})")

    if tool_name == "fetch_logs":
        return fetch_logs(**tool_input)
    elif tool_name == "check_metrics":
        return check_metrics(**tool_input)
    elif tool_name == "search_past_incidents":
        return search_past_incidents(**tool_input)
    elif tool_name == "generate_report":
        return generate_report(**tool_input)
    else:
        return f"Unknown tool: {tool_name}"


SYSTEM_PROMPT = """You are an expert Site Reliability Engineer investigating support tickets.

Follow this investigation process strictly:
1. Fetch logs for the affected service first
2. Check metrics for that service
3. Search past incidents for similar issues
4. Generate the resolution report with your findings

Never skip steps. Never generate the report before checking logs, metrics, and past incidents.
"""


def run_agent(ticket_id: str, ticket_text: str) -> str:
    client = Groq()

    print(f"\n{'='*60}")
    print(f"🎫 Investigating ticket: {ticket_id}")
    print(f"📋 {ticket_text}")
    print(f"{'='*60}")

    # ── Groq difference 1: system goes inside messages list ──────────────────
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Please investigate this support ticket and generate a resolution report.\n\n"
                f"Ticket ID: {ticket_id}\n"
                f"Description: {ticket_text}"
            )
        }
    ]

    final_report = None
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n--- Iteration {iteration} ---")

        # ── Groq difference 2: different client call ─────────────────────────
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto"
        )

        choice = response.choices[0]
        print(f"  Stop reason: {choice.finish_reason}")

        # ── Groq difference 3: different stop reason name ────────────────────
        if choice.finish_reason == "stop":
            # LLM is done, no more tool calls
            if choice.message.content:
                print(f"\n💬 Agent: {choice.message.content}")
            break

        if choice.finish_reason != "tool_calls":
            print(f"  Unexpected stop reason: {choice.finish_reason}")
            break

        tool_calls = choice.message.tool_calls
        if not tool_calls:
            break

        # ── Groq difference 4: append assistant message WITH tool calls ──────
        # This is required before adding tool results
        messages.append({
            "role": "assistant",
            "content": choice.message.content,   # may be None — that's fine
            "tool_calls": tool_calls
        })

        # ── THIS IS THE BLOCK YOU NOTICED WAS MISSING ────────────────────────
        # Same purpose as in the Anthropic version:
        #   1. Print the LLM's thinking (if any text came with the tool call)
        #   2. Run each tool via execute_tool()
        #   3. Check if generate_report was called → set final_report
        #   4. Collect all results to send back to the LLM
        # ─────────────────────────────────────────────────────────────────────

        for tool_call in tool_calls:

            # 1. Print thinking — in Groq, text comes in choice.message.content
            if choice.message.content:
                print(f"\n🧠 Thinking: {choice.message.content[:200]}")

            tool_name = tool_call.function.name

            # ── Groq difference 5: arguments come as a JSON STRING ────────────
            # Anthropic gives a ready dict. Groq gives a string you must parse.
            try:
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                print(f"  ⚠️ Failed to parse tool arguments: {e}")
                tool_input = {}   # safe fallback

            # 2. Run the actual tool — same execute_tool() as Anthropic version
            result = execute_tool(tool_name, tool_input)

            # 3. Check if investigation is complete
            if tool_name == "generate_report":
                final_report = result
                print(f"\n✅ Report generated!")

            # ── Groq difference 6: results go as separate "tool" role messages
            # Anthropic bundles them as user turn blocks.
            # Groq wants one message per tool result with role="tool"
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,   # links result to the request
                "content": result
            })

        # 4. If we have the final report, stop the loop
        if final_report:
            break

    return final_report or "Investigation did not produce a report."


if __name__ == "__main__":
    report = run_agent(
        ticket_id="TKT-4821",
        ticket_text=(
            "auth-service is throwing 500 errors on the login endpoint since "
            "approximately 2am. Multiple users cannot log in. Please investigate urgently."
        )
    )

    print("\n" + "="*60)
    print("📄 FINAL RESOLUTION REPORT")
    print("="*60)
    print(report)
    