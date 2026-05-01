# tools/check_metrics.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# ─────────────────────────────────────────────────────────────────────────────
# MOCK METRICS DATA
#
# Each service has a snapshot of its current metrics.
# "threshold" = the normal maximum value
# "value"     = what it's currently at
# "unit"      = what the number means
#
# The agent reads these and decides if something looks wrong.
# ─────────────────────────────────────────────────────────────────────────────

MOCK_METRICS = {
    "auth-service": {
        "cpu_percent":          {"value": 67,   "threshold": 80,  "unit": "%",            "status": "normal"},
        "memory_percent":       {"value": 71,   "threshold": 85,  "unit": "%",            "status": "normal"},
        "db_connections_active":{"value": 100,  "threshold": 100, "unit": "connections",  "status": "critical"},
        "db_connections_max":   {"value": 100,  "threshold": 100, "unit": "connections",  "status": "info"},
        "http_error_rate":      {"value": 94.3, "threshold": 1,   "unit": "%",            "status": "critical"},
        "http_p99_latency_ms":  {"value": 8420, "threshold": 500, "unit": "ms",           "status": "critical"},
        "requests_per_second":  {"value": 142,  "threshold": 500, "unit": "req/s",        "status": "normal"},
    },
    "payment-service": {
        "cpu_percent":          {"value": 45,   "threshold": 80,  "unit": "%",            "status": "normal"},
        "memory_percent":       {"value": 52,   "threshold": 85,  "unit": "%",            "status": "normal"},
        "redis_hit_rate":       {"value": 2.1,  "threshold": 80,  "unit": "%",            "status": "critical"},
        "http_p99_latency_ms":  {"value": 10200,"threshold": 500, "unit": "ms",           "status": "critical"},
        "http_error_rate":      {"value": 38.7, "threshold": 1,   "unit": "%",            "status": "critical"},
        "db_query_time_avg_ms": {"value": 180,  "threshold": 200, "unit": "ms",           "status": "normal"},
        "db_connections_active":{"value": 48,   "threshold": 100, "unit": "connections",  "status": "normal"},
    },
    "notification-service": {
        "cpu_percent":          {"value": 12,   "threshold": 80,  "unit": "%",            "status": "normal"},
        "memory_percent":       {"value": 91,   "threshold": 85,  "unit": "%",            "status": "critical"},
        "memory_used_mi":       {"value": 466,  "threshold": 512, "unit": "Mi",           "status": "critical"},
        "restart_count":        {"value": 7,    "threshold": 3,   "unit": "restarts",     "status": "critical"},
        "http_error_rate":      {"value": 0.2,  "threshold": 1,   "unit": "%",            "status": "normal"},
        "http_p99_latency_ms":  {"value": 210,  "threshold": 500, "unit": "ms",           "status": "normal"},
    },
    "api-gateway": {
        "cpu_percent":          {"value": 23,   "threshold": 80,  "unit": "%",            "status": "normal"},
        "memory_percent":       {"value": 41,   "threshold": 85,  "unit": "%",            "status": "normal"},
        "http_error_rate":      {"value": 89.1, "threshold": 1,   "unit": "%",            "status": "critical"},
        "upstream_timeout_rate":{"value": 100,  "threshold": 0,   "unit": "%",            "status": "critical"},
        "http_p99_latency_ms":  {"value": 30400,"threshold": 500, "unit": "ms",           "status": "critical"},
    },
    "search-service": {
        "cpu_percent":          {"value": 8,    "threshold": 80,  "unit": "%",            "status": "normal"},
        "memory_percent":       {"value": 34,   "threshold": 85,  "unit": "%",            "status": "normal"},
        "es_queue_depth":       {"value": 182447,"threshold": 1000,"unit": "messages",    "status": "critical"},
        "es_index_lag_seconds": {"value": 21600,"threshold": 60,  "unit": "seconds",      "status": "critical"},
        "sync_worker_restarts": {"value": 4,    "threshold": 2,   "unit": "restarts",     "status": "critical"},
        "search_p99_latency_ms":{"value": 95,   "threshold": 200, "unit": "ms",           "status": "normal"},
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# STATUS EMOJI — just makes the output easier to scan at a glance
# ─────────────────────────────────────────────────────────────────────────────

STATUS_EMOJI = {
    "critical": "🔴",
    "warning":  "🟡",
    "normal":   "🟢",
    "info":     "⚪",
}

# ─────────────────────────────────────────────────────────────────────────────
# THE ACTUAL TOOL FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def check_metrics(service: str) -> str:
    """
    Return current infrastructure metrics for a service.
    Flags any metric that is above its normal threshold.

    Args:
        service: name of the service (e.g. "auth-service")
    """

    # Step 1: look up metrics for this service
    metrics = MOCK_METRICS.get(service.lower())

    if not metrics:
        return (
            f"No metrics found for service '{service}'.\n"
            f"Available services: {', '.join(MOCK_METRICS.keys())}"
        )

    # Step 2: separate metrics into two groups
    # so the LLM sees the problems first
    critical_metrics = []   # anything flagged critical or warning
    normal_metrics   = []   # everything that's fine

    for metric_name, data in metrics.items():
        if data["status"] in ("critical", "warning"):
            critical_metrics.append((metric_name, data))
        else:
            normal_metrics.append((metric_name, data))

    # Step 3: build the output string
    lines = [f"=== Metrics for '{service}' ===\n"]

    # Show critical ones first — most important for the agent to see
    if critical_metrics:
        lines.append("⚠️  ANOMALIES DETECTED:")
        for name, data in critical_metrics:
            emoji = STATUS_EMOJI.get(data["status"], "❓")
            lines.append(
                f"  {emoji} {name}: {data['value']} {data['unit']} "
                f"(threshold: {data['threshold']} {data['unit']}) "
                f"[{data['status'].upper()}]"
            )

    lines.append("")  # blank line between sections

    # Then show the healthy ones
    if normal_metrics:
        lines.append("✅ NORMAL:")
        for name, data in normal_metrics:
            emoji = STATUS_EMOJI.get(data["status"], "❓")
            lines.append(
                f"  {emoji} {name}: {data['value']} {data['unit']}"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    from rich import print

    print("\n[bold cyan]Test 1: auth-service metrics[/bold cyan]")
    print(check_metrics("auth-service"))

    print("\n[bold cyan]Test 2: notification-service metrics[/bold cyan]")
    print(check_metrics("notification-service"))

    print("\n[bold cyan]Test 3: unknown service[/bold cyan]")
    print(check_metrics("unknown-service"))
    