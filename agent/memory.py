# agent/memory.py
# Phase 8.4: SQLite replaced with Firestore.
# Every function signature and return value is IDENTICAL to the Phase 5 version.
# The agent, triage agent, and pipeline import from this file unchanged.
#
# What changed:     SQLite file operations → Firestore document operations
# What didn't:      Function names, parameters, return types, ShortTermMemory class

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from datetime import datetime, timezone
from dotenv import load_dotenv
from google.cloud import firestore

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE SETUP
# Firestore is a managed NoSQL document database on GCP.
# No file path needed — the client connects over HTTP automatically.
# Locally it uses GOOGLE_APPLICATION_CREDENTIALS.
# On Cloud Run it uses the attached service account (ticket-resolver-sa).
# ─────────────────────────────────────────────────────────────────────────────

# firestore.Client() creates a connection to your GCP Firestore database.
# project= tells it which GCP project to connect to.
db = firestore.Client(project=os.getenv("VERTEX_PROJECT_ID", "ticket-resolver-arnab"))

# COLLECTION is the Firestore equivalent of a SQL table name.
# All investigation documents live inside this collection.
COLLECTION = "investigations"

# No initialise_db() needed — Firestore creates collections and documents
# automatically when you first write to them. No schema to define upfront.


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
    Persist a completed investigation to Firestore.
    Called at the end of every successful run_agent() call.

    SQLite equivalent:
        INSERT INTO investigations (...) VALUES (...)

    Firestore equivalent:
        db.collection("investigations").document(ticket_id).set({...})

    Using ticket_id as the document ID means saving the same ticket twice
    overwrites the first — same behaviour as SQLite's INSERT OR REPLACE.
    """
    try:
        # db.collection() selects the collection — like "FROM investigations"
        # .document(ticket_id) selects the specific document by ID
        #   — ticket_id is the primary key, e.g. "TKT-0001"
        # .set() writes all fields — creates if not exists, overwrites if exists
        doc_ref = db.collection(COLLECTION).document(ticket_id)
        doc_ref.set({
            "ticket_id":       ticket_id,
            "service":         service,
            "priority":        priority,
            "category":        category,
            "root_cause":      root_cause,
            "resolution_type": resolution_type,
            "summary":         summary,
            # Store timestamp as ISO string — same format as the SQLite version
            # so get_service_history() can slice [:10] to get the date unchanged
            "created_at":      datetime.now(timezone.utc).isoformat(),
        })

        print(f"  💾 Saved investigation for {service} to long-term memory")

    except Exception as e:
        # Don't crash the agent if memory save fails — just log it
        print(f"  ⚠️  Failed to save investigation for {ticket_id}: {e}")


def get_service_history(service: str, limit: int = 5) -> str:
    """
    Retrieve the most recent past investigations for a service.
    Returns formatted text — identical format to the SQLite version.

    SQLite equivalent:
        SELECT ... FROM investigations
        WHERE service = ?
        ORDER BY created_at DESC
        LIMIT ?

    Firestore equivalent:
        db.collection("investigations")
          .where("service", "==", service)
          .order_by("created_at", direction=DESCENDING)
          .limit(limit)
          .stream()

    Args:
        service: service name to look up e.g. "auth-service"
        limit:   how many past investigations to return
    """
    try:
        # Chain query operations — each returns a new query object
        # .where()    = filter (like SQL WHERE)
        # .order_by() = sort   (like SQL ORDER BY)
        # .limit()    = cap    (like SQL LIMIT)
        # .stream()   = execute and return iterator of DocumentSnapshot objects
        # NEW — uses filter= keyword argument
        docs = (
            db.collection(COLLECTION)
            .where(filter=firestore.FieldFilter("service", "==", service))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )

        # Convert DocumentSnapshot objects to plain dicts
        # .to_dict() gives us the same field names we wrote in save_investigation()
        rows = [doc.to_dict() for doc in docs]

    except Exception as e:
        print(f"  ⚠️  Failed to retrieve history for {service}: {e}")
        return f"No previous investigations found for '{service}'."

    if not rows:
        return f"No previous investigations found for '{service}'."

    # ── Format output — identical to SQLite version ───────────────────────────
    # The agent reads this string directly, so the format must not change
    lines = [f"=== Past Investigations for '{service}' ===\n"]

    for row in rows:
        lines.append(
            f"Ticket:     {row['ticket_id']}\n"
            f"Date:       {row['created_at'][:10]}\n"
            # [:10] slices "2025-01-15T10:30:00+00:00" → "2025-01-15"
            # Works because we stored created_at as ISO string, same as before
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

    SQLite equivalent:
        SELECT DISTINCT service FROM investigations ORDER BY service

    Firestore note: Firestore has no DISTINCT — we fetch all documents
    and deduplicate in Python. Fine for a small dataset like this.
    """
    try:
        docs = db.collection(COLLECTION).stream()
        # Use a set to deduplicate service names — same as SQL DISTINCT
        services = set()
        for doc in docs:
            data = doc.to_dict()
            if data.get("service"):
                services.add(data["service"])

        # Return sorted list — same as SQLite's ORDER BY service
        return sorted(list(services))

    except Exception as e:
        print(f"  ⚠️  Failed to retrieve service names: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# SHORT-TERM MEMORY
# Unchanged from Phase 5 — this is pure in-memory Python, no database involved.
# Tracks key findings during the CURRENT investigation only.
# Resets every time a new investigation starts.
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
            lines.append(f"{i}. {finding}")
        return "\n".join(lines)

    def clear(self):
        """Reset findings — called when starting a new investigation."""
        self.findings = []


# ─────────────────────────────────────────────────────────────────────────────
# NOTE: No initialise_db() call here — Firestore needs no schema setup.
# Collections and documents are created automatically on first write.
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# TEST — run this file directly to verify Firestore connectivity
# python agent/memory.py
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing Firestore memory module...\n")

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

    # Test retrieving history — output must look identical to Phase 5
    print("\n" + get_service_history("auth-service"))
    print("\n" + get_service_history("payment-service"))
    print("\n" + get_service_history("search-service"))  # nothing here yet

    # Test short-term memory — completely unchanged
    print("\n--- Short-term memory test ---")
    stm = ShortTermMemory("TKT-TEST", "auth-service")
    stm.add_finding("DB connections at 100/100 — maxed out")
    stm.add_finding("Error rate spiked to 94% at 02:03")
    stm.add_finding("v2.3.1 deployed at 01:47 — 16 minutes before incident")
    print(stm.get_summary())

    # Show all services in memory
    print(f"\nServices in long-term memory: {get_all_service_names()}")