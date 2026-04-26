import json
import os
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
from rich import print
from rich.progress import track

load_dotenv()

os.environ["ANONYMIZED_TELEMETRY"] = "False"

CHROMA_PATH = os.getenv("CHROMA_PATH")
INCIDENTS_FILE = Path(__file__).parent / "past_incidents.json"

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

def load_incidents() -> list[dict]:
    with open(INCIDENTS_FILE) as f:
        return json.load(f)

def incident_to_document(incident: dict) -> str:
    """
    What you embed determines what you retrieve.
    We combine all meaningful fields so similarity search
    works on symptoms, root cause, and resolution equally.
    """
    steps = "\n".join(f"  - {s}" for s in incident["investigation_steps"])
    res_steps = "\n".join(f"  - {s}" for s in incident["resolution_steps"])

    return f"""
Incident: {incident['title']}
Service: {incident['service']}
Severity: {incident['severity']}
Symptoms: {incident['symptoms']}
Root Cause: {incident['root_cause']}
Investigation Steps:
{steps}
Resolution Steps:
{res_steps}
Tags: {', '.join(incident['tags'])}
""".strip()

def seed():
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Fresh start each time you re-seed
    try:
        client.delete_collection("past_incidents")
        print("[yellow]Deleted existing collection — re-seeding[/yellow]")
    except Exception:
        pass

    collection = client.create_collection(
        name="past_incidents",
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"}
    )

    incidents = load_incidents()

    documents, ids, metadatas = [], [], []

    for incident in track(incidents, description="Embedding incidents..."):
        documents.append(incident_to_document(incident))
        ids.append(incident["id"])
        metadatas.append({
            "service":          incident["service"],
            "severity":         incident["severity"],
            "resolution_type":  incident["resolution_type"],
            "time_to_resolve":  incident["time_to_resolve_minutes"],
            "tags":             ", ".join(incident["tags"])
        })

    collection.add(documents=documents, ids=ids, metadatas=metadatas)

    print(f"\n[green]✓ Seeded {len(documents)} incidents into ChromaDB[/green]")
    print(f"[blue]  Stored at: {CHROMA_PATH}[/blue]")

if __name__ == "__main__":
    seed()