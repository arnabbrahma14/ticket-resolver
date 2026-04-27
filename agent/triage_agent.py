# agent/triage_agent.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# What triage produces — a simple structured result
# The investigation agent reads this before it starts
# ─────────────────────────────────────────────────────────────────────────────

TRIAGE_SYSTEM_PROMPT = """You are a support ticket triage specialist.
Your only job is to read a ticket and classify it quickly.

You must respond with ONLY a JSON object — no explanation, no extra text.
The JSON must have exactly these fields:

{
  "priority": "critical" | "high" | "medium" | "low",
  "category": "database" | "memory" | "network" | "deployment" | "cache" | "security" | "infrastructure" | "other",
  "affected_service": "the service name mentioned or inferred from the ticket",
  "summary": "one sentence describing the core problem"
}

Priority rules:
- critical: production is down, users cannot use the system at all
- high: major feature broken, many users affected
- medium: partial degradation, workaround exists
- low: minor issue, cosmetic, or single user affected

Always extract the service name from the ticket text if mentioned.
If no service is mentioned, set affected_service to "unknown".
"""


def run_triage(ticket_id: str, ticket_text: str) -> dict:
    """
    Classify a ticket quickly using a single LLM call.
    Returns a dictionary with priority, category, affected_service, summary.

    This is intentionally a single LLM call with no tools — fast and cheap.
    The full investigation only runs after triage confirms priority.
    """
    client = Groq()

    print(f"\n{'='*60}")
    print(f"🔍 Triaging ticket: {ticket_id}")
    print(f"{'='*60}")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user",   "content": f"Ticket ID: {ticket_id}\n\n{ticket_text}"}
        ],
        # No tools here — triage is pure reasoning, no tool calls needed
        temperature=0,
        # temperature=0 means the model gives its most confident, deterministic answer
        # We want consistent classification — not creative variation
        max_tokens=256
        # Triage output is tiny — just a small JSON object
        # Keeping max_tokens low saves cost and forces brevity
    )

    raw_output = response.choices[0].message.content.strip()

    print(f"  Raw triage output: {raw_output}")

    # ── Parse the JSON the LLM returned ──────────────────────────────────────
    # LLMs sometimes wrap JSON in ```json ... ``` even when told not to.
    # We strip those fences before parsing just in case.
    try:
        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            # Remove closing fence
            cleaned = cleaned.rsplit("```", 1)[0]

        triage_result = json.loads(cleaned.strip())

    except json.JSONDecodeError as e:
        # If the LLM returned something unparseable, use safe defaults
        # Never crash — triage failure should not block investigation
        print(f"  ⚠️  Triage JSON parse failed: {e}. Using defaults.")
        triage_result = {
            "priority":         "high",
            "category":         "other",
            "affected_service": "unknown",
            "summary":          ticket_text[:100]
        }

    print(f"  ✅ Priority:  {triage_result.get('priority')}")
    print(f"  ✅ Category:  {triage_result.get('category')}")
    print(f"  ✅ Service:   {triage_result.get('affected_service')}")
    print(f"  ✅ Summary:   {triage_result.get('summary')}")

    return triage_result


# ─────────────────────────────────────────────────────────────────────────────
# Test it directly
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_tickets = [
        {
            "id": "TKT-001",
            "text": "auth-service is down, nobody can log in, all getting 500 errors since 2am"
        },
        {
            "id": "TKT-002",
            "text": "payment service is running slow, checkouts taking 10 seconds, some users giving up"
        },
        {
            "id": "TKT-003",
            "text": "notification-service pod keeps restarting every 20 minutes, OOMKilled in logs"
        },
        {
            "id": "TKT-004",
            "text": "one user says the dark mode toggle looks a bit off on their screen"
        }
    ]

    for ticket in test_tickets:
        result = run_triage(ticket["id"], ticket["text"])
        print()
        