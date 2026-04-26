# tools/generate_report.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# datetime lets us stamp the report with when it was generated
from datetime import datetime, timezone

# json lets us convert a Python dictionary into a nicely formatted JSON string
import json

# ─────────────────────────────────────────────────────────────────────────────
# THE ACTUAL TOOL FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(
    ticket_id:            str,
    service:              str,
    priority:             str,
    category:             str,
    root_cause:           str,
    confidence:           str,
    supporting_evidence:  list[str],
    resolution_steps:     list[dict],
    similar_incidents:    list[dict],
    fallback_advice:      str = ""
) -> str:
    """
    Structure the agent's investigation findings into a final report.
    This is the ONLY output the agent produces — a human reads this and acts.

    Args:
        ticket_id           : e.g. "TKT-4821"
        service             : which service is affected
        priority            : "critical" / "high" / "medium" / "low"
        category            : "database" / "memory" / "network" / "deployment" etc.
        root_cause          : one sentence describing what the agent thinks went wrong
        confidence          : "high" / "medium" / "low" — how sure the agent is
        supporting_evidence : list of strings — the facts that back the diagnosis
        resolution_steps    : list of dicts, each with "step", "action", "command", "expected_result"
        similar_incidents   : list of dicts with "id", "similarity", "resolution_summary"
        fallback_advice     : what to try if the steps above don't work
    """

    # Build the report as a Python dictionary first
    # This makes it easy to structure, and then we convert to JSON at the end
    report = {

        # ── Header ──────────────────────────────────────────────────────────
        "ticket_id":    ticket_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # .isoformat() gives us a standard timestamp like "2025-01-15T09:32:11+00:00"

        # ── Triage summary ───────────────────────────────────────────────────
        "triage": {
            "priority":         priority,
            "category":         category,
            "affected_service": service,
        },

        # ── Diagnosis ────────────────────────────────────────────────────────
        "diagnosis": {
            "most_likely_root_cause": root_cause,
            "confidence":             confidence,
            # supporting_evidence is a list of strings — each one is a fact
            # the agent found in logs or metrics that points to this root cause
            "supporting_evidence":    supporting_evidence,
        },

        # ── Past incidents the agent found similar to this one ────────────────
        # This comes from the search_past_incidents RAG tool
        "similar_past_incidents": similar_incidents,

        # ── The actual steps a human should follow ────────────────────────────
        # Each step has:
        #   step           : step number (1, 2, 3...)
        #   action         : plain English description of what to do
        #   command        : the exact command to run (if applicable)
        #   expected_result: what you should see if this step worked
        "resolution_steps": resolution_steps,

        # ── What to do if the steps above don't work ─────────────────────────
        "if_steps_dont_work": fallback_advice,
    }

    # Convert the dictionary to a nicely indented JSON string
    # indent=2 means 2 spaces per level — makes it human-readable
    return json.dumps(report, indent=2)


if __name__ == "__main__":
    from rich import print

    # Test with a realistic example — simulating what the agent would pass in
    # after investigating an auth-service DB connection issue

    test_report = generate_report(
        ticket_id   = "TKT-4821",
        service     = "auth-service",
        priority    = "critical",
        category    = "database",

        root_cause  = (
            "PostgreSQL connection pool exhausted due to a connection leak "
            "introduced in auth-service v2.3.1 deployment at 01:47."
        ),
        confidence  = "high",

        supporting_evidence = [
            "Error logs show 'too many connections' errors starting at 02:03 — 16 minutes after v2.3.1 deployment",
            "DB metrics show active connections at 100/100 (hard limit reached)",
            "HTTP error rate spiked to 94.3% coinciding with connection exhaustion",
            "Past incident INC-001 matches: same service, same error, same deployment-before-incident pattern",
        ],

        similar_incidents = [
            {
                "id": "INC-001",
                "similarity": "87%",
                "resolution_summary": (
                    "Rolled back auth-service to previous version. "
                    "DB connections normalized within 4 minutes."
                ),
            }
        ],

        resolution_steps = [
            {
                "step": 1,
                "action": "Confirm DB connection count is maxed",
                "command": "SELECT count(*), state FROM pg_stat_activity GROUP BY state;",
                "expected_result": "Should show ~100 active connections, many in idle or waiting state",
            },
            {
                "step": 2,
                "action": "Check for connection leak in v2.3.1 diff",
                "command": "git diff v2.3.0..v2.3.1 -- auth_service/db/connection.py",
                "expected_result": "Look for missing connection.close() or missing context manager",
            },
            {
                "step": 3,
                "action": "Rollback auth-service to v2.3.0",
                "command": "kubectl rollout undo deployment/auth-service",
                "expected_result": "Connection count should start dropping within 2 minutes",
            },
            {
                "step": 4,
                "action": "Monitor recovery",
                "command": "watch -n 5 'psql -c \"SELECT count(*) FROM pg_stat_activity;\"'",
                "expected_result": "Connections should stabilize below 20 within 5 minutes",
            },
        ],

        fallback_advice = (
            "If rollback does not resolve it, manually terminate idle connections: "
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE state = 'idle' AND query_start < NOW() - INTERVAL '5 minutes';"
        ),
    )

    print(test_report)
    