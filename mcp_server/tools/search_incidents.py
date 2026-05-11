# mcp_server/tools/search_incidents.py
# Phase 8.3: Queries Vertex AI Vector Search instead of local ChromaDB.
# Everything above this layer (MCP server, investigation agent) is unchanged.

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import json
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
from google.cloud import aiplatform

load_dotenv()

# ── Config from environment ──────────────────────────────────────────────────
# These come from .env locally, from Secret Manager in production.
PROJECT_ID          = os.getenv("VERTEX_PROJECT_ID", "ticket-resolver-arnab")
LOCATION            = "us-central1"
INDEX_ENDPOINT_NAME = os.getenv("VERTEX_INDEX_ENDPOINT")
DEPLOYED_INDEX_ID   = os.getenv("VERTEX_DEPLOYED_INDEX_ID", "incidents_index")
EMBEDDING_MODEL     = "models/gemini-embedding-001"

# ── Also load the original incidents JSON so we can return the actual text ───
# Vertex AI only stores and returns IDs + distances — not the original text.
# We use the returned IDs to look up the full incident data from the JSON file.
INCIDENTS_PATH = Path(__file__).parent.parent.parent / "data" / "past_incidents.json"

with open(INCIDENTS_PATH) as f:
    ALL_INCIDENTS = json.load(f)

# ── Clients ──────────────────────────────────────────────────────────────────
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
aiplatform.init(project=PROJECT_ID, location=LOCATION)


def search_past_incidents(query: str, top_k: int = 3, service_filter=None) -> str:
    """
    Searches past incidents using Vertex AI Vector Search (semantic similarity).
    
    Phase 8.3 replacement for the ChromaDB-based version.
    Same function signature — the MCP server and agent don't need to change.

    Args:
        query:          Natural language description of the current problem.
        top_k:          Number of similar incidents to return.
        service_filter: Optional service name to filter results (not used in
                        this implementation — kept for API compatibility).

    Returns:
        A formatted string of the most similar past incidents.
    """

    # ── Step 1: Embed the query ───────────────────────────────────────────────
    # We embed it as RETRIEVAL_QUERY (not RETRIEVAL_DOCUMENT) because we're
    # searching, not indexing. Gemini uses different internal representations
    # for these two task types.
    try:
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=query,
            task_type="RETRIEVAL_QUERY",
        )
        query_embedding = result["embedding"]

    except Exception as e:
        return f"ERROR: Failed to embed query: {e}"

    # ── Step 2: Query the Vertex AI index endpoint ────────────────────────────
    # MatchingEngineIndexEndpoint.find_neighbors() sends the embedding to the
    # deployed index and returns the nearest neighbours as (id, distance) pairs.
    try:
        endpoint = aiplatform.MatchingEngineIndexEndpoint(
            index_endpoint_name=INDEX_ENDPOINT_NAME
        )

        # find_neighbors() is the actual search call.
        # It returns a list of lists — one list per query vector.
        # Since we're sending one query, we take [0].
        response = endpoint.find_neighbors(
            deployed_index_id=DEPLOYED_INDEX_ID,
            queries=[query_embedding],
            num_neighbors=top_k,
        )

        # response[0] is the list of neighbours for our single query
        neighbours = response[0]

    except Exception as e:
        return f"ERROR: Failed to query Vertex AI Vector Search: {e}"

    if not neighbours:
        return "No similar past incidents found."

    # ── Step 3: Look up the full incident text by ID ──────────────────────────
    # Vertex AI returns IDs (e.g. "000042") and distances.
    # We use the ID as an index into ALL_INCIDENTS to get the full text.
    results = []

    for neighbour in neighbours:
        # neighbour.id is the string ID we wrote during embedding ("000042")
        # Convert to int to index into the list
        incident_idx = int(neighbour.id)

        if incident_idx >= len(ALL_INCIDENTS):
            continue

        incident = ALL_INCIDENTS[incident_idx]
        distance = neighbour.distance

        # Format just like the old ChromaDB version so the agent sees
        # exactly the same output format it was already trained on
        results.append(
            f"[Similarity: {distance:.3f}]\n"
            f"Title: {incident.get('title', 'Unknown')}\n"
            f"Service: {incident.get('service', 'Unknown')}\n"
            f"Root cause: {incident.get('root_cause', 'Unknown')}\n"
            f"Resolution: {incident.get('resolution', 'Unknown')}\n"
        )

    if not results:
        return "No matching incidents found after ID lookup."

    return "\n---\n".join(results)
