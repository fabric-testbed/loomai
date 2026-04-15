---
name: benchmark
description: Run ad-hoc network/compute benchmarks (iperf3, ping, fio, stress-ng) on existing FABRIC slice nodes.
---

# Benchmarking existing FABRIC slice nodes

When the user asks you to run a benchmark (iperf3, bandwidth, throughput, ping, latency, fio, stress) **between nodes of an existing slice**, follow this workflow. **Do NOT create a new weave** — the slice already exists and the user wants a measurement, not a project directory.

## Rule 1 — Read IPs from `get_slice`, never from `ip addr show`

`ip addr show` returns the **management IP** first (typically `10.30.x.x` on `enp3s0`/`ens3`/`eth0`). Management IPs at different sites do NOT route between worker nodes. Using one fails with:

```
iperf3: error - unable to send control message: Bad file descriptor
```

or `Destination Host Unreachable` from ping.

**Always call `get_slice(slice_name)` and read `node.interfaces[i].ip_addr`** — that is the FABnet dataplane IP (in `10.128.0.0/10`) that routes across the overlay. Prefer interfaces whose `network_name` starts with `FABNET_` (overlay), `L2STS`, `L2PTP`, or `L2Bridge` (direct L2). Ignore interfaces with any other `network_name`.

Example extraction:

```json
{
  "nodes": [
    {
      "name": "worker1",
      "interfaces": [
        {"name": "worker1-FABNET_IPv4_NEWY_nic-p1",
         "network_name": "FABNET_IPv4_NEWY",
         "ip_addr": "10.137.132.2"}
      ]
    },
    {
      "name": "worker2",
      "interfaces": [
        {"name": "worker2-FABNET_IPv4_INDI_nic-p1",
         "network_name": "FABNET_IPv4_INDI",
         "ip_addr": "10.140.2.2"}
      ]
    }
  ]
}
```

→ worker1 dataplane IP is `10.137.132.2`, worker2 is `10.140.2.2`. Copy them **verbatim** — do not change the last octet.

## Rule 2 — Do NOT create a weave

The slice already exists. The user wants a number, not a project directory. Run the test directly via `ssh_execute`. **Never call `create_weave`, `write_file` to build a `weave.json`, or scaffold a project dir for an ad-hoc benchmark.**

## Mechanical IP table (emit every time)

After calling `get_slice`, **write an explicit IP table before taking any further action**. The table is a guard against IP hallucination — if you skip it, you will invent wrong IPs and the test will fail.

```
| node    | site  | dataplane network   | dataplane IP    |
| ------- | ----- | ------------------- | --------------- |
| worker1 | NEWY  | FABNET_IPv4_NEWY    | 10.137.132.2    |
| worker2 | INDI  | FABNET_IPv4_INDI    | 10.140.2.2      |
```

Rules for the table:
1. For each node, pick the first `interfaces[]` element whose `network_name` matches `FABNET_*`, `L2STS`, `L2PTP`, or `L2Bridge`.
2. Copy `ip_addr` verbatim. Do NOT extrapolate, average, or change the last octet.
3. **Every node must have a distinct IP.** If two rows are equal, re-read the JSON — you cannot iperf3 a node against itself; loopback returns nonsense numbers.
4. If a node has no matching interface, write `(no dataplane)` and exclude it from the test.

## iperf3 workflow

Given a **client** node and a **server** node (if the user says "from A to B", A is client, B is server):

**Step 1 — Look up IPs** from the table:
- `SERVER_IP` = the server node's dataplane IP
- `CLIENT_IP` = the client node's dataplane IP

Sanity check: **`SERVER_IP != CLIENT_IP`**. If they're equal, re-read `get_slice`.

**Step 2 — Ensure iperf3 is installed on both nodes** with a long timeout (apt on a cold VM can take 60–120 s):

```
ssh_execute(slice, server_node, "which iperf3 || (sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iperf3)", timeout=300)
ssh_execute(slice, client_node, "which iperf3 || (sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iperf3)", timeout=300)
```

**Step 3 — Start the iperf3 server as a daemon:**

