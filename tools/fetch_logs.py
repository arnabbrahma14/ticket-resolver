# tools/fetch_logs.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# MOCK DATA
# This is a dictionary where:
#   - the KEY is a service name (e.g. "auth-service")
#   - the VALUE is a list of fake log entries for that service
#
# In Phase 6, we replace this entire dictionary with a real call
# to a logging system (like Elasticsearch or Cloud Logging).
# But for now, fake data lets us test the agent without any infrastructure.
# ─────────────────────────────────────────────────────────────────────────────

MOCK_LOGS = {
    "auth-service": [
        {"timestamp": "2025-01-15T02:03:12Z", "severity": "ERROR", "message": "too many connections for role 'app_user'"},
        {"timestamp": "2025-01-15T02:03:15Z", "severity": "ERROR", "message": "connection pool exhausted, rejecting request"},
        {"timestamp": "2025-01-15T02:03:18Z", "severity": "ERROR", "message": "HTTP 500 on POST /api/login — upstream DB error"},
        {"timestamp": "2025-01-15T01:47:02Z", "severity": "INFO",  "message": "Deployment auth-service v2.3.1 started"},
        {"timestamp": "2025-01-15T01:47:58Z", "severity": "INFO",  "message": "Deployment auth-service v2.3.1 completed successfully"},
        {"timestamp": "2025-01-15T02:01:44Z", "severity": "WARN",  "message": "DB connection count at 87/100 — approaching limit"},
        {"timestamp": "2025-01-15T02:02:51Z", "severity": "WARN",  "message": "DB connection count at 98/100 — critical"},
    ],
    "payment-service": [
        {"timestamp": "2025-01-15T03:01:05Z", "severity": "WARN",  "message": "Redis cache hit rate dropped to 12% — unusually low"},
        {"timestamp": "2025-01-15T03:01:09Z", "severity": "ERROR", "message": "Checkout request took 9842ms — timeout threshold is 5000ms"},
        {"timestamp": "2025-01-15T03:01:12Z", "severity": "ERROR", "message": "Checkout request took 11203ms — user session lost"},
        {"timestamp": "2025-01-15T03:00:01Z", "severity": "INFO",  "message": "Scheduled maintenance job started: flush_cache"},
        {"timestamp": "2025-01-15T03:00:03Z", "severity": "INFO",  "message": "Scheduled maintenance job completed: flush_cache — 94832 keys removed"},
    ],
    "notification-service": [
        {"timestamp": "2025-01-15T08:21:03Z", "severity": "ERROR", "message": "OOMKilled — container exceeded memory limit of 512Mi"},
        {"timestamp": "2025-01-15T08:21:04Z", "severity": "INFO",  "message": "Container restarting (restart count: 7)"},
        {"timestamp": "2025-01-15T08:03:17Z", "severity": "WARN",  "message": "Memory usage at 89% — 455Mi of 512Mi"},
        {"timestamp": "2025-01-15T07:44:22Z", "severity": "WARN",  "message": "Memory usage at 74% — 379Mi of 512Mi"},
        {"timestamp": "2025-01-15T07:21:09Z", "severity": "INFO",  "message": "Container started fresh — memory at 12%"},
        {"timestamp": "2025-01-15T08:19:44Z", "severity": "DEBUG", "message": "template_cache size: 8847 entries — no eviction policy set"},
    ],
    "api-gateway": [
        {"timestamp": "2025-01-15T11:05:33Z", "severity": "ERROR", "message": "Upstream timeout: inventory-service did not respond within 30s"},
        {"timestamp": "2025-01-15T11:05:33Z", "severity": "ERROR", "message": "Returning 503 to client — upstream unavailable"},
        {"timestamp": "2025-01-15T11:05:34Z", "severity": "ERROR", "message": "Circuit breaker OPEN for inventory-service after 10 consecutive failures"},
    ],
    "search-service": [
        {"timestamp": "2025-01-15T06:14:22Z", "severity": "ERROR", "message": "es-sync-worker OOMKilled — memory limit 256Mi exceeded"},
        {"timestamp": "2025-01-15T06:14:23Z", "severity": "WARN",  "message": "Product update queue depth: 182447 messages pending"},
        {"timestamp": "2025-01-15T06:14:50Z", "severity": "ERROR", "message": "es-sync-worker in CrashLoopBackOff — restart count 4"},
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# THE ACTUAL TOOL FUNCTION
# This is what the agent will call.
# ─────────────────────────────────────────────────────────────────────────────

def fetch_logs(
    service: str,
    severity: str = "ALL",
    limit: int = 20
) -> str:
    """
    Fetch recent log entries for a given service.

    Args:
        service  : name of the service (e.g. "auth-service")
        severity : filter by level — "ERROR", "WARN", "INFO", or "ALL"
        limit    : max number of log lines to return
    """

    # Step 1: look up mock logs for this service
    # .lower() makes the comparison case-insensitive
    # so "Auth-Service" and "auth-service" both work
    logs = MOCK_LOGS.get(service.lower())

    # Step 2: if we have no logs for this service, say so clearly
    if not logs:
        return (
            f"No logs found for service '{service}'.\n"
            f"Available services: {', '.join(MOCK_LOGS.keys())}"
        )

    # Step 3: filter by severity if the caller asked for a specific level
    # severity.upper() makes "error" == "ERROR" == "Error"
    if severity.upper() != "ALL":
        logs = [
            entry for entry in logs          # loop through all log entries
            if entry["severity"] == severity.upper()   # keep only matching ones
        ]

    # Step 4: apply the limit — don't return hundreds of lines to the LLM
    logs = logs[:limit]

    # Step 5: if filtering removed everything, say so
    if not logs:
        return f"No {severity.upper()} logs found for service '{service}'."

    # Step 6: build a nicely formatted string the LLM can read
    # We're not returning a Python list — we return plain text
    # because that's what gets pasted into the LLM's context window
    lines = [f"=== Logs for '{service}' (severity={severity.upper()}) ===\n"]

    for entry in logs:
        # Each line looks like: [2025-01-15T02:03:12Z] ERROR  too many connections...
        lines.append(
            f"[{entry['timestamp']}] {entry['severity']:<6} {entry['message']}"
        )
        # Note: {entry['severity']:<6} left-aligns severity in a 6-char column
        # so ERROR, WARN, INFO all line up neatly

    return "\n".join(lines)   # join all lines into one string with newlines between


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST — run this file directly to verify it works
# python tools/fetch_logs.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rich import print

    print("\n[bold cyan]Test 1: All logs for auth-service[/bold cyan]")
    print(fetch_logs("auth-service"))

    print("\n[bold cyan]Test 2: Only ERROR logs for auth-service[/bold cyan]")
    print(fetch_logs("auth-service", severity="ERROR"))

    print("\n[bold cyan]Test 3: Unknown service[/bold cyan]")
    print(fetch_logs("unknown-service"))

    print("\n[bold cyan]Test 4: payment-service WARN logs[/bold cyan]")
    print(fetch_logs("payment-service", severity="WARN"))
    