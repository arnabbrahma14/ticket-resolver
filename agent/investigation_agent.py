# agent/investigation_agent.py

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
from agent.memory import ShortTermMemory, get_service_history, save_investigation
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# TOOL DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

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
            "parameters": {
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
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket ID, e.g. TKT-4821"
                },
                "service": {
                    "type": "string",
                    "description": "The affected service name"
                },
                "priority": {
                    "type": "string",
                    "description": "critical, high, medium, or low"
                },
                "category": {
                    "type": "string",
                    "description": "database, memory, network, deployment, cache, security, or other"
                },
                "root_cause": {
                    "type": "string",
                    "description": "One clear sentence describing what went wrong"
                },
                "confidence": {
                    "type": "string",
                    "description": "high, medium, or low"
                },
                "resolution_summary": {
                    "type": "string",
                    "description": (
                        "A detailed description of the resolution steps as plain text. "
                        "Include specific commands and what to expect after each step."
                    )
                },
                "evidence_summary": {
                    "type": "string",
                    "description": (
                        "A plain text summary of the supporting evidence found during investigation. "
                        "Include key log findings, metric anomalies, and past incident matches."
                    )
                }
            },
            "required": [
                "ticket_id", "service", "priority", "category",
                "root_cause", "confidence", "resolution_summary", "evidence_summary"
            ]
        }
    }
     }
]

# ─────────────────────────────────────────────────────────────────────────────
# TOOL EXECUTOR
# Now accepts short_term_memory so it can note key findings
# and truncate large results before they go into the messages list
# ─────────────────────────────────────────────────────────────────────────────

def execute_tool(
    tool_name:         str,
    tool_input:        dict,
    short_term_memory: ShortTermMemory
) -> str:
    """
    Runs the tool and returns the result as a string.
    Also notes key findings in short-term memory
    and truncates large results to protect the context window.
    """
    print(f"\n  🔧 Calling: {tool_name}({json.dumps(tool_input)})")

    if tool_name == "fetch_logs":
        result = fetch_logs(**tool_input)

        # Note the first ERROR line as a finding — concise signal for the LLM
        if "ERROR" in result:
            first_error = next(
                (line for line in result.splitlines() if "ERROR" in line),
                ""
            )
            # next() returns the first matching item from the iterator
            # The "" is the default if nothing matches
            short_term_memory.add_finding(f"Logs: {first_error[:120]}")

        # Truncate to 1500 chars — agent gets the signal without flooding context
        return result[:1500]

    elif tool_name == "check_metrics":
        result = check_metrics(**tool_input)

        # Note critical metrics as a finding
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
        # Only pass query — top_k and service_filter hardcoded here
        # Avoids Groq/LLaMA optional param bug that generates malformed JSON arrays
        result = search_past_incidents(
            query=tool_input.get("query", ""),
            top_k=3,
            service_filter=None
        )

        # Note if a strong match was found (80%+ similarity)
        if "Similarity: 8" in result or "Similarity: 9" in result:
            short_term_memory.add_finding(
                "Strong past incident match found — check resolution steps"
            )

        # Past incidents can be very long — truncate to 2000 chars
        return result[:2000]

    elif tool_name == "generate_report":
        return generate_report(**tool_input)

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

def run_agent(
    ticket_id:     str,
    ticket_text:   str,
    triage_result: dict = None
) -> str:
    """
    Run the full investigation for a ticket.
    Uses short-term memory to track findings and manage context window.
    Uses long-term memory to provide service history and save results.
    Returns the final JSON resolution report.
    """
    client = Groq()

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

            # Run tool — pass short-term memory so findings are noted
            result = execute_tool(tool_name, tool_input, stm)

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
    if final_report:
        try:
            report_dict = json.loads(final_report)
            save_investigation(
            ticket_id=ticket_id,
            service=service,
            priority=report_dict.get("triage", {}).get("priority", "unknown"),
            category=report_dict.get("triage", {}).get("category", "unknown"),
            root_cause=report_dict.get("diagnosis", {}).get("most_likely_root_cause", ""),
            resolution_type="agent_investigation",
            summary=report_dict.get("diagnosis", {}).get("confidence", "unknown")
            # simplified — no longer looking for resolution_steps list
        )
        except Exception as e:
            print(f"  ⚠️ Could not save to long-term memory: {e}")

    return final_report or "Investigation did not produce a report."


# ─────────────────────────────────────────────────────────────────────────────
# CLI RUNNER
# ─────────────────────────────────────────────────────────────────────────────

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
