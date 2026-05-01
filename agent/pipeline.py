# agent/pipeline.py
# This is the entry point for the full system.
# Triage runs first, then investigation uses its output.

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import sys
import asyncio                          # PHASE 6: added for async support
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from agent.triage_agent import run_triage
from agent.investigation_agent import run_agent
import json


async def process_ticket(ticket_id: str, ticket_text: str) -> str:  # PHASE 6: now async
    """
    Full pipeline:
      1. Triage agent classifies the ticket
      2. Investigation agent uses triage context to investigate
      3. Returns the final resolution report
    """

    # ── Step 1: Triage ────────────────────────────────────────────────────────
    triage_result = run_triage(ticket_id, ticket_text)  # triage stays sync — no change

    print(f"\n{'─'*60}")
    print(f"📋 Triage complete. Priority: {triage_result['priority'].upper()}")
    print(f"   Handing off to investigation agent...")
    print(f"{'─'*60}")

    # ── Optional: skip investigation for low priority tickets ─────────────────
    if triage_result["priority"] == "low":
        print("ℹ️  Low priority ticket — investigation will still run for learning purposes.")

    # ── Step 2: Investigation ─────────────────────────────────────────────────
    report = await run_agent(                           # PHASE 6: await added
        ticket_id=ticket_id,
        ticket_text=ticket_text,
        triage_result=triage_result
    )

    return report


async def run_all_tickets(test_cases):                  # PHASE 6: async wrapper for the loop
    for ticket in test_cases:
        print(f"\n{'#'*60}")
        print(f"# NEW TICKET: {ticket['id']}")
        print(f"{'#'*60}")

        report = await process_ticket(ticket["id"], ticket["text"])

        print(f"\n{'='*60}")
        print(f"📄 FINAL RESOLUTION REPORT — {ticket['id']}")
        print(f"{'='*60}")

        # In pipeline.py — replace the pretty-print block with this:

    try:
        # MCP returns results as JSON strings — may need double-parsing
        parsed = json.loads(report)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)   # unwrap the extra layer
        print(json.dumps(parsed, indent=2))
    except Exception:
        print(report)

        print("\n")


if __name__ == "__main__":

    test_cases = [
        {
            "id":   "TKT-4821",
            "text": (
                "auth-service is throwing 500 errors on the login endpoint since "
                "approximately 2am. Multiple users cannot log in. Please investigate urgently."
            )
        },
        {
            "id":   "TKT-4822",
            "text": (
                "notification-service pod keeps restarting every 20 minutes. "
                "Users are not receiving emails. OOMKilled showing in kubectl events."
            )
        }
    ]

    asyncio.run(run_all_tickets(test_cases))            # PHASE 6: asyncio.run() here