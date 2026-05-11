# Dockerfile
# Builds a production-ready image of the Support Ticket Resolution System.
#
# Build command (run from project root):
#   docker build -t support-ticket-agent:local .
#
# Run command (inject your real keys):
#   docker run -p 8080:8080 \
#     -e GROQ_API_KEY=your_key_here \
#     support-ticket-agent:local

# ── Stage 1: Base image ──────────────────────────────────────────────────────
# python:3.11-slim = Debian Linux + Python 3.11, no unnecessary extras.
# We pin to 3.11 to match your local dev environment (your venv uses 3.11).
FROM python:3.11-slim

# ── Stage 2: Working directory ───────────────────────────────────────────────
# All subsequent commands run from /app inside the container.
# This is where your code will live.
WORKDIR /app

# ── Stage 3: Install dependencies FIRST (layer cache trick) ──────────────────
# We copy requirements.txt BEFORE copying the rest of the code.
#
# Why? Docker caches each layer. If requirements.txt hasn't changed,
# Docker reuses the cached pip install layer on the next build —
# even if your Python files have changed. This makes rebuilds fast.
#
# If you copy everything first, any code change invalidates the pip cache.
COPY requirements.txt .

# --no-cache-dir: don't save pip's download cache inside the image.
# This keeps the image smaller. We don't need the cache at runtime.
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 4: Copy application code ──────────────────────────────────────────
# Now copy everything else. The dot on the left = current folder on your machine.
# The dot on the right = WORKDIR inside the container (/app).
# .dockerignore controls what gets excluded (secrets, chroma_db, venv, etc.)
COPY . .

# ── Stage 5: Expose the port Cloud Run expects ──────────────────────────────
# Cloud Run routes traffic to port 8080 by convention.
# EXPOSE is documentation — it tells Docker and Cloud Run which port we use.
EXPOSE 8080

# ── Stage 6: Start command ───────────────────────────────────────────────────
# CMD is what runs when the container starts.
#
# uvicorn: the ASGI server that runs FastAPI
# main:app: "in main.py, find the object called app"
# --host 0.0.0.0: listen on ALL network interfaces, not just localhost.
#   Without this, the container accepts no outside traffic.
# --port 8080: match what Cloud Run sends traffic to
# --workers 1: one worker for now. Cloud Run scales by spinning up more
#   container instances, not more workers per container.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]