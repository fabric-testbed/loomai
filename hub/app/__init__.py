"""LoomAI Hub.

The single source of truth for the hub version. Both the FastAPI app metadata
and the outgoing X-LoomAI-Version tracking header read from here — they were
previously separate literals and had drifted to 0.7.13 and 0.2.0.
"""

__version__ = "0.7.14"