```
ssh_execute(slice, server_node, "pkill -9 iperf3 2>/dev/null; sleep 0.5; iperf3 -s -D --logfile /tmp/iperf3-server.log")
```

**Step 4 — Sanity-ping SERVER_IP from the client before iperf3:**

```
ssh_execute(slice, client_node, "ping -c 2 -W 2 <SERVER_IP>")
```

- If 100% packet loss, the dataplane route is broken or the IP is wrong. Re-verify SERVER_IP against the table, then check `ip route | grep 10.128` on both nodes — every node should have `10.128.0.0/10 via <local_gateway>`. If the route is missing, report the problem and stop; do NOT fabricate a result.
- If ping returns sub-millisecond latency, you may be pinging the client's own interface. Verify the reply IP matches SERVER_IP and does NOT match CLIENT_IP.

**Step 5 — Run the iperf3 client and extract the summary:**

The full `iperf3 -J` output is ~5 KB (10 per-interval blocks), which exceeds the tool-result size limit and gets truncated — the `end` summary section is lost and you will retry in a loop. **Always pipe through the python extractor** to return only the `start.connected` (for loopback verification) and `end` (for the actual metrics) — about 400 chars:

```
ssh_execute(slice, client_node, "iperf3 -c <SERVER_IP> -t 10 -J | python3 -c \"import json,sys;d=json.load(sys.stdin);s=d['end']['sum_sent'];print(json.dumps({'remote_host':d['start']['connected'][0]['remote_host'],'gbps':round(s['bits_per_second']/1e9,3),'retransmits':s.get('retransmits',0),'sender_cpu':round(d['end']['cpu_utilization_percent']['host_total'],1)}))\"", timeout=60)
```

**Do NOT run bare `iperf3 -c ... -J`** without the python extractor — the full output is ~5 KB, exceeds the tool-result limit, gets truncated, and you will waste tool calls retrying.

**Step 6 — Read the extracted JSON directly.** The extractor already converts to Gbps and extracts all fields. Example output:
```json
{"remote_host": "10.147.2.2", "gbps": 0.190, "retransmits": 0, "sender_cpu": 2.5}
```
Verify `remote_host == SERVER_IP` (and `!= CLIENT_IP`) to catch accidental loopback. Read `gbps`, `retransmits`, and `sender_cpu` directly — no further math needed.

**Step 7 — Stop the iperf3 server:**

```
ssh_execute(slice, server_node, "pkill -9 iperf3 2>/dev/null")
```

**Step 8 — Report one concise line:**

> **`<client>` (`<CLIENT_IP>`) → `<server>` (`<SERVER_IP>`): X.XXX Gbps over 10 s (N retransmits, C % sender CPU)**

If retransmits > 0 or CPU ~100%, append one short sentence suggesting `-P 4` parallel streams, BBR congestion control, or larger TCP buffers.

## Anti-patterns

1. **Running `ip addr show` on the VMs to find IPs** — returns management IPs; test will fail.
2. **Skipping the IP table** — leads to IP hallucination.
3. **Using the same IP for client and server** — loopback test; result is meaningless.
4. **Using an IP not present in `get_slice`'s output** — every IP must be copied verbatim.
5. **Creating a weave for an ad-hoc benchmark** — the slice already exists.
6. **Fabricating a Gbps number** when the test fails — report the specific failure instead.
7. **Running bare `iperf3 -J` without the python extractor** — output is ~5 KB, exceeds the tool-result limit, gets truncated, and you retry in a loop. Always pipe through the extractor.

## Quick recipes for other benchmarks (single-node — no IP discovery)

| Benchmark | Command |
|---|---|
| **Latency** (cross-node: same FABnet-IP rule applies) | `ping -c 100 <FABNET_IP> \| tail -2` |
| **Disk I/O** | `sudo apt-get install -y -qq fio && fio --name=rw --rw=randrw --bs=4k --size=512M --runtime=30 --group_reporting --direct=1` |
| **CPU** | `sudo apt-get install -y -qq stress-ng && stress-ng --cpu $(nproc) --timeout 30s --metrics-brief` |
