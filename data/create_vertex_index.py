import os
from google.cloud import aiplatform
from google.cloud.aiplatform.compat.types import matching_engine_index as aip_index
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID   = "ticket-resolver-arnab"
LOCATION     = "us-central1"
BUCKET_URI   = "gs://ticket-resolver-arnab-vectors"
DISPLAY_NAME = "ticket-resolver-incidents"

aiplatform.init(project=PROJECT_ID, location=LOCATION)

print("Creating index... this takes 5–15 minutes. Do not close this terminal.")

# The API now requires algorithmConfig to be explicitly provided.
# TreeAhConfig is the algorithm behind Vertex AI Vector Search (ScaNN).
# We pass it inside metadata along with the other index settings.
# data/create_vertex_index.py — change dimensions from 768 to 3072

index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
    display_name=DISPLAY_NAME,
    contents_delta_uri=BUCKET_URI,
    dimensions=3072,              # ← changed from 768
    approximate_neighbors_count=10,
    distance_measure_type="DOT_PRODUCT_DISTANCE",
    leaf_node_embedding_count=500,
    leaf_nodes_to_search_percent=7,
)

print(f"\nIndex created!")
print(f"Resource name: {index.resource_name}")
print(f"\nSave this value — you need it for deploy_vertex_index.py:")
print(f"INDEX_RESOURCE_NAME = \"{index.resource_name}\"")