# Roadmap

Project status and planned work for fabric-webgui.

## Done

Major features completed (see `docs/TEAM_STATUS.md` for details):

- **Core GUI**: Three-panel topology editor, Cytoscape.js graph, Leaflet map, tabular sliver view
- **Slice lifecycle**: Create, submit, modify, refresh, delete, clone, export/import, renew, archive
- **Template system**: Weaves (orchestrated topologies), VM templates, recipes
- **Weave workflow**: Python lifecycle scripts (`start`/`stop`/`monitor`), `weave.sh` orchestrator, background runs with log streaming, failure monitoring, graceful shutdown (SIGTERM trap)
- **Artifact marketplace**: Browse, publish, download artifacts from FABRIC Artifact Manager
- **AI tools**: 6 integrated tools — LoomAI (chat), Aider (web IDE), OpenCode (terminal), Crush (TUI), Claude Code (CLI), Deep Agents (LangChain)
- **AI agents & skills**: 8 agent personas + 28 skills for in-container AI tools
- **Site resolution**: `@group` co-location tags, host-level feasibility checks, auto-assign
- **File management**: Dual-panel browser (container storage + VM SFTP), file editor
- **Terminal**: Local container shell, SSH to VMs via bastion, FABlib log tail
- **Monitoring**: Per-node `node_exporter` install, Prometheus scraping, rolling time-series
- **Guided tours**: 10 interactive walkthroughs with completion checks
- **Help system**: Tooltips, right-click context help, searchable help page
- **Performance optimization**: 3 rounds — lazy loading, React.memo, connection pooling, FABlib thread pool, stale-while-revalidate caching, visibility-aware polling
- **Dark/light mode**: CSS custom properties with `[data-theme="dark"]` overrides
- **Multi-platform builds**: `linux/amd64` + `linux/arm64` Docker images
- **Deployment options**: Docker Compose, Tailscale, LXC/Proxmox template

## In Progress

- **weave-workflow branch**: Artifacts publish flow, card UI cleanup, AI tools update
- **Help documentation update** — update help entries and searchable docs to reflect current features (6 AI tools, AllSliversView, artifact marketplace, JupyterLab integration, boot config)
- **Guided tours update** — revise and extend the 10 interactive walkthroughs to cover new views (AllSliversView, artifact marketplace, JupyterLab) and updated workflows

## Gaps & TODOs

### Testing
- No CI/CD test pipeline — only a `publish-to-public.yml` workflow for mirroring
- No test coverage reporting configured
- No frontend unit tests (only Playwright E2E)
- Missing WebSocket tests (TODO comments in test files):
  - WebSocket proxy tests
  - SSE streaming tests
  - Tool-calling loop tests
  - Terminal WebSocket tests

### AI Tool Configuration & Validation (Audited 2025-03-22)
- **All 6 tools have correct config propagation** — API key and server URL injected via env vars (`OPENAI_API_KEY`, `OPENAI_BASE_URL`) for Aider, OpenCode, Crush, Deep Agents; LoomAI reads settings directly; Claude Code uses Anthropic's own key
- **Crush and Deep Agents are lazy-installed** — npm (`@charmland/crush`) and pip (`deepagents-cli`) packages install on first launch via ToolInstallOverlay; both packages verified available in registries
- **Runtime validation needed** — end-to-end test of Crush and Deep Agents after lazy-install to confirm they connect to FABRIC AI and produce responses; currently only config-level verified

### AI/LLM Provider Configuration
- **NRP/Nautilus LLM integration** — use NRP's hosted LLM service (`ellm.nrp-nautilus.io`) as a built-in provider option alongside the FABRIC AI server (`ai.fabric-testbed.net`)
- **Arbitrary LLM providers via API keys** — configure self-hosted or commercial LLM providers (OpenAI, Anthropic, local Ollama, vLLM, etc.) by supplying an API key and base URL in settings
- **Automatic AI tool configuration** — when the LLM provider is changed in settings, automatically propagate the new endpoint/API key to all 6 AI tools (LoomAI, Aider, OpenCode, Crush, Claude Code, Deep Agents) without manual per-tool configuration
- **LLM connection health tests** — verify API key validity, model availability, and response capability before and after configuration changes; surface connection status in the AI settings panel and add automated tests to the test suite

### Documentation
- README mentions 3 AI tools but there are 6
- No CONTRIBUTING guide
- No API reference beyond ARCHITECTURE.md endpoint tables

