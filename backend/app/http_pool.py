"""Shared httpx clients with connection pooling.

Reuses TCP+TLS sessions across requests, saving ~100-200ms per call
that would otherwise be spent on connection setup.
"""

import httpx


async def _inject_tracking_headers(request: httpx.Request) -> None:
    """Event hook that adds LoomAI tracking headers to every outgoing request."""
    from app.tracking_headers import get_tracking_headers

    for key, value in get_tracking_headers().items():
        request.headers[key] = value


# Shared client for FABRIC API calls (artifacts, metrics, projects)
fabric_client = httpx.AsyncClient(
    timeout=30,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    event_hooks={"request": [_inject_tracking_headers]},
)

# For AI/LLM API calls and web fetches (longer timeouts)
# Complex weave prompts can take 5+ min for the LLM to generate long scripts
ai_client = httpx.AsyncClient(
    timeout=httpx.Timeout(600.0, connect=10.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    follow_redirects=True,
    headers={"User-Agent": "Mozilla/5.0 (compatible; LooMAI/1.0)"},
    event_hooks={"request": [_inject_tracking_headers]},
)

# For Prometheus metrics queries (verify=False for self-signed certs)
# Not instrumented — internal localhost scraping only
metrics_client = httpx.AsyncClient(
    timeout=15,
    verify=False,
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
)
