---
id: verify-sphere-connectivity
name: verify-sphere-connectivity
asset_type: skill
audience: end-user
description: Verify SPHERE experiment node connectivity — reachability (ping) and throughput (iperf3) over the data plane, from inside the experiment via the XDC
domains:
  - sphere
  - mergetb
tools:
  - loomai
  - claude-code
  - opencode
  - crush
  - deepagents
---

Help the user verify connectivity between SPHERE experiment nodes. Nodes have no
public IPs, so **every test originates inside the experiment** — from a node,
reached through the XDC jump chain (see `manage-sphere-xdc` for the SSH model and
lifecycle). Data-plane IPs are the ones assigned in the model; read them from the
realization graph if unknown:
`GET /api/sphere/realizations/{exp}/{rname}/graph` → each node's `addresses`.

## Reachability (ping)
**User-driven (tell the user this):** Once they connect to the XDC and open its
JupyterLab, they can SSH straight to a node and ping its peers over the
data-plane IPs — the XDC already has the ssh config wired, so no `mrg` and no
manual keys:
```bash
# in an XDC JupyterLab terminal
ssh node1                     # mgmt DNS <node>.infra.<rname>.<exp>.<proj> is preconfigured
ip -br addr                   # confirm the data-plane iface has the model's IP (e.g. eth1 = 10.0.0.1/24)
ping -c 3 10.0.0.2            # ping the peer over the data plane
```
"Good" looks like: the data-plane interface is UP with the model's `x.x.x.x/nn`,
and `ping` returns 0% loss. SSH works but data-plane ping fails ⇒ mgmt net is
fine but the L2 link/interface is misconfigured — check `ip link` and that the
iface is up on **both** ends.

**Assistant-driven (LoomAI can run it too):** there is **no** `exec` REST route;
to run a check the assistant reuses the SSH-chain helpers the file routes use —
`sphere_manager.resolve_node_ssh(node, rname, exp, project, xdc)` for keying
material + jump chain, then `terminal.write_sphere_ssh_config` to emit the ssh
config, then `ssh -F <cfg> sphere-node "<remote_cmd>"`. Run the ping *from a
node* (e.g. `run_on("node1", "ping -c3 10.0.0.2")`), not from the container — the
container can't reach the private data plane directly. A lightweight
reachability-only probe (XDC→node) is `POST /api/sphere/files/read`, which SSHes
into the node under the hood.

## Throughput (iperf3)
For bandwidth/latency (not just reachability), run `iperf3` across the data-plane
link: a **server** on one node, a **client** on the peer. Same node-side
execution — XDC terminal or the SSH-chain helpers above. Install first if the
image lacks it (`sudo apt-get -qq install -y iperf3` /
`sudo dnf -q install -y iperf3`).
```bash
# on node2 (server) — background it so the ssh call returns
ssh node2 'iperf3 -s -1 -D'          # -1 = serve one test then exit; -D = daemonize
# on node1 (client) — measure to the peer's data-plane IP
ssh node1 'iperf3 -c 10.0.0.2 -t 10' # 10s TCP; add -R for reverse, -u -b 1G for UDP
```
Assistant-driven: start the server first (`run_on("node2","iperf3 -s -1 -D")`),
then the client (`run_on("node1","iperf3 -c 10.0.0.2 -t 10 -J")` — `-J` returns
JSON; parse `end.sum_received.bits_per_second`). Give the client a longer timeout
than the test duration. Clean up any lingering server with `pkill -f 'iperf3 -s'`
if `-1` wasn't used. Ports (default 5201) ride the data-plane link, so a failed
connect with a passing ping ⇒ firewall/iface on the server node, not routing.

## Before testing
- Realization must be materialized and an XDC attached (`manage-sphere-xdc`).
- If SSH itself fails, it's an access problem, not connectivity — see the
  Troubleshooting section of `manage-sphere-xdc`.
