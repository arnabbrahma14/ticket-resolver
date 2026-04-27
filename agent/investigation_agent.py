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
            "past incidents often contain the exact resolution steps needed. "
            "Pass a natural language description of the symptoms you observed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language description of the current issue. "
                        "Example: 'postgresql connection pool exhausted auth-service'"
                    )
                }
            },
            "required": ["query"]
            # Removed top_k and service_filter — LLaMA gets confused with
            # too many optional params and generates malformed JSON arrays.
            # Defaults are handled inside the Python function directly.
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
    # LLM only passes query now — we set sensible defaults here
        return search_past_incidents(
            query=tool_input.get("query", ""),
            top_k=3,
            service_filter=None
        )
    elif tool_name == "generate_report":
        return generate_report(**tool_input)
    else:
        return f"Unknown tool: {tool_name}"


# Changes to agent/investigation_agent.py
# Only showing what changes — keep everything else the same

# ── Update the system prompt to reference triage context ──────────────────

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) investigating support tickets.

You will be given a ticket along with triage context (priority, category, affected service).
Use this context to focus your investigation — don't re-classify what triage already determined.

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
- The resolution_steps must be specific commands a human can run immediately
- Never take actions — you only investigate and report
"""


# ── Update run_agent() to accept and use triage_result ────────────────────

def run_agent(ticket_id: str, ticket_text: str, triage_result: dict = None) -> str:
    """
    Run the full investigation for a ticket.
    Accepts optional triage_result from the triage agent.
    Returns the final JSON resolution report.
    """
    client = Groq()

    print(f"\n{'='*60}")
    print(f"🎫 Investigating ticket: {ticket_id}")
    print(f"{'='*60}")

    # Build the first user message
    # If we have triage context, include it so the agent starts focused
    if triage_result:
        user_message = (
            f"Please investigate this support ticket and generate a resolution report.\n\n"
            f"Ticket ID: {ticket_id}\n"
            f"Description: {ticket_text}\n\n"
            f"--- Triage Context (already determined) ---\n"
            f"Priority:         {triage_result.get('priority', 'unknown')}\n"
            f"Category:         {triage_result.get('category', 'unknown')}\n"
            f"Affected Service: {triage_result.get('affected_service', 'unknown')}\n"
            f"Summary:          {triage_result.get('summary', '')}\n"
            f"-------------------------------------------\n\n"
            f"Start by fetching logs for the affected service above."
        )
    else:
        user_message = (
            f"Please investigate this support ticket and generate a resolution report.\n\n"
            f"Ticket ID: {ticket_id}\n"
            f"Description: {ticket_text}"
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message}
    ]

    final_report = None
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n--- Iteration {iteration} ---")

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=TOOL_DEFINITIONS,
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

        messages.append({
            "role":       "assistant",
            "content":    choice.message.content,
            "tool_calls": tool_calls
        })

        for tool_call in tool_calls:

            if choice.message.content:
                print(f"\n🧠 Thinking: {choice.message.content[:200]}")

            tool_name = tool_call.function.name

            try:
                tool_input = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                print(f"  ⚠️ Failed to parse tool arguments: {e}")
                tool_input = {}

            result = execute_tool(tool_name, tool_input)

            if tool_name == "generate_report":
                final_report = result
                print(f"\n✅ Report generated!")

            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      result
            })

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
    