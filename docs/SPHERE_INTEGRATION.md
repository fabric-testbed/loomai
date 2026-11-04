# SPHERE / MergeTB Integration — Implementation Spec

## Context

Add **SPHERE** (Security and Privacy Heterogeneous Environment for Reproducible
Experimentation) as a **third testbed provider** in LoomAI, alongside FABRIC
(FABlib) and Chameleon (OpenStack). SPHERE runs on the **Merge (MergeTB)**
control stack; researchers define topologies in Python (`mergexp`) and drive the
experiment lifecycle (`realize` → `materialize`) via the Merge Portal API.

SPHERE is a *security-research instrument* — its differentiators are tiered
**containment** (incl. live-malware isolation), security-specific hardware
(TEEs: Intel TDX / AMD SEV / ARM CCA-TrustZone; real OT/ICS PLCs; ~500 physical
IoT devices), and reproducibility. None of these overlap FABRIC/Chameleon, so
SPHERE is **complementary**, not redundant. See
`~/sphere/sphere-vs-fabric.md` for the testbed comparison.

**Decisions:**
- Provider model: third provider mirroring the **Chameleon** integration
  (`*_manager` + `*_executor` + `routes/*` + CLI `commands/*` + contract fakes).
- API surface: **native gRPC** (`grpc.sphere-testbed.net:443`) is the
  **confirmed, primary binding** — it is the transport `mrg` itself uses, and a
  generated Python client has been verified end-to-end against the live portal
  (see "gRPC client — generated & verified" below). The REST grpc-gateway at
  `api.sphere-testbed.net` is **unverified**: every path returns `401` (not
  `404`) for the `mrg` session token across `Bearer` / cookie / `X-Session-Token`
  schemes, so its auth contract is unknown. (This inverts the original
  REST-primary assumption.)
- Auth: Merge **portal token** (obtained via `mrg login` → `mrg whoami -t`, or
  the equivalent REST auth call), stored like Chameleon credentials.
- Scope: phase toward parity with FABRIC/Chameleon (browse resources → create
  experiment → realize/materialize → SSH/exec → unified topology view).

## Live SPHERE endpoints (from the Launch portal)

| Item | Value |
|---|---|
| Launch version | `v1.1.119-sphere` |
| Merge Testbed version | `v1.3.29` |
| **Merge REST API** | `https://api.sphere-testbed.net` |
| **Merge gRPC** | `https://grpc.sphere-testbed.net` |
| Portal / Launch UI | `https://launch.sphere-testbed.net` |

Both API endpoints are **publicly reachable** — no XDC or bastion is required to
call them, which is what makes the clean "third provider" integration viable.
The `mrg` CLI and the web Launch UI are both just clients of `api.sphere-testbed.net`.

## Why this fits LoomAI's architecture

LoomAI already abstracts multiple testbeds:

- **FABRIC** — FABlib direct import (`fablib_manager.py`, `fablib_executor.py`,
  `routes/slices.py`)
- **Chameleon** — OpenStack REST sessions (`chameleon_manager.py`,
  `chameleon_executor.py`, `routes/chameleon.py`, `routes/chameleon_files.py`,
  CLI `commands/chameleon.py`)
- Provider-contract test harness (`contract_fabric.py`,
  `tests/unit/test_contract_provider_fakes.py`)
- Cross-testbed/federation layer (`federated` CLI group, `routes/composite.py`,
  "cross-testbed connection intent")

SPHERE slots into the **Chameleon-shaped seam**: a remote REST API wrapped by a
manager that exposes session/auth + experiment lifecycle, surfaced through routes
and the CLI, and rendered by `graph_builder.py`.

## The Merge API model

```
mergexp (Python topology DSL)  →  Merge REST API (api.sphere-testbed.net)  →  testbed
                                   ↕ grpc-gateway
                                   Merge gRPC (grpc.sphere-testbed.net)

mrg CLI  ──── token auth ────────┘   (mrg and the web UI are both clients)
```

