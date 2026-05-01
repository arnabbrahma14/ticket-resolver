# tools/test_all_tools.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from mcp_server.tools.fetch_logs        import fetch_logs
from mcp_server.tools.check_metrics     import check_metrics
from mcp_server.tools.search_incidents  import search_past_incidents
from mcp_server.tools.generate_report   import generate_report
from rich import print

print("\n[bold green]═══ Testing all 4 tools ═══[/bold green]\n")

print("[bold]1. fetch_logs[/bold]")
result = fetch_logs("auth-service", severity="ERROR")
print(result[:300], "...\n")   # print first 300 chars so output isn't too long

print("[bold]2. check_metrics[/bold]")
result = check_metrics("auth-service")
print(result, "\n")

print("[bold]3. search_past_incidents[/bold]")
result = search_past_incidents("database connection pool exhausted login failing")
print(result[:400], "...\n")

print("[bold]4. generate_report[/bold]")
result = generate_report(
    ticket_id="TEST-001", service="auth-service",
    priority="critical", category="database",
    root_cause="Connection pool exhausted",
    confidence="high",
    supporting_evidence=["connections at 100/100", "errors after v2.3.1 deploy"],
    resolution_steps=[{"step": 1, "action": "Check connections",
                        "command": "SELECT count(*) FROM pg_stat_activity",
                        "expected_result": "Should show 100 connections"}],
    similar_incidents=[{"id": "INC-001", "similarity": "87%",
                         "resolution_summary": "Rolled back deployment"}],
)
print(result[:400], "...\n")

print("[bold green]✓ All 4 tools working[/bold green]")
