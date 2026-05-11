# main.py
# Phase 8.5: Async FastAPI gateway with Cloud Tasks background job queue.
#
# Three endpoints:
#   POST /ticket            → client-facing: accepts ticket, enqueues job, returns task_id
#   GET  /result/{task_id}  → client-facing: polls Firestore for job status + report
#   POST /worker/process    → internal: Cloud Tasks calls this to trigger the agent
#   GET  /health            → Cloud Run health check

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import json
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from google.cloud import tasks_v2, firestore

from worker import create_job, run_job

load_dotenv()

# ── Startup validation ────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY environment variable is not set.")

PROJECT_ID        = os.getenv("VERTEX_PROJECT_ID", "ticket-resolver-arnab")
QUEUE_NAME        = os.getenv("CLOUD_TASKS_QUEUE", "ticket-investigation-queue")
QUEUE_LOCATION    = os.getenv("CLOUD_TASKS_LOCATION", "us-central1")
WORKER_URL        = os.getenv("WORKER_URL", "http://localhost:8080/worker/process")

# ── Clients ───────────────────────────────────────────────────────────────────
tasks_client = tasks_v2.CloudTasksClient()
db           = firestore.Client(project=PROJECT_ID)

# Full resource path for the queue — Cloud Tasks API requires this format
QUEUE_PATH = tasks_client.queue_path(PROJECT_ID, QUEUE_LOCATION, QUEUE_NAME)

app = FastAPI(
    title="Support Ticket Resolution System",
    description="Async agentic AI system for investigating support tickets.",
    version="2.0.0",
)

# ── Request / Response models ─────────────────────────────────────────────────

class TicketRequest(BaseModel):
    ticket_id:   str    # e.g. "TKT-4821"
    ticket_text: str    # raw problem description from the user

class SubmitResponse(BaseModel):
    task_id:  str       # UUID to poll with GET /result/{task_id}
    status:   str       # always "pending" at this point
    message:  str       # human-readable confirmation

class WorkerRequest(BaseModel):
    task_id:     str
    ticket_id:   str
    ticket_text: str

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Cloud Run health check — must return 200 for container to receive traffic."""
    return {"status": "ok"}


@app.post("/ticket", response_model=SubmitResponse)
async def submit_ticket(request: TicketRequest):
    """
    Client-facing endpoint. Accepts a ticket and returns immediately.

    What happens here (all fast, under 1 second):
      1. Generate a unique task_id (UUID)
      2. Write a 'pending' document to Firestore
      3. Enqueue a Cloud Tasks job pointing at POST /worker/process
      4. Return the task_id to the client

    The client uses task_id to poll GET /result/{task_id}.
    The actual agent investigation happens asynchronously in the background.
    """
    # Step 1: Generate a unique ID for this job
    # uuid4() generates a random UUID like "550e8400-e29b-41d4-a716-446655440000"
    task_id = str(uuid.uuid4())

    try:
        # Step 2: Create the Firestore job document with status='pending'
        # This must happen BEFORE enqueuing the task, because the worker
        # might start before the client even calls GET /result
        create_job(
            task_id=task_id,
            ticket_id=request.ticket_id,
            ticket_text=request.ticket_text,
        )

        # Step 3: Build the Cloud Tasks payload
        # Cloud Tasks will POST this JSON body to WORKER_URL
        payload = json.dumps({
            "task_id":     task_id,
            "ticket_id":   request.ticket_id,
            "ticket_text": request.ticket_text,
        }).encode()  # Cloud Tasks requires bytes, not str

        # The task object tells Cloud Tasks:
        # - WHERE to send the HTTP request (WORKER_URL)
        # - WHAT to send (the JSON payload above)
        # - WHAT content type to use
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url":         WORKER_URL,
                "headers":     {"Content-Type": "application/json"},
                "body":        payload,
            }
        }

        # Step 4: Enqueue the task — this returns immediately
        # Cloud Tasks handles delivery, retries, and backoff automatically
        tasks_client.create_task(request={"parent": QUEUE_PATH, "task": task})

        print(f"[Gateway] Ticket {request.ticket_id} enqueued as task {task_id}")

        return SubmitResponse(
            task_id=task_id,
            status="pending",
            message=f"Ticket accepted. Poll GET /result/{task_id} for the report.",
        )

    except Exception as e:
        print(f"[Gateway] ERROR enqueuing ticket {request.ticket_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue ticket: {str(e)}")


@app.get("/result/{task_id}")
async def get_result(task_id: str):
    """
    Client-facing polling endpoint. Returns the current job status.

    Possible responses:
      status='pending'    → job is queued, not started yet
      status='processing' → agent is currently running
      status='done'       → report is ready (check the 'report' field)
      status='failed'     → agent crashed (check the 'error' field)
      404                 → task_id not found
    """
    doc = db.collection("ticket_jobs").document(task_id).get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    data = doc.to_dict()

    # Convert Firestore timestamps to strings for JSON serialisation
    for field in ("created_at", "completed_at"):
        if data.get(field):
            data[field] = str(data[field])

    return data


@app.post("/worker/process")
async def worker_process(request: Request):
    """
    Internal endpoint. Only Cloud Tasks should call this.

    Cloud Tasks POSTs the ticket details here when it's ready to process the job.
    This endpoint runs the full agent pipeline — it takes 30–60 seconds.
    Cloud Tasks waits for a 200 response. If it gets anything else (or times out),
    it will retry the task automatically with exponential backoff.

    Note: In production, protect this endpoint so only Cloud Tasks can call it.
    We'll add OIDC token verification in Phase 8.6.
    """
    try:
        # Parse the JSON body Cloud Tasks sent
        body = await request.json()
        task_id     = body["task_id"]
        ticket_id   = body["ticket_id"]
        ticket_text = body["ticket_text"]

    except Exception as e:
        # Return 400 so Cloud Tasks does NOT retry (bad payload won't fix itself)
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    try:
        # Run the agent pipeline — this is the slow part
        # run_job() handles updating Firestore status throughout
        await run_job(
            task_id=task_id,
            ticket_id=ticket_id,
            ticket_text=ticket_text,
        )
        # Return 200 so Cloud Tasks knows the job succeeded
        return {"status": "ok", "task_id": task_id}

    except Exception as e:
        # Return 500 so Cloud Tasks retries this task
        raise HTTPException(status_code=500, detail=str(e))
    