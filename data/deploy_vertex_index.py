# data/deploy_vertex_index.py
# Deploys your index to an endpoint so it can be queried.
# This starts the billing clock (~$0.094/hour for e2-standard-2).
# Run once.

import os
from google.cloud import aiplatform
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID         = "ticket-resolver-arnab"
LOCATION           = "us-central1"
INDEX_RESOURCE_NAME = "projects/910644517708/locations/us-central1/indexes/5212839602867404800"

aiplatform.init(project=PROJECT_ID, location=LOCATION)

# Step A: Create the endpoint (this is just a named container, no cost yet)
print("Creating endpoint...")
endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
    display_name="ticket-resolver-endpoint",
    public_endpoint_enabled=True,   # makes it accessible from Cloud Run
)
print(f"Endpoint created: {endpoint.resource_name}")

# Step B: Deploy the index TO the endpoint (this starts the VM and billing)
print("\nDeploying index to endpoint... this takes 5–10 minutes.")
endpoint.deploy_index(
    index=aiplatform.MatchingEngineIndex(index_name=INDEX_RESOURCE_NAME),
    deployed_index_id="incidents_index",
    machine_type="e2-standard-16",   # ← was e2-standard-2
    min_replica_count=1,
    max_replica_count=1,
)

print(f"\nDeployment complete!")
print(f"Endpoint resource name: {endpoint.resource_name}")
print(f"Public endpoint domain: {endpoint.public_endpoint_domain_name}")
print(f"\nSave both values — update your .env with:")
print(f"VERTEX_INDEX_ENDPOINT = \"{endpoint.resource_name}\"")
print(f"VERTEX_DEPLOYED_INDEX_ID = \"incidents_index\"")
