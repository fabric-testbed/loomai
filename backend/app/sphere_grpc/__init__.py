"""Vendored MergeTB / SPHERE portal gRPC client (generated).

The Python modules under this package were generated with ``protoc`` from the
MergeTB ``portal.v1`` protobufs (see ``backend/scripts/gen_sphere_grpc.sh`` for
the exact, reproducible generation). They use absolute proto-import paths
(``portal.v1.*``, ``mergetb.xir.pb.*``, ``google.api.*``,
``protoc_gen_openapiv2.*``, ``mwitkow.*``), so this package directory is placed
on ``sys.path`` here to let those imports resolve without polluting the rest of
the app namespace.

The portal endpoint exposes 15 services (verified live via gRPC reflection on
2026-06-26); the ones that matter for the LoomAI lifecycle are ``Model``,
``Realize``, ``Materialize`` and ``XDC``. See docs/SPHERE_INTEGRATION.md.
"""

from __future__ import annotations

import os
import sys

# Make the vendored proto packages importable (`from portal.v1 import ...`).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

__all__ = ["channel", "stubs", "pb"]
