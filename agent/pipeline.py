# agent/pipeline.py
# This is the entry point for the full system.
# Triage runs first, then investigation uses its output.

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from agent.triage_agent import run_triage
from agent.investigation_agent import run_agent
import json


def process_ticket(ticket_id: str, ticket_text: str) -> str:
    """
    Full pipeline:
      1. Triage agent classifies the ticket
      2. Investigation agent uses triage context to investigate
      3. Returns the final resolution report
    """

    # ── Step 1: Triage ────────────────────────────────────────────────────────
    triage_result = run_triage(ticket_id, ticket_text)

    print(f"\n{'─'*60}")
    print(f"📋 Triage complete. Priority: {triage_result['priority'].upper()}")
    print(f"   Handing off to investigation agent...")
    print(f"{'─'*60}")

    # ── Optional: skip investigation for low priority tickets ─────────────────
    # In a real system you might queue low priority tickets instead of
    # investigating them immediately. For now we investigate everything.
    if triage_result["priority"] == "low":
        print("ℹ️  Low priority ticket — investigation will still run for learning purposes.")

    # ── Step 2: Investigation ─────────────────────────────────────────────────
    report = run_agent(
        ticket_id=ticket_id,
        ticket_text=ticket_text,
        triage_result=triage_result      # pass triage context to investigation
    )

    return report


if __name__ == "__main__":

    # Test tickets — different categories to see triage working
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

    for ticket in test_cases:
        print(f"\n{'#'*60}")
        print(f"# NEW TICKET: {ticket['id']}")
        print(f"{'#'*60}")

        report = process_ticket(ticket["id"], ticket["text"])

        print(f"\n{'='*60}")
        print(f"📄 FINAL RESOLUTION REPORT — {ticket['id']}")
        print(f"{'='*60}")

        # Pretty print the JSON report
        try:
            print(json.dumps(json.loads(report), indent=2))
        except Exception:
            print(report)

        print("\n")
        