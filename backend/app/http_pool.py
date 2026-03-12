"""Shared httpx clients with connection pooling.

Reuses TCP+TLS sessions across requests, saving ~100-200ms per call
that would otherwise be spent on connection setup.
"""

import httpx

# Shared client for FABRIC API calls (artifacts, metrics, projects)
fabric_client = httpx.AsyncClient(
    timeout=30,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
)

# For AI/LLM API calls and web fetches (longer timeouts)
ai_client = httpx.AsyncClient(
    timeout=httpx.Timeout(180.0, connect=10.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    follow_redirects=True,
    headers={"User-Agent": "Mozilla/5.0 (compatible; LooMAI/1.0)"},
)

# For Prometheus metrics queries (verify=False for self-signed certs)
metrics_client = httpx.AsyncClient(
    timeout=15,
    verify=False,
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
)
