# LoomAI Hub — Multi-user orchestrator for Kubernetes deployments
# Handles CILogon OIDC auth, FABRIC authorization, pod spawning, proxy management

FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/

# Create non-root user
RUN useradd -m -s /bin/bash hub && \
    mkdir -p /app/data && chown -R hub:hub /app/data

ENV HUB_PREFIX=/hub
ENV DATABASE_URL=sqlite+aiosqlite:///./data/hub.db

EXPOSE 8081

USER hub

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--log-level", "info"]
