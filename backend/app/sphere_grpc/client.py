"""Thin helpers over the vendored MergeTB portal gRPC stubs.

Keeps the proto-import surface in one place so ``sphere_manager`` (and tests)
import service stubs and request/response messages from here rather than reaching
into the generated tree directly.

Auth: the portal accepts the Ory session token (``mrg whoami -t``) as a gRPC
``authorization: bearer <token>`` metadata header over TLS on :443. Verified
live against ``grpc.sphere-testbed.net:443`` on 2026-06-26 with
``Realize.GetRealizations``.
"""

from __future__ import annotations

import grpc

# Importing this package puts the vendored tree on sys.path (see __init__.py).
from app import sphere_grpc  # noqa: F401

from portal.v1 import portal_pb2_grpc as stubs  # type: ignore  # noqa: E402

DEFAULT_GRPC_TARGET = "grpc.sphere-testbed.net:443"


def make_channel(target: str = DEFAULT_GRPC_TARGET) -> grpc.Channel:
    """Return a TLS gRPC channel to the portal."""
    return grpc.secure_channel(target, grpc.ssl_channel_credentials())


def auth_metadata(token: str) -> list[tuple[str, str]]:
    """gRPC metadata carrying the portal bearer token."""
    return [("authorization", f"bearer {token}")]


def realize_stub(channel: grpc.Channel) -> "stubs.RealizeStub":
    return stubs.RealizeStub(channel)


def materialize_stub(channel: grpc.Channel) -> "stubs.MaterializeStub":
    return stubs.MaterializeStub(channel)


def model_stub(channel: grpc.Channel) -> "stubs.ModelStub":
    return stubs.ModelStub(channel)


def xdc_stub(channel: grpc.Channel) -> "stubs.XDCStub":
    return stubs.XDCStub(channel)


def workspace_stub(channel: grpc.Channel) -> "stubs.WorkspaceStub":
    """Projects, experiments, users — `Workspace` owns experiment CRUD."""
    return stubs.WorkspaceStub(channel)


def identity_stub(channel: grpc.Channel) -> "stubs.IdentityStub":
    """Login/Logout — used for token (re)acquisition."""
    return stubs.IdentityStub(channel)


def cred_stub(channel: grpc.Channel) -> "stubs.CredStub":
    """SSH keying material + certificates (GetUserSSHKeys / GetUserSSHCert)."""
    return stubs.CredStub(channel)


def commission_stub(channel: grpc.Channel) -> "stubs.CommissionStub":
    """Facilities/sites inventory (GetFacilities)."""
    return stubs.CommissionStub(channel)


def alloc_stub(channel: grpc.Channel) -> "stubs.AllocStub":
    """Allocation pools (GetPools)."""
    return stubs.AllocStub(channel)
