# Agents & AI Tools

Two distinct agent systems operate in this project: **Claude Code slash commands** (development-time) and **in-container AI tool agents** (runtime).

## Claude Code Slash Commands

11 slash commands available for development work. These are defined as skills in `ai-tools/claude-code/skills/`.

| Command | Role | Key Files |
|---------|------|-----------|
| `/lead <goal>` | Team lead — breaks goals into tasks, delegates to specialists | `docs/TEAM_STATUS.md` |
| `/backend <task>` | Backend specialist — FastAPI, FABlib, Python | `backend/app/` |
| `/frontend <task>` | Frontend specialist — React, TypeScript, CSS | `frontend/src/` |
| `/graph <task>` | Graph/visualization — Cytoscape.js, Leaflet, graph_builder | `backend/app/graph_builder.py`, `frontend/src/components/CytoscapeGraph.tsx` |
| `/libraries <task>` | Artifacts — templates, recipes, seeding | `backend/app/routes/templates.py`, `backend/app/routes/artifacts.py` |
| `/artifacts <task>` | FABRIC Artifact Manager — browse, search, get, publish | `backend/app/routes/artifacts.py` |
| `/infra <task>` | Infrastructure — Docker, builds, deployment, nginx | `Dockerfile`, `docker-compose*.yml`, `build/` |
| `/ai-eval [mode] [target]` | In-container AI tool optimization | `backend/ai-tools/` |
| `/test [target]` | Run backend/frontend tests | `backend/tests/`, `frontend/e2e/` |
| `/test-guide <question>` | Test suite specialist — write, debug, extend tests | `backend/tests/`, `frontend/e2e/` |
| `/update_skills` | Review and optimize Claude Code skills | `ai-tools/claude-code/skills/` |

### Agent Coordination

Agents share state through `docs/TEAM_STATUS.md`, which tracks:
- **Current Goal**: The active objective being worked on
- **Active Work**: Tasks currently in progress
- **Completed**: Finished work items with details
- **Blockers**: Issues preventing progress

## In-Container AI Tool Agents

8 agent personas defined in `backend/ai-tools/shared/agents/`. These are available to the in-container AI tools (LoomAI, Aider, OpenCode, Crush, Deep Agents) for FABRIC-specific expertise.

| Agent | File | Expertise |
|-------|------|-----------|
| Fabric Manager | `fabric-manager.md` | Slice lifecycle, resource management, FABlib operations |
| Network Architect | `network-architect.md` | L2/L3 networks, VLANs, facility ports, inter-site connectivity |
| Template Builder | `template-builder.md` | Weave creation, VM templates, boot configs, `weave.json` |
| DevOps Engineer | `devops-engineer.md` | Deployment, monitoring, infrastructure setup on VMs |
| Troubleshooter | `troubleshooter.md` | Debugging slice failures, connectivity issues, SSH problems |
| Data Analyst | `data-analyst.md` | FABRIC Reports API queries, usage analytics, visualization |
| Experiment Designer | `experiment-designer.md` | Experiment topology design, resource selection, methodology |
| AI Tools Evaluator | `ai-tools-evaluator.md` | Assess and optimize AI tool configurations |

## In-Container AI Tool Skills

28 skills defined in `backend/ai-tools/shared/skills/`. These provide step-by-step instructions for common FABRIC operations.

| Skill | File | Purpose |
|-------|------|---------|
| `create-slice` | `create-slice.md` | Build a new slice topology |
| `deploy-slice` | `deploy-slice.md` | Submit and provision a slice |
| `modify-slice` | `modify-slice.md` | Add/remove nodes and components |
| `delete-slice` | `delete-slice.md` | Delete a running slice |
| `renew-slice` | `renew-slice.md` | Extend slice lease |
| `clone-export` | `clone-export.md` | Clone or export a slice |
| `interact-slice` | `interact-slice.md` | SSH and execute on VMs |
| `monitor` | `monitor.md` | Enable monitoring, view metrics |
| `create-weave` | `create-weave.md` | Build orchestrated weave artifacts |
| `create-vm-template` | `create-vm-template.md` | Create VM template artifacts |
| `create-recipe` | `create-recipe.md` | Create recipe artifacts |
| `create-tutorial` | `create-tutorial.md` | Create tutorial notebooks |
| `publish-artifact` | `publish-artifact.md` | Publish to FABRIC Artifact Manager |
| `network` | `network.md` | Configure networks and connectivity |
| `sites` | `sites.md` | Query site availability and resources |
| `config` | `config.md` | FABRIC configuration and credentials |
| `ssh-config` | `ssh-config.md` | SSH key and bastion setup |
| `init-project` | `init-project.md` | Initialize a FABRIC project |
| `getting-started` | `getting-started.md` | New user onboarding |
| `fablib` | `fablib.md` | FABlib Python API reference |
| `query-fabric` | `query-fabric.md` | Query FABRIC infrastructure |
| `reports` | `reports.md` | FABRIC Reports API queries |
| `install-software` | `install-software.md` | Install packages on VMs |
| `debug` | `debug.md` | Troubleshoot common issues |
| `benchmark` | `benchmark.md` | Run performance benchmarks |
| `web-tunnel` | `web-tunnel.md` | Set up web app tunnels to VMs |
| `jupyter` | `jupyter.md` | JupyterLab integration |
| `eval-ai-tools` | `eval-ai-tools.md` | Evaluate AI tool configurations |
