# tools/generate_report.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from datetime import datetime, timezone
import json


def generate_report(
    ticket_id:          str,
    service:            str,
    priority:           str,
    category:           str,
    root_cause:         str,
    confidence:         str,
    resolution_summary: str,
    evidence_summary:   str
) -> str:
    """
    Structure the agent's findings into a final resolution report.
    Accepts simplified inputs to avoid Groq/LLaMA tool schema bugs.
    The resolution_summary and evidence_summary are plain text from the LLM
    rather than nested arrays — much more reliable with LLaMA.
    """

    report = {
        "ticket_id":    ticket_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),

        "triage": {
            "priority":         priority,
            "category":         category,
            "affected_service": service
        },

        "diagnosis": {
            "most_likely_root_cause": root_cause,
            "confidence":             confidence,
            "supporting_evidence":    evidence_summary
        },

        "resolution": resolution_summary,

        "generated_by": "AI Investigation Agent — human review required before acting"
    }

    return json.dumps(report, indent=2)


if __name__ == "__main__":
    test = generate_report(
        ticket_id="TKT-4821",
        service="auth-service",
        priority="critical",
        category="database",
        root_cause="PostgreSQL connection pool exhausted due to connection leak in v2.3.1",
        confidence="high",
        resolution_summary=(
            "Step 1: Confirm connections maxed — run: SELECT count(*), state FROM pg_stat_activity GROUP BY state\n"
            "Step 2: Check deployment diff — run: git diff v2.3.0..v2.3.1\n"
            "Step 3: Rollback if leak confirmed — run: kubectl rollout undo deployment/auth-service\n"
            "Step 4: Monitor recovery — connections should drop below 20 within 5 minutes"
        ),
        evidence_summary=(
            "Logs show 'too many connections' errors starting at 02:03. "
            "DB metrics show connections at 100/100. "
            "v2.3.1 deployed at 01:47 — 16 minutes before incident. "
            "Past incident INC-001 matches at 87% similarity."
        )
    )
    print(test)
    