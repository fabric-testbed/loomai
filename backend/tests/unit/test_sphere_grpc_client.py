"""Offline checks for the vendored MergeTB / SPHERE portal gRPC client.

These do NOT hit the network — they verify the generated stubs import and that
the lifecycle services / request messages we depend on still exist after a
regeneration (scripts/gen_sphere_grpc.sh). A live call is exercised manually;
see docs/SPHERE_INTEGRATION.md.
"""

from __future__ import annotations

import pytest

grpc = pytest.importorskip("grpc")


def test_client_helpers_and_stubs_import():
    from app.sphere_grpc import client

    ch = client.make_channel("localhost:443")  # no connection attempt on creation
    # The four lifecycle stubs we build the integration on.
    assert client.realize_stub(ch) is not None
    assert client.materialize_stub(ch) is not None
    assert client.model_stub(ch) is not None
    assert client.xdc_stub(ch) is not None


def test_auth_metadata_shape():
    from app.sphere_grpc import client

    md = client.auth_metadata("tok123")
    assert md == [("authorization", "bearer tok123")]


def test_expected_services_present():
    from app.sphere_grpc import client  # noqa: F401  (puts vendored tree on path)
    from portal.v1 import portal_pb2_grpc as stubs

    for svc in ("ModelStub", "RealizeStub", "MaterializeStub", "XDCStub", "IdentityStub"):
        assert hasattr(stubs, svc), f"missing portal.v1 service stub: {svc}"


def test_lifecycle_request_messages_present():
    from app.sphere_grpc import client  # noqa: F401
    from portal.v1 import realize_types_pb2 as rt
    from portal.v1 import materialize_types_pb2 as mt

    # Fields locked against the live wire contract (verified 2026-06-26).
    req = rt.GetRealizationsRequest(summary=True)
    assert {"filter", "summary"} <= {f.name for f in req.DESCRIPTOR.fields}
    assert hasattr(mt, "MaterializeRequest")
