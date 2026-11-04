---
id: mcp-servers
name: mcp-servers
asset_type: runbook
audience: end-user
description: MCP servers LoomAI and its in-container harnesses talk to — FABRIC infrastructure metrics, FABRIC reports, and the local LoomAI harness — with routing rules and worked examples
domains:
  - fabric
  - mcp
  - metrics
  - monitoring
  - observability
  - reports
  - loomai
tools:
  - loomai
  - claude-code
  - codex
  - opencode
  - aider
  - crush
  - deepagents
  - antigravity
  - jupyter-ai
triggers:
  - mcp server
  - infrastructure metrics
  - fabric metrics
  - site cpu load
  - node temperature
  - link traffic
  - port traffic
  - rack utilization
  - dataplane throughput
  - grafana dashboard
  - prometheus query
  - is the site busy
  - fabric reports
source_paths:
  - backend/app/mcp_registry.py
  - backend/app/mcp_client.py
  - backend/app/routes/ai_mcp.py
  - backend/app/routes/metrics.py
generated_outputs:
  - rag:curated
freshness: review-on-change
---

# MCP Servers LoomAI Talks To

`backend/app/mcp_registry.py` is the single source of truth. Every harness
config (`opencode.json`, `.mcp.json`, `.opencode/mcp-scripts/*.sh`) and the
Configure → MCP Servers page is generated from it. Three servers are
registered today.

| Server | Transport | Auth | What it answers |
|---|---|---|---|
| `fabric-metrics` | HTTPS (`https://infrastructure-metrics-mcp.fabric-testbed.net/mcp`) | FABRIC bearer token | Live FABRIC **infrastructure** health — node CPU/memory/disk/network/temperature, switch link and port traffic |
| `fabric-reports` | HTTPS (`https://reports.fabric-testbed.net/mcp`) | FABRIC bearer token, **staff/admin only** | Usage statistics, project membership, resource utilization reports |
| `loomai-harness` | local stdio (`python3 -m app.harness_mcp_server`) | none | LoomAI's own REST API: slices, weaves, recipes, SSH |

Do **not** use a `fabric-api` MCP server. It is not available in the container;
the built-in FABlib tools cover the same ground faster.

## FABRIC Infrastructure Metrics — when to reach for it

Use `fabric-metrics` when the question is about **FABRIC's own infrastructure**:

- "Is `ncsa` busy right now?" / "What is the CPU load at `cern`?"
- "Are any nodes running hot?" (temperature)
- "How much traffic is flowing between `ncsa` and `cern`?" (link traffic)
- "Which switch port is saturated?" (port traffic)
- "Is the link between two racks up?" (link status)
- "Which racks report node data at all?" (`list_sites`)

Do **not** use it for metrics *inside a user's own slice*. Per-VM CPU/memory
from a provisioned node comes from LoomAI's monitoring stack (`node_exporter`
installed per node, `monitoring_manager.py`), not from this server.

The server also does **not** accept PromQL. It runs the fixed queries that
FABRIC's Grafana dashboards already define. The contract is: pick a **topic**,
pick a **variant** for that topic, pass the topic's parameters.

## Routing rule — always list before you query

1. Call `list_metric_topics` (LoomAI) / `fabric_metrics_list_topics` (harnesses).
   It returns every topic, its variants, its source dashboard, and its
   parameters.
2. Pick the topic and a variant **exactly as that listing spells them**. Never
   invent a topic or a variant name, and never derive a tool name from a
   variant.
3. If you need a concrete parameter value — a node name, a switch device, an
   interface — call `list_metric_param_options` first. It resolves live values.
4. Call `query_infrastructure_metrics` with the topic, variant, and args.

Topics: `cpu`, `memory`, `memory_internals`, `disk`, `filesystem`, `network`,
`sockets`, `netstat`, `system`, `time`, `temperature`, `link_status`,
`link_traffic`, `port_traffic`, plus the helpers `list_topics`,
`list_param_options`, `list_sites`.

Two topic pairs are easy to confuse:

- RAM, swap, cache, page faults and the OOM killer are in `memory`. Slab,
  vmalloc, huge pages, bounce, NFS and direct-map are in `memory_internals`.
- Uptime, processes, scheduler, systemd, entropy and file descriptors are in
  `system`; softnet is in `network`; the OOM killer is in `memory`.

Node topics take `node` — which accepts a **rack/site code** (`amst`, `cern`,
`ncsa`, `cien`) to cover every node at that site, not only a single hostname.
Link topics take `src_rack`/`dst_rack`. All topics accept optional `start`,
`end`, `step` and `mode` for range queries.

## Worked examples — LoomAI assistant

```
list_metric_topics()
query_infrastructure_metrics(topic="list_sites")
query_infrastructure_metrics(topic="cpu", variant="load_average", args={"node": "ncsa"})
query_infrastructure_metrics(topic="temperature", variant="max_per_node", args={"node": "cern"})
query_infrastructure_metrics(topic="link_traffic", variant="throughput",
                             args={"src_rack": "ncsa", "dst_rack": "cern"})
list_metric_param_options(topic="port_traffic", param="device")
```

## Worked examples — in-container harnesses

In OpenCode, Claude Code and the other harnesses the same server appears under
its raw tool names:

```
fabric_metrics_list_topics()
fabric_metrics_cpu(variant="load_average", node="ncsa")
fabric_metrics_link_traffic(variant="throughput", src_rack="ncsa", dst_rack="cern")
fabric_metrics_list_param_options(topic="fabric_metrics_port_traffic", param="device")
```

## Related LoomAI surfaces

- `GET /api/ai/mcp/servers` — registry + live reachability, tool counts.
- `GET /api/ai/mcp/servers/{name}` — full tool list with input schemas.
- `POST /api/ai/mcp/servers/{name}/probe` — force a fresh probe.
- Configure → **MCP Servers** in the WebUI shows all of the above.
- `GET /api/metrics/site/{site}` and `/api/metrics/link/{a}/{b}` are LoomAI's
  own lightweight Prometheus proxy — narrower than the MCP server (load average
  and dataplane bits only), but usable with no token.

## Known limitation — oversized bearer token

FABRIC id_tokens are ~8.6 KB. If the metrics server's ingress still uses nginx's
default `large_client_header_buffers` of 8k, authenticated calls fail with
`400 Request Header Or Cookie Too Large` before reaching the application. Tool
*discovery* still works unauthenticated, so the server shows as reachable while
every tool call errors. The fix is server-side: raise
`large_client_header_buffers` (e.g. `4 32k`). LoomAI surfaces this case with an
explicit message rather than a generic 400.