- **Token auth:** `mrg login <user>` creates a time-limited session; the bearer
  token is retrievable via `mrg whoami -t`. A LoomAI manager holds/refreshes this
  token and sets `Authorization: Bearer <token>` on REST calls.
- **Lifecycle verbs:** `new` (create experiment) → `push` (upload model) →
  `realize` (reserve resources) → `materialize` (power on, image, wire network) →
  `dematerialize` / `delete`. `nodes` lists materialized nodes; Merge can also
  emit an **Ansible inventory** from a realized model.
- **Naming:** experiments are `<experiment>.<project>`; every user gets a
  personal project on first portal join.

## Implementation checklist (mirror Chameleon)

| # | File | Job | Mirror of |
|---|------|-----|-----------|
| 1 | (vendored client) | Python client generated from `gitlab.com/mergetb/api` protos / OpenAPI 2.0 spec, or a thin `requests` wrapper over `api.sphere-testbed.net` | `python-chi` / openstacksdk usage |
| 2 | `app/sphere_manager.py` | Token session (`get_session`, `is_configured`, `get_configured_sites`, contract-mode session), experiment lifecycle, node listing | `chameleon_manager.py` |
| 3 | `app/sphere_executor.py` | Provision + per-node command exec (thread-pool offload) | `chameleon_executor.py` |
| 4 | `app/routes/sphere.py`, `app/routes/sphere_files.py` | REST endpoints; register in `routes/__init__.py` | `routes/chameleon*.py` |
| 5 | `backend/cli/loomai_cli/commands/sphere.py` | `loomai sphere ...` command group; register in CLI root | `commands/chameleon.py` |
| 6 | `app/graph_builder.py` | **Generalize the two-way `provider_prefix == "fab" else Chameleon` branches into a provider registry**, add a `sphere` topology serializer (`mergexp` model → LoomAI graph) | existing fab/cham branches (~L1770, 1852, 1861, 2011) |
| 7 | `app/contract_sphere.py` + fakes | Deterministic SPHERE provider for contract tests | `contract_fabric.py`, `test_contract_provider_fakes.py` |
| 8 | `app/settings_manager.py` | SPHERE portal URL(s) + token storage/refresh | Chameleon OIDC/app-cred handling |
| 9 | `ai-tools/shared/{agents,skills}/sphere-*.md` | Agent + skills for SPHERE workflows | `chameleon-manager.md`, federation skills |

## Topology mapping

