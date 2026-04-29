# agent/memory.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE SETUP
# SQLite is a file-based database — no server needed.
# The entire DB lives in one file: memory.db in your project root.
# In Phase 8 this gets swapped to Firestore on GCP — same logic, different backend.
# ─────────────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "memory.db"
# Path(__file__) = agent/memory.py
# .parent       = agent/
# .parent       = ticket-resolver/   ← project root
# / "memory.db" = ticket-resolver/memory.db


def get_connection() -> sqlite3.Connection:
    """
    Open a connection to the SQLite database.
    Creates the file automatically if it doesn't exist.
    """
    conn = sqlite3.connect(str(DB_PATH))

    # This makes rows behave like dictionaries
    # so you can write row["service"] instead of row[0]
    conn.row_factory = sqlite3.Row

    return conn


def initialise_db():
    """
    Create the tables if they don't already exist.
    Safe to call every time the app starts — IF NOT EXISTS prevents duplicates.
    """
    conn = get_connection()

    # cursor is the object you use to run SQL commands
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investigations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id       TEXT NOT NULL,
            service         TEXT NOT NULL,
            priority        TEXT,
            category        TEXT,
            root_cause      TEXT,
            resolution_type TEXT,
            summary         TEXT,
            created_at      TEXT NOT NULL
        )
    """)
    # INTEGER PRIMARY KEY AUTOINCREMENT = auto-incrementing unique row ID
    # TEXT NOT NULL = required string field
    # TEXT = optional string field

    conn.commit()   # save the changes
    conn.close()    # release the connection


# ─────────────────────────────────────────────────────────────────────────────
# LONG-TERM MEMORY
# Save and retrieve past investigations per service
# ─────────────────────────────────────────────────────────────────────────────

def save_investigation(
    ticket_id:       str,
    service:         str,
    priority:        str,
    category:        str,
    root_cause:      str,
    resolution_type: str,
    summary:         str
):
    """
    Persist a completed investigation to the database.
    Called at the end of every successful run_agent() call.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO investigations
            (ticket_id, service, priority, category,
             root_cause, resolution_type, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        ticket_id,
        service,
        priority,
        category,
        root_cause,
        resolution_type,
        summary,
        datetime.now(timezone.utc).isoformat()
        # Always store timestamps in UTC
    ))
    # The ? placeholders prevent SQL injection attacks
    # Values are passed as a tuple as the second argument

    conn.commit()
    conn.close()

    print(f"  💾 Saved investigation for {service} to long-term memory")


def get_service_history(service: str, limit: int = 5) -> str:
    """
    Retrieve the most recent past investigations for a service.
    Returns formatted text the agent can read at the start of investigation.

    Args:
        service: service name to look up
        limit:   how many past investigations to return
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ticket_id, priority, category, root_cause, summary, created_at
        FROM investigations
        WHERE service = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (service, limit))
    # ORDER BY created_at DESC = most recent first
    # LIMIT ? = only return this many rows

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"No previous investigations found for '{service}'."

    lines = [f"=== Past Investigations for '{service}' ===\n"]

    for row in rows:
        # row["field"] works because we set conn.row_factory = sqlite3.Row
        lines.append(
            f"Ticket:     {row['ticket_id']}\n"
            f"Date:       {row['created_at'][:10]}\n"
            # [:10] slices the ISO timestamp to just the date: "2025-01-15"
            f"Priority:   {row['priority']}\n"
            f"Category:   {row['category']}\n"
            f"Root Cause: {row['root_cause']}\n"
            f"Summary:    {row['summary']}\n"
            f"{'-' * 40}"
        )

    return "\n".join(lines)


def get_all_service_names() -> list[str]:
    """
    Return all service names that have investigation history.
    Useful for debugging — lets you see what's in memory.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT service FROM investigations ORDER BY service")
    rows = cursor.fetchall()
    conn.close()

    # List comprehension to extract service names from Row objects
    return [row["service"] for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# SHORT-TERM MEMORY
# Tracks key findings during the CURRENT investigation only.
# Lives in memory (a Python dict) — not saved to disk.
# Resets every time a new investigation starts.
# Solves the context window problem — instead of keeping full tool outputs
# in the messages list, we maintain a compact running summary here.
# ─────────────────────────────────────────────────────────────────────────────

class ShortTermMemory:
    """
    Holds key findings for the current investigation.
    Gets passed to the LLM as a compact summary instead of
    keeping all raw tool outputs in the messages list.
    """

    def __init__(self, ticket_id: str, service: str):
        self.ticket_id = ticket_id
        self.service   = service
        self.findings  = []
        # findings is a list of strings, one per key observation
        # Example: ["DB connections at 100/100", "Error rate 94%", "v2.3.1 deployed at 01:47"]

    def add_finding(self, finding: str):
        """
        Add one key finding from a tool result.
        Call this after each tool execution with the most important observation.
        """
        self.findings.append(finding)
        print(f"  📝 Finding noted: {finding}")

    def get_summary(self) -> str:
        """
        Return all findings as a compact string.
        This goes into the messages list instead of full tool outputs.
        """
        if not self.findings:
            return "No findings yet."

        lines = [f"=== Investigation findings so far for {self.service} ==="]
        for i, finding in enumerate(self.findings, start=1):
            # enumerate(list, start=1) gives (1, item), (2, item)...
            # so i starts at 1 instead of 0
            lines.append(f"{i}. {finding}")
        return "\n".join(lines)

    def clear(self):
        """Reset findings — called when starting a new investigation."""
        self.findings = []


# ─────────────────────────────────────────────────────────────────────────────
# INITIALISE ON IMPORT
# When any file imports from memory.py, the DB is created if it doesn't exist
# ─────────────────────────────────────────────────────────────────────────────

initialise_db()


# ─────────────────────────────────────────────────────────────────────────────
# TEST — run this file directly
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing memory module...\n")

    # Test saving investigations
    save_investigation(
        ticket_id="TKT-0001",
        service="auth-service",
        priority="critical",
        category="database",
        root_cause="PostgreSQL connection pool exhausted due to connection leak in v2.3.1",
        resolution_type="rollback",
        summary="Rolled back auth-service to v2.3.0. Connections normalized in 4 minutes."
    )

    save_investigation(
        ticket_id="TKT-0002",
        service="auth-service",
        priority="high",
        category="deployment",
        root_cause="JWT secret rotated in auth-service but not propagated to dependent services",
        resolution_type="config_change",
        summary="Updated JWT secret across all dependent services. 401 errors stopped within 2 minutes."
    )

    save_investigation(
        ticket_id="TKT-0003",
        service="payment-service",
        priority="critical",
        category="cache",
        root_cause="Redis cache flushed during maintenance causing cache miss storm",
        resolution_type="cache_warm",
        summary="Ran cache warm-up script. Hit rate recovered to 90%+ within 15 minutes."
    )

    # Test retrieving history
    print("\n" + get_service_history("auth-service"))
    print("\n" + get_service_history("payment-service"))
    print("\n" + get_service_history("search-service"))  # nothing here yet

    # Test short-term memory
    print("\n--- Short-term memory test ---")
    stm = ShortTermMemory("TKT-TEST", "auth-service")
    stm.add_finding("DB connections at 100/100 — maxed out")
    stm.add_finding("Error rate spiked to 94% at 02:03")
    stm.add_finding("v2.3.1 deployed at 01:47 — 16 minutes before incident")
    print(stm.get_summary())

    # Show all services in memory
    print(f"\nServices in long-term memory: {get_all_service_names()}")
    