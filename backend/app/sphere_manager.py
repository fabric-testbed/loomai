"""SPHERE / MergeTB manager — portal gRPC session + experiment lifecycle.

Thread-safe singleton pattern mirroring ``chameleon_manager.py`` /
``fablib_manager.py``. SPHERE runs on the Merge (MergeTB) control stack; the
``mrg`` CLI and the web Launch UI are both clients of the same portal.

**Binding: native gRPC** (``grpc.sphere-testbed.net:443``). This is the transport
``mrg`` itself uses and the one verified end-to-end against the live portal
(2026-06-26). The REST grpc-gateway at ``api.sphere-testbed.net`` is NOT used —
every path returns 401 for the portal token and its auth contract is unknown
(see docs/SPHERE_INTEGRATION.md). The generated stubs are vendored in
``app/sphere_grpc/`` (regen: ``scripts/gen_sphere_grpc.sh``).

Auth: the Ory session token (``mrg whoami -t``) is sent as gRPC metadata
``authorization: bearer <token>``. If a username/password is configured the
manager can (re)acquire a token via ``Identity.Login`` — used both for first
acquisition and to recover from an ``UNAUTHENTICATED`` reply.

Responses are protobuf messages; high-level methods return them converted with
``MessageToDict(preserving_proto_field_name=True)``, whose shape matches the
captured ``mrg ... -j`` fixtures exactly — so the parse helpers below operate on
either source.

An interim :class:`_MrgCliBackend` (shell out to ``mrg``) is kept as a documented
fallback; the gRPC path is the default.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

# Strict identifier for SPHERE names that are interpolated into node DNS / ssh
# config — blocks newline/space/shell/config-metachar injection.
_SPHERE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _realization_state(detail: dict, complete: Any) -> tuple[str, str]:
    """Derive ('complete'|'failed'|'pending', error) from a GetRealization reply.

    A realization with Error-level diagnostics has *failed* (e.g. "no suitable
    resource found"); otherwise complete vs still-embedding. Lets the UI report
    failures instead of showing everything that isn't complete as "pending".

    GetRealization is returned either flat ({realization, diagnostics}) or wrapped
    ({result: {realization, diagnostics}, status}) — unwrap both."""
    inner = detail.get("result", detail) if isinstance(detail, dict) else {}
    diags = ((inner.get("diagnostics") or {}).get("value")) or []
    errs = [x.get("message") for x in diags if x.get("level") == "Error" and x.get("message")]
    if errs:
        return "failed", "; ".join(sorted(set(errs)))[:300]
    if complete is None:
        complete = (inner.get("realization") or {}).get("complete")
    if complete:
        return "complete", ""
    return "pending", ""
from typing import Any, Optional

# Importing the vendored gRPC package puts its tree on sys.path so the generated
# ``from portal.v1 import ...`` modules resolve (see app/sphere_grpc/__init__.py).
from app import sphere_grpc as _sphere_grpc  # noqa: F401

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sessions: dict[str, "_SphereSession"] = {}

_RPC_TIMEOUT = 60.0  # seconds

# Public SPHERE endpoints (from the Launch portal: Merge Testbed v1.3.29).
SPHERE_DEFAULTS = {
    "api_endpoint": "https://api.sphere-testbed.net",
    "grpc_endpoint": "grpc.sphere-testbed.net",
    "grpc_port": 443,
    "launch_url": "https://launch.sphere-testbed.net",
}

# GPS coordinates for SPHERE enclaves (for map display) — mirror
# CHAMELEON_SITE_LOCATIONS. Enclaves: IoT @ Northeastern, compute @ USC-ISI.
SPHERE_SITE_LOCATIONS = {
    "USC-ISI": {"lat": 33.9931, "lon": -118.4517, "city": "Marina del Rey, CA"},
    "Northeastern": {"lat": 42.3398, "lon": -71.0892, "city": "Boston, MA"},
    "Utah": {"lat": 40.7649, "lon": -111.8421, "city": "Salt Lake City, UT"},
}


def _contract_mode() -> bool:
    """True when running under the deterministic contract backend."""
    return os.environ.get("LOOMAI_CONTRACT_MODE") == "1"


def _grpc_target() -> str:
    cfg = _sphere_settings()
    host = cfg.get("grpc_endpoint", SPHERE_DEFAULTS["grpc_endpoint"])
    port = cfg.get("grpc_port", SPHERE_DEFAULTS["grpc_port"])
    return host if ":" in host else f"{host}:{port}"


# --------------------------------------------------------------------------- #
# Settings access
# --------------------------------------------------------------------------- #
def _sphere_settings() -> dict[str, Any]:
    """Return the ``sphere`` settings block (endpoints + credentials).

    TODO: add a ``sphere`` block to settings_manager DEFAULT_SETTINGS mirroring
    the ``chameleon`` block, e.g.::

        "sphere": {
            "enabled": false,
            "api_endpoint": "https://api.sphere-testbed.net",
            "grpc_endpoint": "grpc.sphere-testbed.net",
            "grpc_port": 443,
            "username": "",
            "password": "",        # optional; enables Identity.Login refresh
            "token": "",            # bearer from `mrg whoami -t`
            "default_project": "",  # e.g. "fabricsphere"
        }
    """
    try:
        from app import settings_manager

        return settings_manager._get_settings().get("sphere", {})  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - settings optional during scaffold
        return {}


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
@dataclass
class _SphereSession:
    """Holds a Merge portal gRPC channel + token for a given project context."""

    project: str
    grpc_target: str = field(default_factory=_grpc_target)
    username: str = ""
    _token: str = ""
    _channel: Any = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # Short-TTL cache for session-stable SSH material (keypair, cert, jump hosts,
    # per-XDC info) so each file/terminal op doesn't repeat 3-4 gRPC round trips.
    _cache: dict = field(default_factory=dict, repr=False)

    _CACHE_TTL = 300.0  # seconds

    def _cached(self, key: str, fn):
        now = time.monotonic()
        ent = self._cache.get(key)
        if ent and now - ent[0] < self._CACHE_TTL:
            return ent[1]
        val = fn()
        self._cache[key] = (now, val)
        return val

    # ---- channel ----------------------------------------------------------- #
    def channel(self) -> Any:
        """Lazily create (and cache) the TLS gRPC channel."""
        if self._channel is None:
            from app.sphere_grpc import client as _grpc

            self._channel = _grpc.make_channel(self.grpc_target)
        return self._channel

    # ---- auth -------------------------------------------------------------- #
    def get_token(self) -> str:
        """Return a valid bearer token, (re)authenticating if needed.

        Order of preference: a token already held this session → ``Identity.Login``
        when a username/password are configured (these take precedence over the
        ``token`` field, which may hold a stale value) → a configured token.
        """
        with self._lock:
            if self._token:
                return self._token
            cfg = _sphere_settings()
            # Credentials win over a possibly-stale settings token: log in fresh.
            if cfg.get("username") and cfg.get("password"):
                token = self._login_locked(cfg)
                if token:
                    return token
            token = cfg.get("token", "")
            if token:
                self._token = token
                return self._token
            raise RuntimeError(
                "SPHERE not configured: set settings.sphere.{username,password} "
                "for Identity.Login, or store a `mrg whoami -t` token in "
                "settings.sphere.token."
            )

    def _login_locked(self, cfg: dict[str, Any]) -> str:
        """Acquire a token via Identity.Login. Caller must hold ``self._lock``."""
        username = cfg.get("username") or self.username
        password = cfg.get("password")
        if not (username and password):
            return ""
        from app.sphere_grpc import client as _grpc
        from portal.v1 import identity_types_pb2 as it

        stub = _grpc.identity_stub(self.channel())
        resp = stub.Login(
            it.LoginRequest(username=username, password=password),
            timeout=_RPC_TIMEOUT,
        )
        self._token = resp.token
        return self._token

    def _metadata(self) -> list[tuple[str, str]]:
        from app.sphere_grpc import client as _grpc

        return _grpc.auth_metadata(self.get_token())

    # ---- generic invoke with one re-auth retry ----------------------------- #
    def _invoke(self, stub_method_name: str, stub_factory: str, request: Any) -> Any:
        """Call ``stub_factory(channel).<stub_method_name>(request)`` with auth,
        retrying once after a forced re-login when the session is rejected.

        The portal returns UNAUTHENTICATED or PERMISSION_DENIED ("No auth session
        found") for an expired/invalid token — both mean "log in again".
        """
        import grpc
        from app.sphere_grpc import client as _grpc

        _REAUTH = (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED)
        stub = getattr(_grpc, stub_factory)(self.channel())
        method = getattr(stub, stub_method_name)
        try:
            return method(request, metadata=self._metadata(), timeout=_RPC_TIMEOUT)
        except grpc.RpcError as exc:  # pragma: no cover - network path
            if exc.code() in _REAUTH:
                with self._lock:
                    self._token = ""
                    self._login_locked(_sphere_settings())
                return method(request, metadata=self._metadata(), timeout=_RPC_TIMEOUT)
            raise

    @staticmethod
    def _to_dict(msg: Any) -> dict[str, Any]:
        from google.protobuf.json_format import MessageToDict

        # Use json_name casing (the default) — it reproduces the `mrg ... -j`
        # field names captured in the fixtures EXACTLY (e.g. `taskSummary`,
        # `numVirtual`, and the reconcile subtree's `HighestStatus`), so the
        # parse/materialization helpers work on gRPC and CLI output alike.
        return MessageToDict(msg)

    # ---- projects / experiments (Workspace service) ------------------------ #
    def list_projects(self, by_all: bool = False) -> list[str]:
        from portal.v1 import workspace_types_pb2 as wt

        resp = self._invoke(
            "GetProjects", "workspace_stub",
            wt.GetProjectsRequest(filter=(1 if by_all else 0)),  # FilterMode ByAll/ByUser
        )
        return [p.name for p in resp.projects]

    def create_experiment(self, experiment: str, description: str = "") -> dict[str, Any]:
        from portal.v1 import workspace_types_pb2 as wt

        exp = wt.Experiment(name=experiment, project=self.project, description=description)
        resp = self._invoke("CreateExperiment", "workspace_stub",
                            wt.CreateExperimentRequest(experiment=exp))
        return self._to_dict(resp)

    def get_experiment(self, experiment: str, with_models: bool = False) -> dict[str, Any]:
        from portal.v1 import workspace_types_pb2 as wt

        resp = self._invoke(
            "GetExperiment", "workspace_stub",
            wt.GetExperimentRequest(project=self.project, experiment=experiment,
                                    with_models=with_models),
        )
        return self._to_dict(resp)

    def list_experiments(self, project: str | None = None) -> list[dict[str, Any]]:
        from portal.v1 import workspace_types_pb2 as wt

        resp = self._invoke(
            "GetProjectExperiments", "workspace_stub",
            wt.GetProjectExperimentsRequest(project=project or self.project),
        )
        return [self._to_dict(e) for e in resp.experiments]

    def get_experiment_model(self, experiment: str,
                             project: str | None = None) -> dict[str, Any]:
        """Return the experiment's latest pushed model as a builder-friendly
        topology: ``{found, network, nodes:[{name,facility}], links:[{members,addrs}]}``.
        Reconstructed from the compiled model (the mergexp source isn't stored)."""
        exp = self.get_experiment(experiment, with_models=True)
        models = exp.get("models") or {}
        if not models:
            return {"found": False, "nodes": [], "links": []}
        # Pick the most recently compiled revision.
        rev = max(models, key=lambda r: (models[r].get("compileTime") or ""))
        net = (models[rev] or {}).get("model") or {}
        nodes_raw = net.get("nodes") or []
        links_raw = net.get("links") or []
        nodes = [{"name": n.get("id"), "facility": (n.get("facility") or {}).get("value", "")}
                 for n in nodes_raw if n.get("id")]
        # (node, link) -> addr from each node's socket bound to that link
        addr: dict[tuple, str] = {}
        for n in nodes_raw:
            for s in n.get("sockets", []) or []:
                lid = (s.get("endpoint") or {}).get("element")
                a = (s.get("addrs") or [None])[0]
                if lid:
                    addr[(n.get("id"), lid)] = a or ""
        links = []
        for l in links_raw:
            members = [(e.get("socket") or {}).get("element")
                       for e in (l.get("endpoints") or [])]
            members = [m for m in members if m]
            links.append({"members": members,
                          "addrs": {m: addr.get((m, l.get("id")), "") for m in members}})
        return {"found": True, "revision": rev, "nodes": nodes, "links": links}

    def get_realization_topology(self, experiment: str, realization: str,
                                 project: str | None = None) -> dict[str, Any]:
        """Builder-friendly topology ({found, network, nodes, links}) extracted
        from a *realization* — the materialized truth.

        Unlike :meth:`get_experiment_model`, this is unambiguous: an experiment's
        pushed models are content-hash revisions with no reliable ordering (no
        compileTime), so picking "the latest model" is non-deterministic. The
        realization, by contrast, records exactly the topology that was embedded
        (e.g. a 3-endpoint LAN with all its members). Used by weave packaging so
        ``model.py`` matches what is actually deployed.
        """
        d = self.get_realization(experiment, realization)
        obj = d.get("result", d) if isinstance(d, dict) else d
        real = obj.get("realization", obj) if isinstance(obj, dict) else obj
        rnodes = (real or {}).get("nodes") or {}
        rlinks = (real or {}).get("links") or {}
        if not rnodes:
            return {"found": False, "nodes": [], "links": []}
        nodes: list[dict[str, Any]] = []
        addr: dict[tuple, str] = {}  # (node, link-id) -> cidr
        for wrapper in rnodes.values():
            node = (wrapper or {}).get("node", {})
            name = node.get("id")
            if not name:
                continue
            fac = node.get("facility")
            fac = fac.get("value", "") if isinstance(fac, dict) else (fac or "")
            nodes.append({"name": name, "facility": fac})
            for s in node.get("sockets", []) or []:
                lid = (s.get("endpoint") or {}).get("element")
                a = (s.get("addrs") or [None])[0]
                if lid:
                    addr[(name, lid)] = a or ""
        links: list[dict[str, Any]] = []
        for wrapper in rlinks.values():
            link = (wrapper or {}).get("link", {})
            lid = link.get("id", "")
            if lid == "infranet" or "infranet" in lid:
                continue  # implicit management link, not part of the model
            members = [(e.get("socket") or {}).get("element")
                       for e in (link.get("endpoints") or [])]
            members = [m for m in members if m]
            links.append({"members": members,
                          "addrs": {m: addr.get((m, lid), "") for m in members}})
        return {"found": True, "network": experiment, "nodes": nodes, "links": links}

    def delete_experiment(self, experiment: str, project: str | None = None) -> dict[str, Any]:
        from portal.v1 import workspace_types_pb2 as wt

        return self._to_dict(self._invoke(
            "DeleteExperiment", "workspace_stub",
            wt.DeleteExperimentRequest(project=project or self.project, experiment=experiment),
        ))

    # ---- model (Model service) --------------------------------------------- #
    def compile_model(self, model_src: str) -> dict[str, Any]:
        """Compile (validate) a mergexp model source. Returns
        ``{success, errors, network}`` so the UI can show errors before push."""
        from portal.v1 import model_types_pb2 as mo

        resp = self._invoke("Compile", "model_stub",
                            mo.CompileRequest(model=model_src))
        return self._to_dict(resp)

    def push_model(self, model: str | bytes, experiment: str,
                   tag: str | None = None, branch: str | None = None) -> str:
        """Push a model (mergexp source) to an experiment; returns the revision.

        ``PushRequest.model`` is a string field — decode bytes to text.
        """
        from portal.v1 import model_types_pb2 as mo

        src = model.decode() if isinstance(model, (bytes, bytearray)) else model
        req = mo.PushRequest(model=src, experiment=experiment, project=self.project)
        if tag:
            req.tag = tag
        if branch:
            req.branch = branch
        resp = self._invoke("Push", "model_stub", req)
        return resp.revision

    # ---- realize (Realize service) ----------------------------------------- #
    def list_realizations(self, by_all: bool = False, summary: bool = False,
                          with_state: bool = False) -> list[dict[str, Any]]:
        from portal.v1 import realize_types_pb2 as rt

        resp = self._invoke(
            "GetRealizations", "realize_stub",
            rt.GetRealizationsRequest(filter=(1 if by_all else 0), summary=summary),
        )
        out: list[dict[str, Any]] = []
        for r in resp.results:
            # Each result carries either `realization` (full) or `summary`.
            if r.HasField("realization"):
                out.append(self._to_dict(r.realization))
            elif r.HasField("summary"):
                out.append(self._to_dict(r.summary))
        if with_state:
            for r in out:
                try:
                    # status_ms>0 so the portal includes diagnostics (needed to
                    # tell a *failed* realization from one still embedding).
                    d = self.get_realization(r.get("eid", ""), r.get("id", ""), status_ms=1)
                    state, err = _realization_state(d, r.get("complete"))
                    r["state"] = state
                    if err:
                        r["error"] = err
                except Exception:  # pragma: no cover - per-realization best effort
                    r["state"] = "complete" if r.get("complete") else "pending"
        return out

    def get_realization(self, experiment: str, realization: str,
                        status_ms: int = 0) -> dict[str, Any]:
        from portal.v1 import realize_types_pb2 as rt

        resp = self._invoke(
            "GetRealization", "realize_stub",
            rt.GetRealizationRequest(project=self.project, experiment=experiment,
                                     realization=realization, statusMS=status_ms),
        )
        return self._to_dict(resp)

    def realize(self, experiment: str, realization: str, *, tag: str | None = None,
                branch: str | None = None, revision: str | None = None,
                duration: str | None = None) -> dict[str, Any]:
        from portal.v1 import realize_types_pb2 as rt

        req = rt.RealizeRequest(project=self.project, experiment=experiment,
                                realization=realization)
        if tag:
            req.tag = tag
        if branch:
            req.branch = branch
        if revision:
            req.revision = revision
        if duration:
            req.duration = duration
        return self._to_dict(self._invoke("Realize", "realize_stub", req))

    def relinquish(self, experiment: str, realization: str) -> dict[str, Any]:
        from portal.v1 import realize_types_pb2 as rt

        return self._to_dict(self._invoke(
            "Relinquish", "realize_stub",
            rt.RelinquishRequest(project=self.project, experiment=experiment,
                                 realization=realization),
        ))

    # ---- materialize (Materialize service) --------------------------------- #
    def materialize(self, experiment: str, realization: str) -> dict[str, Any]:
        from portal.v1 import materialize_types_pb2 as mt

        return self._to_dict(self._invoke(
            "Materialize", "materialize_stub",
            mt.MaterializeRequest(project=self.project, experiment=experiment,
                                  realization=realization),
        ))

    def get_materialization(self, experiment: str, realization: str, *,
                            status_ms: int = 0, include_data: bool = False,
                            include_ingresses: bool = False) -> dict[str, Any]:
        from portal.v1 import materialize_types_pb2 as mt

        return self._to_dict(self._invoke(
            "GetMaterialization", "materialize_stub",
            mt.GetMaterializationRequest(
                project=self.project, experiment=experiment, realization=realization,
                statusMS=status_ms, includeMaterializationData=include_data,
                includeIngresses=include_ingresses),
        ))

    def get_materialization_status(self, experiment: str, realization: str) -> dict[str, Any]:
        from portal.v1 import materialize_types_pb2 as mt

        return self._to_dict(self._invoke(
            "GetMaterializationStatus", "materialize_stub",
            mt.GetMaterializationStatusRequest(project=self.project,
                                               experiment=experiment,
                                               realization=realization),
        ))

    def dematerialize(self, experiment: str, realization: str) -> dict[str, Any]:
        from portal.v1 import materialize_types_pb2 as mt

        return self._to_dict(self._invoke(
            "Dematerialize", "materialize_stub",
            mt.DematerializeRequest(project=self.project, experiment=experiment,
                                    realization=realization),
        ))

    # ---- XDC (XDC service) ------------------------------------------------- #
    # An XDC (Experiment Data Conduit) is a Merge-hosted jump container attached
    # to a materialization; it is the only way to reach experiment nodes. See
    # docs/SPHERE_INTEGRATION.md.
    def list_xdcs(self, project: str | None = None,
                  with_status: bool = False) -> list[dict[str, Any]]:
        from portal.v1 import xdc_types_pb2 as xt

        resp = self._invoke("ListXDCs", "xdc_stub",
                            xt.ListXDCsRequest(project=project or self.project))
        out = [self._to_dict(x) for x in resp.XDCs]
        if with_status:
            for x in out:
                try:
                    st = (self.get_xdc(x.get("name", ""), project).get("status") or {})
                    x["status"] = st.get("HighestStatus") or "unknown"
                    x["ready"] = st.get("HighestStatus") == "Success"
                except Exception:  # pragma: no cover - per-XDC status best effort
                    x["status"] = "unknown"
                    x["ready"] = None
        return out

    @staticmethod
    def _bare_xdc(xdc: str) -> str:
        """XDC identifiers in gRPC must be the bare name (regex
        ``^[a-z][a-z0-9]{0,62}$``); callers/UI may pass the qualified
        ``<name>.<project>`` form, so strip the project suffix."""
        return (xdc or "").split(".", 1)[0]

    def get_xdc(self, xdc: str, project: str | None = None,
                status_ms: int = 1) -> dict[str, Any]:
        from portal.v1 import xdc_types_pb2 as xt

        return self._to_dict(self._invoke(
            "GetXDC", "xdc_stub",
            xt.GetXDCRequest(project=project or self.project,
                             xdc=self._bare_xdc(xdc), statusMS=status_ms)))

    def create_xdc(self, xdc: str, project: str | None = None,
                   xdc_type: str = "shared") -> dict[str, Any]:
        from portal.v1 import xdc_types_pb2 as xt

        try:
            type_val = xt.XDCType.Value(xdc_type)
        except ValueError:
            type_val = xt.XDCType.Value("shared")
        req = xt.CreateXDCRequest(project=project or self.project,
                                  xdc=self._bare_xdc(xdc), type=type_val)
        return self._to_dict(self._invoke("CreateXDC", "xdc_stub", req))

    def delete_xdc(self, xdc: str, project: str | None = None) -> dict[str, Any]:
        from portal.v1 import xdc_types_pb2 as xt

        return self._to_dict(self._invoke(
            "DeleteXDC", "xdc_stub",
            xt.DeleteXDCRequest(project=project or self.project, xdc=self._bare_xdc(xdc))))

    def attach_xdc(self, xdc: str, experiment: str, realization: str,
                   project: str | None = None,
                   realization_project: str | None = None) -> dict[str, Any]:
        from portal.v1 import xdc_types_pb2 as xt

        proj = project or self.project
        req = xt.AttachXDCRequest(
            xdc=self._bare_xdc(xdc), project=proj, experiment=experiment,
            realization=realization, realization_project=realization_project or proj)
        return self._to_dict(self._invoke("AttachXDC", "xdc_stub", req))

    def detach_xdc(self, xdc: str, experiment: str, realization: str,
                   project: str | None = None) -> dict[str, Any]:
        from portal.v1 import xdc_types_pb2 as xt

        req = xt.DetachXDCRequest(xdc=self._bare_xdc(xdc), project=project or self.project,
                                  experiment=experiment, realization=realization)
        return self._to_dict(self._invoke("DetachXDC", "xdc_stub", req))

    def get_xdc_jump_hosts(self) -> list[dict[str, Any]]:
        from portal.v1 import xdc_types_pb2 as xt

        resp = self._invoke("GetXDCJumpHosts", "xdc_stub",
                            xt.GetXDCJumpHostsRequest())
        return [self._to_dict(j) for j in resp.JumpHosts]

    # ---- Inventory (Commission / Realize / Alloc) -------------------------- #
    def get_facilities(self) -> list[dict[str, Any]]:
        from portal.v1 import commission_types_pb2 as cm

        resp = self._invoke("GetFacilities", "commission_stub",
                            cm.GetFacilitiesRequest())
        return [self._to_dict(f) for f in resp.facilities]

    def get_resources(self) -> list[dict[str, Any]]:
        from portal.v1 import realize_types_pb2 as rt

        resp = self._invoke("GetResources", "realize_stub",
                            rt.GetResourcesRequest())
        return [self._to_dict(r) for r in resp.resources]

    def get_pools(self) -> list[dict[str, Any]]:
        from portal.v1 import alloc_types_pb2 as al

        resp = self._invoke("GetPools", "alloc_stub", al.GetPoolsRequest())
        return [self._to_dict(p) for p in resp.pools]

    def get_inventory(self) -> dict[str, Any]:
        """Facilities + resources + pools for the inventory view. The three RPCs
        run concurrently (each best-effort) so the view loads in ~1 round trip."""
        from concurrent.futures import ThreadPoolExecutor
        sections = {"facilities": self.get_facilities,
                    "resources": self.get_resources,
                    "pools": self.get_pools}
        out: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {key: ex.submit(fn) for key, fn in sections.items()}
            for key, fut in futures.items():
                try:
                    out[key] = fut.result()
                except Exception as exc:  # pragma: no cover - network path
                    logger.warning("SPHERE inventory %s failed: %s", key, exc)
                    out[key] = []
        return out

    # ---- Cred (Cred service) — SSH keying material + certificates ----------- #
    def _cred_username(self) -> str:
        return _sphere_settings().get("username") or self.username or ""

    def get_user_ssh_keys(self, username: str | None = None) -> dict[str, Any]:
        from portal.v1 import cred_types_pb2 as ct

        resp = self._invoke(
            "GetUserSSHKeys", "cred_stub",
            ct.GetUserSSHKeysRequest(Username=username or self._cred_username()))
        return self._to_dict(resp)

    def get_user_ssh_cert(self, username: str | None = None) -> dict[str, Any]:
        from portal.v1 import cred_types_pb2 as ct

        resp = self._invoke(
            "GetUserSSHCert", "cred_stub",
            ct.GetUserSSHCertRequest(Username=username or self._cred_username()))
        return self._to_dict(resp)

    # ---- High-level: everything needed to SSH to one node ------------------ #
    def resolve_node_ssh(self, experiment: str, realization: str, node: str,
                         xdc: str) -> dict[str, Any]:
        """Resolve the full SSH path to a materialized node through an XDC.

        Returns the keying material, signed cert, jump-host chain, XDC fqdn,
        node management DNS and login user — everything ``terminal.py`` needs to
        build an ``ssh`` invocation equivalent to ``mrg xdc ssh -x <xdc>.<proj>
        <node>``. Node management DNS follows the Merge convention
        ``<node>.infra.<rname>.<exp>.<proj>``.
        """
        # Validate every value that gets interpolated into node DNS / ssh config.
        for label, val in (("experiment", experiment), ("realization", realization),
                           ("node", node), ("xdc", xdc), ("project", self.project)):
            if not val or not _SPHERE_ID_RE.match(val):
                raise ValueError(f"Invalid SPHERE {label}: {val!r}")
        # Session-stable material is cached; only re-fetched after the TTL.
        keys = (self._cached("ssh_keys", self.get_user_ssh_keys) or {}).get("Keys", {}) or {}
        cert = (self._cached("ssh_cert", self.get_user_ssh_cert) or {}).get("Cert", {}) or {}
        jump_hosts = self._cached("jump_hosts", self.get_xdc_jump_hosts)
        xdc_info = (self._cached(f"xdc:{xdc}", lambda: self.get_xdc(xdc)) or {}).get("xdc", {}) or {}
        user = self._cred_username()
        node_dns = f"{node}.infra.{realization}.{experiment}.{self.project}"
        return {
            "username": user,
            "private_key": keys.get("Private", ""),
            "public_key": keys.get("Public", ""),
            "cert": cert.get("Cert", ""),
            "ca_host_pubkey": cert.get("CAHostPubKey", ""),
            "jump_hosts": jump_hosts,            # [{name, port, fqdn, ver}]
            "xdc_fqdn": xdc_info.get("fqdn", ""),
            "node_dns": node_dns,
            "node": node,
            "xdc": xdc,
        }

    def resolve_xdc_ssh(self, xdc: str) -> dict[str, Any]:
        """Resolve the SSH path to the **XDC container itself** (not a node).

        Same keying material + jump chain as :meth:`resolve_node_ssh`, but the
        target is the XDC pod — used to browse/seed the XDC's own filesystem
        (where its JupyterLab serves from). ``ssh_target`` tells the file-op
        helpers to scp/ssh to the ``sphere-xdc`` alias instead of ``sphere-node``.
        """
        if not xdc or not _SPHERE_ID_RE.match(xdc):
            raise ValueError(f"Invalid SPHERE xdc: {xdc!r}")
        keys = (self._cached("ssh_keys", self.get_user_ssh_keys) or {}).get("Keys", {}) or {}
        cert = (self._cached("ssh_cert", self.get_user_ssh_cert) or {}).get("Cert", {}) or {}
        jump_hosts = self._cached("jump_hosts", self.get_xdc_jump_hosts)
        xdc_info = (self._cached(f"xdc:{xdc}", lambda: self.get_xdc(xdc)) or {}).get("xdc", {}) or {}
        return {
            "username": self._cred_username(),
            "private_key": keys.get("Private", ""),
            "public_key": keys.get("Public", ""),
            "cert": cert.get("Cert", ""),
            "ca_host_pubkey": cert.get("CAHostPubKey", ""),
            "jump_hosts": jump_hosts,
            "xdc_fqdn": xdc_info.get("fqdn", ""),
            "node_dns": "",
            "node": "",
            "xdc": xdc,
            "ssh_target": "sphere-xdc",
        }


class _ContractSphereSession:
    """Deterministic SPHERE session for contract tests.

    Returns the captured fixture payloads (shaped like the live proto→dict
    output) so the frontend contract suite is stable without a live portal.
    """

    _FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "tests",
                                "fixtures", "sphere")

    def __init__(self, project: str = "fabricsphere"):
        self.project = project

    @classmethod
    def _fixture(cls, name: str) -> dict[str, Any]:
        path = os.path.join(cls._FIXTURE_DIR, name)
        with open(path) as fh:
            return json.load(fh)

    def get_token(self) -> str:
        return "contract-token"

    def list_projects(self, by_all: bool = False) -> list[str]:
        return ["fabricsphere"]

    def list_realizations(self, by_all: bool = False, summary: bool = False,
                          with_state: bool = False) -> list[dict[str, Any]]:
        results = self._fixture("realization.json").get("results", [])
        out: list[dict[str, Any]] = []
        for r in results:
            rz = r.get("realization") or r.get("summary") or r
            if with_state:
                rz = {**rz, "state": "complete" if rz.get("complete") else "pending"}
            out.append(rz)
        return out

    def create_experiment(self, experiment: str, description: str = "") -> dict[str, Any]:
        return {"name": experiment, "project": self.project, "description": description}

    def list_experiments(self, project: str | None = None) -> list[dict[str, Any]]:
        return [{"name": "hello", "project": self.project, "description": "contract",
                 "creator": "contract"}]

    def get_experiment_model(self, experiment: str,
                             project: str | None = None) -> dict[str, Any]:
        return {"found": True, "revision": "contract",
                "nodes": [{"name": "a", "facility": ""}, {"name": "b", "facility": ""}],
                "links": [{"members": ["a", "b"], "addrs": {"a": "10.0.0.1/24", "b": "10.0.0.2/24"}}]}

    def delete_experiment(self, experiment: str, project: str | None = None) -> dict[str, Any]:
        return {}

    def compile_model(self, model_src: str) -> dict[str, Any]:
        return {"success": True, "errors": [], "network": "hello"}

    def push_model(self, model: str | bytes, experiment: str,
                   tag: str | None = None, branch: str | None = None) -> str:
        return "contract-revision"

    def get_realization(self, experiment: str, realization: str,
                        status_ms: int = 0) -> dict[str, Any]:
        for r in self.list_realizations():
            if r.get("id") == realization and r.get("eid") == experiment:
                return r
        return self.list_realizations()[0]

    def get_materialization(self, experiment: str, realization: str, **_: Any
                            ) -> dict[str, Any]:
        return self._fixture("materialization.json")

    get_materialization_status = get_materialization  # type: ignore[assignment]

    # ---- XDC / Cred (deterministic stand-ins) ------------------------------ #
    def list_xdcs(self, project: str | None = None,
                  with_status: bool = False) -> list[dict[str, Any]]:
        x = {
            "name": "x0", "fqdn": f"x0.{self.project}", "creator": "contract",
            "type": "shared", "materialization": "world.hello." + self.project,
        }
        if with_status:
            x["status"] = "Success"
            x["ready"] = True
        return [x]

    def get_xdc(self, xdc: str, project: str | None = None,
                status_ms: int = 1) -> dict[str, Any]:
        return {"xdc": {"name": xdc, "fqdn": f"{xdc}.{self.project}",
                        "type": "shared"},
                "status": {"HighestStatus": "Success"}}

    def create_xdc(self, xdc: str, project: str | None = None,
                   xdc_type: str = "shared") -> dict[str, Any]:
        return {}

    def delete_xdc(self, xdc: str, project: str | None = None) -> dict[str, Any]:
        return {}

    def attach_xdc(self, xdc: str, experiment: str, realization: str,
                   project: str | None = None,
                   realization_project: str | None = None) -> dict[str, Any]:
        return {}

    def detach_xdc(self, xdc: str, experiment: str, realization: str,
                   project: str | None = None) -> dict[str, Any]:
        return {}

    def get_xdc_jump_hosts(self) -> list[dict[str, Any]]:
        return [{"name": "jump0", "port": 22,
                 "fqdn": f"jump.{self.project}.sphere-testbed.net", "ver": 1}]

    def get_inventory(self) -> dict[str, Any]:
        return {
            "facilities": [
                {"name": "moddeter", "address": "USC-ISI", "description": "Modeling/DETER enclave"},
            ],
            "resources": [
                {"resource": {"id": "md25", "facility": "moddeter",
                              "procs": [{"cores": 64}], "memory": {"capacity": "274877906944"}}},
            ],
            "pools": [
                {"name": "default", "description": "contract", "facilities": [], "projects": ["fabricsphere"]},
            ],
        }

    def get_user_ssh_keys(self, username: str | None = None) -> dict[str, Any]:
        return {"Keys": {"Public": "ssh-ed25519 AAAA... contract",
                         "Private": "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                                    "contract\n-----END OPENSSH PRIVATE KEY-----\n",
                         "ver": 1}}

    def get_user_ssh_cert(self, username: str | None = None) -> dict[str, Any]:
        return {"Cert": {"Cert": "ssh-ed25519-cert-v01@openssh.com AAAA... contract",
                         "CAHostPubKey": "ssh-ed25519 AAAA... contract-ca",
                         "ver": 1}}

    def resolve_node_ssh(self, experiment: str, realization: str, node: str,
                         xdc: str) -> dict[str, Any]:
        keys = self.get_user_ssh_keys()["Keys"]
        cert = self.get_user_ssh_cert()["Cert"]
        return {
            "username": "contract",
            "private_key": keys["Private"], "public_key": keys["Public"],
            "cert": cert["Cert"], "ca_host_pubkey": cert["CAHostPubKey"],
            "jump_hosts": self.get_xdc_jump_hosts(),
            "xdc_fqdn": f"{xdc}.{self.project}",
            "node_dns": f"{node}.infra.{realization}.{experiment}.{self.project}",
            "node": node, "xdc": xdc,
        }

    def resolve_xdc_ssh(self, xdc: str) -> dict[str, Any]:
        keys = self.get_user_ssh_keys()["Keys"]
        cert = self.get_user_ssh_cert()["Cert"]
        return {
            "username": "contract",
            "private_key": keys["Private"], "public_key": keys["Public"],
            "cert": cert["Cert"], "ca_host_pubkey": cert["CAHostPubKey"],
            "jump_hosts": self.get_xdc_jump_hosts(),
            "xdc_fqdn": f"{xdc}.{self.project}",
            "node_dns": "", "node": "", "xdc": xdc, "ssh_target": "sphere-xdc",
        }

    def get_realization_topology(self, experiment: str, realization: str,
                                 project: str | None = None) -> dict[str, Any]:
        # Contract mode: fall back to the experiment model path (deterministic
        # here) so packaging tests exercise a stable topology.
        return {"found": False, "nodes": [], "links": []}


# --------------------------------------------------------------------------- #
# mrg CLI backend (interim fallback — proven working in the live run)
# --------------------------------------------------------------------------- #
class _MrgCliBackend:
    """Drive SPHERE by shelling out to the local ``mrg`` binary.

    Kept as a documented fallback. The gRPC session above is the default; use
    this only where ``mrg`` is installed and a missing gRPC route blocks a verb.
    """

    def __init__(self, mrg_path: str | None = None):
        self.mrg = mrg_path or shutil.which("mrg") or "mrg"

    def _run(self, args: list[str], json_out: bool = True) -> Any:
        cmd = [self.mrg, *args]
        if json_out:
            cmd.append("-j")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"mrg {' '.join(args)} failed: {proc.stderr.strip()}")
        if not json_out:
            return proc.stdout
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def list_realizations(self) -> Any:
        return self._run(["list", "realizations"])

    def show_materialization(self, rname: str, exp: str, proj: str) -> Any:
        ref = f"{rname}.{exp}.{proj}"
        return self._run(["show", "materialization", ref, "--with-status"])


# --------------------------------------------------------------------------- #
# Module-level lifecycle (thin wrappers over the session for a given project)
# --------------------------------------------------------------------------- #
def create_experiment(exp: str, project: str, description: str = "") -> Any:
    return get_session(project).create_experiment(exp, description)


def list_experiments(project: str) -> Any:
    return get_session(project).list_experiments(project)


def delete_experiment(exp: str, project: str) -> Any:
    return get_session(project).delete_experiment(exp, project)


def get_experiment_model(exp: str, project: str) -> Any:
    return get_session(project).get_experiment_model(exp, project)


def push_model(model: str | bytes, exp: str, project: str, tag: str | None = None) -> Any:
    return get_session(project).push_model(model, exp, tag=tag)


def compile_model(model_src: str, project: str) -> Any:
    return get_session(project).compile_model(model_src)


def realize(rname: str, exp: str, project: str, ref: str, by: str = "tag") -> Any:
    kwargs = {by: ref} if by in ("tag", "branch", "revision") else {"tag": ref}
    return get_session(project).realize(exp, rname, **kwargs)


def materialize(rname: str, exp: str, project: str) -> Any:
    return get_session(project).materialize(exp, rname)


def dematerialize(rname: str, exp: str, project: str) -> Any:
    return get_session(project).dematerialize(exp, rname)


def list_xdcs(project: str, with_status: bool = False) -> Any:
    return get_session(project).list_xdcs(project, with_status)


def get_inventory(project: str) -> Any:
    return get_session(project).get_inventory()


def create_xdc(xdc: str, project: str, xdc_type: str = "shared") -> Any:
    return get_session(project).create_xdc(xdc, project, xdc_type)


def delete_xdc(xdc: str, project: str) -> Any:
    return get_session(project).delete_xdc(xdc, project)


def attach_xdc(xdc: str, rname: str, exp: str, project: str) -> Any:
    return get_session(project).attach_xdc(xdc, exp, rname, project)


def detach_xdc(xdc: str, rname: str, exp: str, project: str) -> Any:
    return get_session(project).detach_xdc(xdc, exp, rname, project)


def resolve_node_ssh(node: str, rname: str, exp: str, project: str, xdc: str) -> Any:
    return get_session(project).resolve_node_ssh(exp, rname, node, xdc)


def resolve_xdc_ssh(xdc: str, project: str) -> Any:
    return get_session(project).resolve_xdc_ssh(xdc)


# --------------------------------------------------------------------------- #
# Parse helpers — field names taken from real captured payloads
# --------------------------------------------------------------------------- #
def parse_realization_nodes(realization: dict) -> list[dict[str, Any]]:
    """Flatten ``realization.nodes`` into LoomAI node dicts.

    Input shape (from ``mrg list realizations -j`` → results[].realization, or
    the identical ``MessageToDict(preserving_proto_field_name=True)`` of the
    gRPC ``Realization``):
        nodes = { "moddeter/a": {"node": {"id": "a",
                  "sockets": [{"addrs": ["10.0.0.1/24"], "endpoint": {...}}]}}, ... }
    """
    out: list[dict[str, Any]] = []
    for key, wrapper in (realization.get("nodes") or {}).items():
        node = (wrapper or {}).get("node", {})
        addrs: list[str] = []
        for sock in node.get("sockets", []) or []:
            addrs.extend(sock.get("addrs", []) or [])
        out.append(
            {
                "key": key,                 # "moddeter/a" (<module>/<name>)
                "name": node.get("id"),     # "a"
                "addrs": addrs,             # ["10.0.0.1/24"]
                "provider": "sphere",
            }
        )
    return out


def parse_realization_links(realization: dict) -> list[dict[str, Any]]:
    """Flatten ``realization.links`` (keyed like "a.0~b.0") into edge dicts."""
    out: list[dict[str, Any]] = []
    for key, wrapper in (realization.get("links") or {}).items():
        link = (wrapper or {}).get("link", {})
        endpoints = [
            ep.get("socket", {}).get("element")
            for ep in link.get("endpoints", []) or []
        ]
        out.append({"key": key, "endpoints": endpoints, "provider": "sphere"})
    return out


def materialization_ready(matrlz: dict) -> bool:
    """True when a materialization payload reports overall Success.

    Shape: { "taskSummary": {"HighestStatus": "Success", ...}, "summary": {...} }
    """
    return (matrlz.get("taskSummary") or {}).get("HighestStatus") == "Success"


def materialization_summary(matrlz: dict) -> dict[str, Any]:
    """Return the compact `summary` block: {rid, eid, pid, numVirtual, numLinks}."""
    return matrlz.get("summary") or {}


# --------------------------------------------------------------------------- #
# Module-level surface (mirror chameleon_manager public API)
# --------------------------------------------------------------------------- #
def get_session(project: str) -> "_SphereSession | _ContractSphereSession":
    """Return (creating if needed) the session for *project*."""
    if _contract_mode():
        return _ContractSphereSession(project)
    with _lock:
        sess = _sessions.get(project)
        if sess is None:
            cfg = _sphere_settings()
            sess = _SphereSession(
                project=project,
                grpc_target=_grpc_target(),
                username=cfg.get("username", ""),
            )
            _sessions[project] = sess
        return sess


def get_configured_projects() -> list[str]:
    """Projects the user can target. Mirrors chameleon get_configured_sites.

    Uses the configured default if present; otherwise queries the portal
    (Workspace.GetProjects) when a token is available.
    """
    if _contract_mode():
        return ["fabricsphere"]
    cfg = _sphere_settings()
    default = cfg.get("default_project")
    if default:
        return [default]
    if cfg.get("token") or (cfg.get("username") and cfg.get("password")):
        try:
            return _SphereSession(project="").list_projects()
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("SPHERE list_projects failed: %s", exc)
    return []


def reset_sessions() -> None:
    """Drop cached sessions (e.g. after a settings change)."""
    with _lock:
        for sess in _sessions.values():
            ch = getattr(sess, "_channel", None)
            if ch is not None:
                try:
                    ch.close()
                except Exception:  # pragma: no cover
                    pass
        _sessions.clear()


def is_configured() -> bool:
    """True when SPHERE has enough config to attempt API calls."""
    if _contract_mode():
        return True
    cfg = _sphere_settings()
    if not cfg.get("enabled"):
        return False
    return bool(cfg.get("token")) or bool(cfg.get("username") and cfg.get("password"))