`mergexp` (Merge's Python topology DSL) is conceptually the same shape as a
FABlib slice — `nodes`, `links`, a topology object. The `graph_builder.py`
serializer is therefore a **translation job**, not a new paradigm. Map:
`mergexp` node → LoomAI node; `mergexp` link/LAN → LoomAI network; provider
prefix `sphere`/`mrg`.

## Cross-testbed angle (the proposal hook)

SPHERE's architecture already includes a **FABRIC L2 link** between the
Northeastern IoT enclave and USC-ISI. Once SPHERE is a LoomAI provider, the
existing `federated` / `composite` machinery is the natural place to express a
SPHERE↔FABRIC stitched experiment: SPHERE supplies contained, hardware-realistic
endpoints (IoT/OT/TEE); FABRIC supplies the programmable, measured WAN. **Caveat
to encode:** bridging a *contained* SPHERE experiment onto FABRIC creates an
egress path, so a merged experiment must reconcile SPHERE's containment tier with
FABRIC's AUP.

## Verified by live run (2026-06-26)

Feasibility is **confirmed end-to-end** against the live SPHERE testbed, project
`fabricsphere`, using the locally-installed `mrg v1.4.17`:

- ✅ **Remote auth** — `mrg login` against `grpc.sphere-testbed.net` succeeds from
  a laptop; `mrg whoami -t` yields a reusable bearer token. (Identity is Ory
  Kratos; password = the SPHERE web-portal identity password.)
- ✅ **Full lifecycle** — `new experiment` → `push --tag` → `realize <rname>.<exp>.<proj> tag <t>`
  → `materialize` all succeed and report `Success` via `--with-status`.
- ✅ **Resource access** — created a **shared** XDC, SSH'd in, then SSH'd into
  experiment node `a` and `ping`'d `b` over the modeled `10.0.0.0/24` link
  (0% loss, ~0.5 ms). Topology fidelity matches the pushed `mergexp` model.
- ✅ **Endpoints public** — `api.sphere-testbed.net` / `grpc.sphere-testbed.net`
  reachable without an XDC/bastion.

### Naming facts learned (important for the manager)

- **Dotted, right-anchored to project:** experiment `<exp>.<proj>`, realization
  `<rname>.<exp>.<proj>`, XDC `<xdc>.<proj>`.
- **Personal vs shared XDC:** in a non-personal/research project (like
  `fabricsphere`) you **must** create XDCs with `-t shared` — personal XDCs are
  rejected (`personal XDCs are allowed only in personal projects`).
- **Node DNS naming:** dataplane = `<node>.exp.<rname>.<exp>.<proj>`; management =
  `<node>.infra.<rname>.<exp>.<proj>`. SSH hop is `mrg xdc ssh -x <xdc>.<proj> <node>`.
- **`realize` grammar:** `mrg realize <rname>.<exp>.<proj> <revision|tag|branch> <ref>`.

### Captured payload schemas (model the client on these)

Real JSON captured from the live run is vendored in the repo at
`backend/tests/fixtures/sphere/{realization,materialization}.json`
(via `mrg ... -j`). Key fields the manager/graph_builder parse:

- **`mrg list realizations -j`** → `results[].realization`:
  `{ complete, id (rname), eid (exp), pid (proj), xhash, nodes, links, infranet, creator, created, expires }`
  - `nodes` is keyed `"<module>/<name>"` (e.g. `"moddeter/a"`); each →
    `node.id`, `node.sockets[].addrs` (e.g. `["10.0.0.1/24"]`).
  - `links` keyed `"a.0~b.0"` → `link.endpoints[].socket.element`, plus
    `segments[].endpoints[]` with `{facility, host, node, mac, phy}`.
- **`mrg show materialization <r>.<e>.<p> --with-status -j`** →
  `{ taskSummary{HighestStatus, FirstUpdated, LastUpdated}, summary{rid, eid, pid, numVirtual, numLinks}, taskStatus{...43-task tree...} }`.
  Poll `taskSummary.HighestStatus == "Success"` for readiness.

## gRPC client — generated & verified (2026-06-26)

Open question #2 (REST vs gRPC) is **resolved in favour of gRPC.** Findings from a
live probe with the `mrg` session token:

- **gRPC reflection** on `grpc.sphere-testbed.net:443` lists 15 `portal.v1`
  services: `Alloc, Artifact, Commission, Communications, Cred, Deploy, Identity,
  KeyValue, Materialize, Model, Realize, Wireguard, Workspace, XDC` (+ internal
  `Mergefs`). Reflection **cannot fully describe** them — the server omits the
  transitive `mergetb/xir/pb/core.proto` descriptor (`File not found:
  mergetb/xir/pb/core.proto`), so the client must be compiled from source protos.
- **Generated Python client** lives in `backend/app/sphere_grpc/` (stubs +
  `client.py` helpers + package loader). Regenerate reproducibly with
  `backend/scripts/gen_sphere_grpc.sh` (clones `gitlab.com/mergetb/{api,xir,
  tech/reconcile}`, `mwitkow/go-proto-validators`, grpc-gateway's openapiv2
  options, and fetches `google/api/*` from googleapis, then runs `grpc_tools`).
- **Auth**: the `mrg whoami -t` Ory session token is accepted as gRPC metadata
  `authorization: bearer <token>` over TLS on :443.
- **Verified live**: `Realize.GetRealizations(summary=True)` returned the
  `world.hello.fabricsphere` realization (2 nodes / 2 links). Offline import +
  contract tests: `backend/tests/unit/test_sphere_grpc_client.py`.
- **Lifecycle method map** (the verbs `sphere_manager` will call):
  - `Model`: `Compile`, `Push`
  - `Realize`: `Realize`, `Relinquish`, `GetRealization(s)`, `GetResources`, `UpdateRealization`
  - `Materialize`: `Materialize`, `Dematerialize`, `RebootMaterialization`, `GetMaterialization(s)[V2]`, `GetMaterializationStatus`, `NewIngress`, `DeleteIngress`
  - `XDC`: `CreateXDC`, `DeleteXDC`, `Attach/DetachXDC`, `GetXDC`, `ListXDCs`, `GetXDCJumpHosts`
- **Dep note**: this added `grpcio` (runtime) + `protobuf` 6.x to the backend;
  fablib (`fabrictestbed-extensions`) and `app.main` import cleanly under
  protobuf 6.33. `grpcio-tools` is a regen-only/dev dep.

## Remaining open questions

1. **Token lifetime & refresh** — sessions are time-limited; the manager needs a
   re-login/refresh path (mirror Chameleon token handling). The portal exposes
   `Identity.Login`/`Logout` — confirm whether re-`Login` is the refresh path vs.
   a token endpoint. Still TBD.
2. ~~REST vs gRPC binding~~ — **resolved: gRPC, and wired.** `sphere_manager.py`
   now drives the portal over gRPC: `_SphereSession` holds a TLS channel + token
   (token from settings, or `Identity.Login` with a configured username/password;
   one re-login retry on `UNAUTHENTICATED`), with high-level methods
   `list_projects`, `create_experiment`, `get_experiment`, `push_model`,
   `list_realizations`, `get_realization`, `realize`, `relinquish`, `materialize`,
   `get_materialization[_status]`, `dematerialize`. Responses are converted with
   `MessageToDict` (json_name casing — reproduces the `mrg -j` fixtures exactly, so
   the parse helpers work on gRPC + CLI output alike). `_ContractSphereSession`
   serves the captured fixtures for offline/contract runs. `_MrgCliBackend` remains
   only as a documented fallback. Verified live (`list_projects`,
   `list_realizations`, `get_materialization`) against `fabricsphere`. The REST
   gateway is only worth revisiting if its auth contract surfaces from the mergetb
   OpenAPI spec.
   - **DONE (CLI + REST + graph):** `settings_manager` now has a `sphere` block
     (`enabled/grpc_endpoint/grpc_port/api_endpoint/username/password/token/
     default_project`) + accessors (`is_sphere_enabled`, `get_sphere_settings`,
     `get_sphere_default_project`, `is_sphere_configured`). `app/routes/sphere.py`
     exposes `/api/sphere/{status,projects,experiments,realizations[/{e}/{r}[/graph]],
     materializations[/{e}/{r}]}` (gated by `sphere.enabled` like Chameleon;
     blocking gRPC offloaded via `asyncio.to_thread`), registered in `main.py`.
     CLI `loomai sphere {status,projects,realizations,realization,graph,realize,
     relinquish,materialize,materialization,dematerialize}`
     (`backend/cli/loomai_cli/commands/sphere.py`). `graph_builder.build_sphere_realization_graph`
     converts a realization → the standard `{nodes,edges}` Cytoscape envelope
     (`sphere-cluster`/`sphere-node`/`sphere-net`/`sphere-mgmt-net` classes) — a
     dedicated serializer, not a full provider-registry rewrite. Verified live
     end-to-end through the HTTP stack against `fabricsphere` (status/projects/
     realizations/graph/materialization). Tests: `test_sphere_routes.py` (+ manager/
     client suites) — 17 sphere tests, full unit suite 641 passing.
     - **GOTCHA:** `GetRealization` (singular) wraps as `{result:{realization,…}}`
       whereas `GetRealizations` (plural) returns `results[].realization` — the
       graph route unwraps both shapes.
   - **DONE (XDC management + in-browser node SSH):** `_SphereSession` now wraps
     the `XDC` service (`list/get/create/delete/attach/detach_xdc`,
     `get_xdc_jump_hosts`) and the `Cred` service (`get_user_ssh_keys`,
     `get_user_ssh_cert`), plus `resolve_node_ssh` which assembles the full SSH
     path (portal keypair + signed cert + jump-host chain + XDC fqdn + node
     management DNS `<node>.infra.<rname>.<exp>.<proj>`). Routes:
     `/api/sphere/xdcs` (list/create), `/api/sphere/xdcs/{xdc}` (delete),
     `/api/sphere/xdcs/{xdc}/{attach,detach}`, `/api/sphere/jump-hosts`. CLI:
     `loomai sphere xdc {list,create,delete,attach,detach}` and `loomai sphere
     ssh`. `routes/terminal.py` adds a `type="sphere"` terminal that runs an
     `ssh -o CertificateFile=… -o ProxyJump=<jump>,<xdc> <user>@<node-dns>` in a
     server-held PTY (no `mrg` binary needed) — equivalent to `mrg xdc ssh -x
     <xdc>.<proj> <node>` and persistent across browser reloads. Frontend
     `SphereView` exposes an XDC selector (create/attach) and a per-node
     **Connect** button that opens the terminal in the bottom panel.
   - **Still TODO (deeper parity):** `sphere_executor.py` (provision + per-node
     non-interactive exec), `contract_sphere.py` (a standalone contract-fakes
     module — the `_ContractSphereSession` fixtures cover contract runs for now),
     and model push/compile UX. The node-SSH `ProxyJump` chain (jump host → XDC →
     node) is encoded from the documented model and the gRPC primitives but has
     not yet been re-verified live end-to-end through the WebUI PTY.
3. **Containment representation** — decide whether LoomAI surfaces SPHERE's
   security-policy tier (standard / expanded / containment) in the UI/CLI.

## WebUI / CLI feature set — full integration (PR #50)

SPHERE was brought to parity with the FABRIC/Chameleon views. Shipped on branch
`loomai-sphere-integration` (PR #50 → main) and deployed to prod GKE as
`kthare10/loomai:0.7.4a` (helm release `loomai`).

### Architecture
- Native **gRPC** to `grpc.sphere-testbed.net:443` (vendored stubs in
  `backend/app/sphere_grpc/`); the REST gateway `api.sphere-testbed.net` is NOT used.
- Auth: **username/password** (CILogon) via `Identity.Login`
  (`settings.sphere.{username,password}`). The portal `token` field was removed
  from the UI (SPHERE has no token-create flow). `get_token()` prefers
  credentials over a stale token; `_invoke()` re-auths on `UNAUTHENTICATED` **and**
  `PERMISSION_DENIED`.
- Settings can be seeded from env (`SPHERE_ENABLED/USERNAME/PASSWORD/DEFAULT_PROJECT/…`);
  env secrets are NOT persisted to `settings.json` on save.

### Node access model (key gotcha)
Experiment nodes are reachable only through an **XDC** (Merge-hosted jump
container). SSH chain is **jump → XDC → node**, generated as an ssh config whose
`Host *` block applies relaxed host-key checking to *every* hop (else jump hops
fail with "Host key verification failed"). Critical detail: the XDC `fqdn`
(e.g. `x0-fabricsphere.xdc.sphere-testbed.net`) is the **Jupyter ingress**, NOT
the SSH host — the SSH-reachable XDC host via the jump is the fqdn's **leftmost
label** (`x0-fabricsphere`). Node management DNS = `<node>.infra.<rname>.<exp>.<proj>`.
Uses the portal-issued keypair + signed cert (Cred service) — no `mrg` binary
needed. XDC names in gRPC must be the **bare** name (`^[a-z][a-z0-9]{0,62}$`),
not the qualified `<name>.<project>` form.

### Features (ribbon: Realizations · Topology · Storage · Project Inventory · Map · Notebook)
- **Experiment Builder** (editor, tabbed): Experiment → Topology → Model →
  Realize → Materialize → XDC. Generates a `mergexp` model from a node/link form
  (Compile + Push) so users who don't author models can run experiments.
  Experiment creation lives in the top ribbon (+ New Experiment + realization
  selector).
- **Node SSH** terminal through the XDC chain (Connect button / right-click a
  topology node); server-held PTY that persists across reloads.
- **XDC management** (create/attach/detach/delete + readiness) in the editor's
  XDC tab.
- **Storage**: dual-panel file manager (LoomAI container ↔ node) with transfer
  arrows; node side over scp through the XDC chain.
- **Project Inventory** (`GetFacilities`/`GetResources`/`GetPools`) + usage-by-project
  pie charts (chart.js). **Map** (enclaves, Leaflet). **Notebook** launches the
  XDC's JupyterLab in a new tab.
- Topology wraps resources in a slice-box (FABRIC-style) for federated-view
  compatibility.

### Security / performance hardening (post-review)
- Blocked ssh-config injection: validate `node/experiment/realization/xdc/project`
  and sanitize every value written into the ssh config (a newline previously
  allowed an injected local `ProxyCommand`).
- One-shot file ops clean up their temp key/cert/config dirs (private keys were
  leaking to `/tmp`); cert perms 0600.
- DoS caps: read 5 MB (`head -c`), upload 5 GB, folder download streams tar to disk.
- Perf: SSH `ControlMaster` multiplexing; per-session cache (5 min TTL) of SSH
  material so file ops don't repeat ~4 gRPC calls; concurrent inventory RPCs;
  memoized usage charts.

### Deploy facts
The SPHERE code lives in the **single-user image** `kthare10/loomai` (root
`Dockerfile`), NOT the hub (`kthare10/loomai-hub`). Deploy =
build/push `kthare10/loomai:<tag>` → bump `singleuser.image.tag` in
`helm/loomai/values-gke-https.yaml` → `helm upgrade loomai -n loomai` → **restart
`deployment/loomai-hub` + `daemonset/loomai-image-puller`** so new user pods pull
the new image. `values-gke-https.yaml` is gitignored (holds the CILogon secret +
Core API token).

**Build gotchas (macOS → GKE):** `docker build` on Apple Silicon defaults to
**arm64**, but GKE nodes are **amd64** → user pods fail `ErrImagePull`
("no match for platform"). Always build with
`docker buildx build --platform linux/amd64 --provenance=false -t kthare10/loomai:<tag> --push .`
(`--provenance=false` avoids a manifest list with an `unknown/unknown`
attestation that some containerd versions mis-resolve). If a tag was ever pushed
with the wrong arch, the GKE node's CDN edge can keep serving the stale manifest
for that tag — **bump to a fresh tag** rather than reusing it (e.g. `0.7.4b` →
`0.7.4c`). `VERSION`/`package.json` can stay fixed (e.g. `0.7.4`) while only the
image tag advances.

### Experiment packaging — reproducible weaves (`sphere-experiment-v1`)
The builder's **Package** tab (`POST /api/sphere/experiments/{exp}/package`,
`app/sphere_weave.py`) saves a live experiment as a LoomAI weave under
`my_artifacts/<dir>/` so others can recreate it and it can be published to the
FABRIC Artifact Manager. Bundle:
- `model.py` — mergexp source regenerated from **`get_realization_topology`**
  (see below), not the stored model.
- `experiment.py` — lifecycle driver: on Run it calls the local SPHERE API
  (create → push → realize → materialize, polling state); Stop dematerializes +
  relinquishes. Uses stdlib `urllib` against `127.0.0.1:8000`. (It does **not**
  create/attach an XDC — that stays a shared, manually-attached resource so we
  don't proliferate one XDC per weave.)
- `weave.sh` — Run/Stop orchestrator, same contract as FABRIC/Chameleon weaves.
- `scripts/*.sh` — author per-node setup scripts (`target` = node or `all`);
  filenames validated (no path traversal).
- `analysis.ipynb` — generated by `gen_notebook`: self-documenting (title,
  data-flow diagram, node-role table) + cells to **connect** (SSH w/ bare-name →
  full-DNS `<node>.infra.<rid>.<exp>.<proj>` fallback), **deploy** the scripts,
  **verify**, **analyze** Suricata `eve.json`, **visualize** (matplotlib/networkx
  — topology, alerts by signature/category, severity, top talkers, attack graph,
  timeline; libs `pip`-installed via `subprocess`, no `%` magics), and a
  closed-loop **IPS** cell that `nft`-blocks the top attacker on the gateway.
- `weave.json` — `format: sphere-experiment-v1`; human **title** (`name`) is
  decoupled from the stable on-disk `dir_name`; `description`/`description_short`
  (≤255) / `description_long` (HTML) feed the publish dialog; tags must come from
  the Artifact Manager's controlled vocabulary (`loomai:weave`, `experiment
  pattern`, `sphere` OK; `ids`/`edge`/etc. are rejected). A `sphere` block holds
  experiment/realization/project/network/nodes/links/scripts/notebook.

**`get_realization_topology` (the model-capture fix):** an experiment's pushed
models are **content-hash revisions with no `compileTime`/ordering**, so picking
"the latest model" via `get_experiment_model` was non-deterministic and could
silently revert the topology (e.g. drop a node). Packaging instead reads the
**materialized realization** (`realization.nodes`/`links`, with per-socket
`endpoint.element`→link-id addr mapping) — the unambiguous deployed truth —
falling back to the model only when unrealized.

**XDC as a file target:** the XDC is a *separate container* from LoomAI storage,
so packaging alone doesn't put files where its JupyterLab serves. The sentinel
node `__xdc__` (`resolve_xdc_ssh` + an XDC-only ssh-config) makes the **Storage**
browser and the **Notebook → Send weave → XDC** button target the XDC's own home;
`POST /api/sphere/xdcs/{xdc}/seed-weave` copies a weave's notebook+scripts there.
The Notebook tab lists every XDC with the realization it's attached to (parsed
from each XDC's `materialization`), needing no realization selection.

**`edgeids-weave` (shipped as a default artifact** in
`backend/default_artifacts/`, auto-seeded into `my_artifacts/` on startup):** a
4-node IDS/IPS lab on `moddeter` — `edge` (compromised: recon scans → web
exploits → SSH brute force → DNS-tunnel exfil), `edge2` (benign baseline), `gw`
(victim web + nftables + tc traffic mirror), `mon` (Suricata, categorized rules).
Facility note: `fabricsphere` is entitled **only to `moddeter`** (probed
2026-06-28: embed/sphereiot/iotbeta/iotdev/cps/generalserver/gpuml all denied);
true RPi/IoT edge needs a SPHERE admin to add the project to an edge pool.

Lab build gotchas (baked into the scripts): force-IPv4 apt + don't hijack the
default route (nodes reach apt via their management iface, experiment LANs are
isolated); `curl --path-as-is` (traversal); Suricata `http.uri.raw` rule +
`midstream`/`async-oneside` (the mirror is one-directional); `systemctl restart`
(not just `enable --now`); threaded victim web server (so a scan flood can't
starve the benign device).

### Next / roadmap
- **Marketplace (LibrariesView) should surface SPHERE artifacts** — list/filter
  published `sphere-experiment-v1` weaves as a first-class category (alongside
  FABRIC/Chameleon), so users can browse + download SPHERE labs from the
  Marketplace, not just My Artifacts.
- Realize/Materialize action buttons could chain into one "Deploy".
- Backend file-manager/terminal SSH (jump → XDC → node) can intermittently hit
  "Session open refused by peer" on a stale mux; the in-XDC notebook path is the
  reliable one today.

### Known follow-ups (deferred)
- Routes have no per-request auth (app-wide "trusted network" model, same as the
  FABRIC/Chameleon routes).
- Terminal ssh-config temp dirs persist for the session lifetime (the file-op
  leak is fixed).
- Host-key checking is disabled on hops; `ca_host_pubkey` is fetched and could be
  pinned via `@cert-authority`.

## References

- Testbed comparison: `~/sphere/sphere-vs-fabric.md`
- Merge API repo (protobuf / OpenAPI): `https://gitlab.com/mergetb/api`
- MergeTB docs: experiment automation, CLI reference, dev overview, end-to-end tour
- Chameleon integration precedent: `docs/CHAMELEON_SPEC.md`