### Infrastructure
- No automated test pipeline in CI (tests run locally only)
- No staging environment
- No health check monitoring for deployed instances

### Resource Scheduling & Future Reservations
- **Resource availability calendar** — query when resources will become available if currently unavailable, showing projected free times based on existing slice leases and expiration schedules
- **Future reservation & auto-execution** — create slices/weaves that reserve resources for a future time window and automatically submit slices and manage experiment execution when that time arrives
- **Next-available-time finder** — find the earliest time a specific slice topology (sites, cores, RAM, GPUs, etc.) can be fully instantiated, accounting for all resource constraints
- **Alternative resource suggestions** — when requested resources are unavailable, suggest equivalent alternative sites or resource configurations that could enable earlier experiment execution

### CLI Tool
- **`loomai` CLI** — standalone command-line interface for managing slices, weaves, and artifacts without the web GUI
  - Slice operations: list, create, submit, modify, delete, renew, status, SSH
  - Weave operations: list, run, stop, logs, publish
  - Artifact operations: browse, search, download, publish to FABRIC Artifact Manager
  - Reuses backend logic (FABlib manager, slice serializer, run manager, artifact client)
  - Config via `FABRIC_CONFIG_DIR` (same as backend) or `~/.loomai/config`
  - Output formats: human-readable tables, JSON, YAML for scripting
  - AI chat: interactive or one-shot chat requests to the LoomAI AI tool (same backend as web GUI)
  - Shell completions (bash, zsh, fish)

### Chameleon Cloud Integration
Chameleon Cloud ([chameleoncloud.org](https://www.chameleoncloud.org/)) is a configurable experimental environment for large-scale cloud research. Docs: [chameleoncloud.readthedocs.io](https://chameleoncloud.readthedocs.io/en/latest/). Artifact sharing via Trovi: [trovi.chameleoncloud.org](https://trovi.chameleoncloud.org/dashboard/artifacts?q=fabric).

- **Cross-testbed slices** — create slices that include resources on both FABRIC and Chameleon Cloud, enabling experiments that span both infrastructures
- **Server & network management** — start, stop, and configure Chameleon servers (bare-metal and VM) and networks from the Loomai interface
- **Resource calendar & reservations** — query Chameleon's resource availability calendar and submit reservation requests (leases) for compute, network, and storage resources
- **Unified topology visualization** — integrate Chameleon nodes and networks into the existing Cytoscape.js graph, Leaflet map, and tabular sliver views alongside FABRIC resources, with visual distinction between testbeds
- **Trovi artifact integration** — browse, search, and import artifacts from Chameleon's Trovi artifact manager; publish cross-testbed artifacts that reference both FABRIC and Chameleon resources

### Distributed Storage & File Systems
- **Mount user's distributed filesystem in Loomai container** — automatically mount the user's FABRIC distributed filesystem (e.g. CephFS, POSIX mount) inside the Loomai Docker container so files are accessible to all tools, JupyterLab, and the file manager
- **Mount distributed filesystem in VMs over FABNetv4** — configure selected or all slice VMs to mount the user's distributed filesystem over the FABRIC data plane (FABNetv4), enabling shared storage across experiment nodes
- **WebUI distributed filesystem browser** — add a file manager view to the Loomai WebUI for the user's distributed filesystem with drag-and-drop upload/download, allowing users to move files between their local machine, container storage, and distributed filesystem
- **WebUI S3 bucket browser** — add a file manager view for FABRIC's distributed S3 buckets with drag-and-drop upload/download, enabling users to store and retrieve experiment data, datasets, and artifacts in S3-compatible object storage
- **Example artifacts for distributed storage** — create example weaves, recipes, and VM templates that demonstrate how to mount the user's distributed filesystem or S3 buckets from within experiment VMs, covering common use cases (shared datasets, experiment output collection, cross-node file sharing)

### Tailscale Network Integration
- **Auto-join VMs to Tailscale** — settings to upload a Tailscale auth key and automatically install/configure Tailscale on all or selected slice VMs during boot config, joining them to the user's Tailscale network for direct private connectivity without bastion SSH
- **Loomai container Tailscale join** — settings to enable the Loomai container itself to join the user's Tailscale network, providing direct connectivity from the container to VMs and other Tailscale nodes without routing through the FABRIC bastion
- **Tailscale-preferred transport** — when Tailscale connectivity is available, prefer it for SSH, SCP, and file transfers over the bastion-proxied path; automatically detect Tailscale IPs on VMs and use them for terminal sessions, boot config execution, and file manager SFTP operations
