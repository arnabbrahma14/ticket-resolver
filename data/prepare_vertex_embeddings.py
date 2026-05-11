# data/prepare_vertex_embeddings.py

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import json
import time
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
INCIDENTS_PATH  = Path(__file__).parent / "past_incidents.json"
OUTPUT_PATH = Path(__file__).parent / "incidents_embeddings.json"
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM   = 768

# ── Load incidents ────────────────────────────────────────────────────────────
with open(INCIDENTS_PATH) as f:
    incidents = json.load(f)

print(f"Loaded {len(incidents)} incidents")

# ── Configure Gemini client (new API style) ───────────────────────────────────
# The new google-genai library uses a Client object instead of genai.configure()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Generate embeddings and write JSONL ──────────────────────────────────────
with open(OUTPUT_PATH, "w") as out:
    for i, incident in enumerate(incidents):

        text = f"{incident.get('title', '')} {incident.get('description', '')} {incident.get('resolution', '')}"
        text = text.strip()

        try:
            # New API: client.models.embed_content() instead of genai.embed_content()
            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )

            # New API: result.embeddings is a list of EmbeddingResult objects.
            # Each has a .values attribute which is the list of floats we need.
            embedding = result.embeddings[0].values

            record = {
                "id": str(i).zfill(6),
                "embedding": embedding
            }
            out.write(json.dumps(record) + "\n")

            print(f"  [{i+1}/{len(incidents)}] Embedded incident {i}")
            time.sleep(0.1)

        except Exception as e:
            print(f"  ERROR on incident {i}: {e}")
            continue

print(f"\nDone. Written to {OUTPUT_PATH}")
print(f"Total vectors: {i+1}, dimension: {EMBEDDING_DIM}")