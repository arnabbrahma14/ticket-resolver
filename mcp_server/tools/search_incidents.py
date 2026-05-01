import os
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

load_dotenv()

os.environ["ANONYMIZED_TELEMETRY"] = "False"

CHROMA_PATH = os.getenv("CHROMA_PATH")

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_collection(
        name="past_incidents",
        embedding_function=embedding_fn
    )

def search_past_incidents(
    query: str,
    top_k: int = 3,
    service_filter: str = None
) -> str:
    """
    Search past resolved incidents relevant to the current query.
    Returns formatted text ready for the LLM to reason over.
    """
    collection = get_collection()

    where_filter = {"service": service_filter} if service_filter else None

    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    if not results["documents"][0]:
        return "No similar past incidents found."

    lines = ["=== Similar Past Incidents ===\n"]

    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        similarity = round((1 - dist) * 100, 1)
        lines.append(
            f"[{meta['service']}] — Similarity: {similarity}% "
            f"| Severity: {meta['severity']} "
            f"| Resolved in: {meta['time_to_resolve']} mins\n"
            f"{doc}\n"
            f"{'-' * 60}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    # Test queries — run this to verify retrieval is working
    test_queries = [
        "database connection timeout errors login failing",
        "service running out of memory crashing repeatedly",
        "payment processing slow users cannot checkout",
        "search returning wrong or outdated results",
        "ssl certificate error https not working"
    ]

    for query in test_queries:
        print(f"\n[bold cyan]Query:[/bold cyan] {query}")
        print(search_past_incidents(query, top_k=2))