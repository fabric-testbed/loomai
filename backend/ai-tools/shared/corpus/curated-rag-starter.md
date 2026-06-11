---
id: curated-rag-starter
name: curated-rag-starter
asset_type: runbook
audience: end-user
description: Starter curated RAG map covering FABlib, weaves, Chameleon/OpenStack, Federated workflows, troubleshooting, and LoomAI development guidance
domains:
  - fabric
  - fablib
  - weave
  - chameleon
  - openstack
  - federated
  - troubleshooting
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
  - curated rag
  - fablib example
  - example weave
  - chameleon openstack
  - federated workflow
  - troubleshooting runbook
  - loomai development
source_paths:
  - ai-tools/fablib-examples/INDEX.json
  - backend/default_artifacts/Hello_FABRIC/weave.json
  - backend/default_artifacts/Prometheus_Grafana_Monitor/weave.json
  - backend/default_artifacts/Chameleon_SSH_Slice/weave.json
  - ai-tools/shared/skills/debug.md
  - ai-tools/shared/skills/manage-federated-slice.md
  - ai-tools/shared/skills/manage-chameleon-slice.md
  - ai-tools/shared/skills/develop-loomai-feature.md
generated_outputs:
  - rag:curated
freshness: review-on-change
---

# Curated RAG Starter Corpus

This starter map records the first curated corpus pass. The selected scope is
all categories: FABlib examples, example weaves, Chameleon/OpenStack patterns,
Federated Slice workflows, troubleshooting runbooks, and LoomAI development
guidance.

The RAG index should prefer these sources when users ask for working examples,
known-good code patterns, or debugging guidance. Future additions should keep
the same metadata style: concrete source paths, short trigger phrases, domain
tags, and a review-on-change freshness policy.

## FABlib Patterns

Use the indexed FABlib examples as the primary code corpus. The highest-value
starter paths are:

- `ai-tools/fablib-examples/basics/hello_fabric.py`
- `ai-tools/fablib-examples/slice_lifecycle/create_slice.py`
- `ai-tools/fablib-examples/slice_lifecycle/modify-add-node-network.py`
- `ai-tools/fablib-examples/slice_lifecycle/delete_slice.py`
- `ai-tools/fablib-examples/networking/create_l2network_basic_auto.py`
- `ai-tools/fablib-examples/networking/create_l3network_fabnet_ipv4_auto.py`
- `ai-tools/fablib-examples/networking/get_fabnet_ip_by_mac.py`
- `ai-tools/fablib-examples/ssh_and_config/execute_commands.py`
- `ai-tools/fablib-examples/experiments/slice_submit_patterns.py`
- `ai-tools/fablib-examples/experiments/node_networking_patterns.py`

These examples should answer questions about create/submit/modify/delete slice
flows, L2/L3 networks, post-boot execution, MAC-based IP lookup, and safe FABlib
polling patterns.

## Example Weaves

Use repo default artifacts as canonical starter weaves before user storage has
any local artifacts:

- `backend/default_artifacts/Hello_FABRIC/weave.json`
- `backend/default_artifacts/Hello_FABRIC/hello_fabric.py`
- `backend/default_artifacts/Prometheus_Grafana_Monitor/weave.json`
- `backend/default_artifacts/Prometheus_Grafana_Monitor/prom_grafana_monitor.py`
- `backend/default_artifacts/Chameleon_SSH_Slice/weave.json`
- `backend/default_artifacts/Chameleon_SSH_Slice/chameleon_ssh_slice.py`

These should cover a simple FABRIC slice, a monitoring-oriented weave, and a
Chameleon SSH-ready workflow. Prefer them when users ask for complete artifacts
instead of isolated FABlib snippets.

## Chameleon And OpenStack Patterns

Use these sources first for Chameleon-specific answers:

- `ai-tools/fablib-examples/chameleon/openstack_api_patterns.py`
- `ai-tools/fablib-examples/networking/chameleon_fabnetv4_route_metrics.py`
- `ai-tools/shared/skills/query-chameleon.md`
- `ai-tools/shared/skills/create-chameleon-lease.md`
- `ai-tools/shared/skills/manage-chameleon-slice.md`
- `ai-tools/shared/skills/deploy-chameleon.md`
- `ai-tools/shared/skills/chameleon-api.md`

The main retrieval intents are Blazar leases, Nova instances, Neutron networks,
security groups, floating IPs, FABNetv4 route metrics, and LoomAI Chameleon
slice membership actions.

## Federated Workflows

Use these sources first for cross-testbed workflows:

- `ai-tools/fablib-examples/experiments/federated_slice_weave_pattern.py`
- `ai-tools/shared/skills/manage-federated-slice.md`
- `ai-tools/shared/skills/manage-composite.md`
- `ai-tools/shared/skills/extend-loomai-federation.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`

These should answer questions about FABRIC members, Chameleon members, generic
member schema direction, FABNetv4 connection intent, Facility Port L2
connection intent, and how Federated views delegate provider lifecycle to the
provider slice editors.

## Troubleshooting Runbooks

Use these sources first for debugging and recovery:

- `ai-tools/shared/skills/debug.md`
- `ai-tools/shared/skills/ssh-config.md`
- `ai-tools/shared/skills/interact-slice.md`
- `ai-tools/shared/skills/verify-loomai-change.md`
- `ai-tools/shared/skills/fix-loomai-ui-regression.md`
- `ai-tools/fablib-examples/ssh_and_config/execute_commands.py`
- `ai-tools/fablib-examples/experiments/ping_mesh_connectivity.py`
- `ai-tools/fablib-examples/experiments/network_performance_test.py`

The first runbook themes are SSH failures, slices stuck in transitional states,
post-boot failures, Chameleon lease/instance failures, topology refresh/cache
issues, and regression triage after UI or backend changes.

## LoomAI Development Guidance

Use these sources for agents that are changing LoomAI itself:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/AGENTS.md`
- `docs/AI_ASSET_FORMAT.md`
- `docs/AI_ASSET_INVENTORY.md`
- `docs/FEATURE_PROPAGATION.md`
- `ai-tools/shared/skills/develop-loomai-feature.md`
- `ai-tools/shared/skills/update-loomai-ai-assets.md`

Keep this guidance distinct from end-user experiment assistance. Only surface
development guidance when the user is asking to change LoomAI, improve AI
assets, run tests, or update repo documentation.
