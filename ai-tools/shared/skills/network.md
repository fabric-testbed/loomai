name: network
description: Design a network topology for a FABRIC experiment
---
Design a network topology for a FABRIC experiment. For full network type and
NIC model tables, see AGENTS.md.

## Decision Steps

1. **Same site or cross-site?**
   - Same site: L2Bridge (simplest)
   - Cross-site with IP routing: `fabnet: "v4"` on each node, or one FABNetv4 service per site
   - Cross-site raw Ethernet: L2STS
   - Exactly 2 endpoints: L2PTP

2. **Bandwidth needs?**
   - Standard: NIC_Basic (shared 25G, 1 port) — sufficient for most experiments
   - Dedicated: NIC_ConnectX_5 (25G), NIC_ConnectX_6 (100G), NIC_ConnectX_7 (100/400G)
   - Each dedicated NIC has 2 ports — can connect to 2 networks

3. **Special features?**
   - VLAN tagging / sub-interfaces: requires Python script with dedicated NIC
   - Port mirroring: requires Python script
   - Public IPs: FABNetv4Ext / FABNetv6Ext (limited availability)

## Common Patterns

### Cross-site L3 (recommended default)
```
nodes=[
  {name: "n1", site: "STAR", fabnet: "v4"},
  {name: "n2", site: "TACC", fabnet: "v4"}
]
```
Auto-creates one FABNetv4 service per site and assigns IPs on
10.128.0.0/10. Ping works after the slice reaches StableOK and networking is
configured.

### Same-site L2 LAN
```
nodes=[{name: "n1", site: "STAR"}, {name: "n2", site: "STAR"}],
networks=[{name: "lan", type: "L2Bridge", interfaces: ["n1", "n2"], subnet: "192.168.1.0/24"}]
```

### Cross-site L2 tunnel
```
networks=[{name: "tunnel", type: "L2STS", interfaces: ["n1", "n2"], subnet: "10.0.0.0/24"}]
```

## Hard Service Limits

| Service | Site rule | Size limit |
| --- | --- | --- |
| L2Bridge | all interfaces at one site | site capacity |
| L2STS | exactly two sites | many NICs per side |
| L2PTP | exactly two interfaces, two sites | two endpoints |
| FABNetv4/v6/Ext | all attached VMs at one site | up to 255 VMs per service |

Do not create one FABNetv4/FABNetv6 network that lists interfaces from
multiple sites; FABRIC rejects it with "Service cannot span N sites. Limit: 1".
For multi-site L3, use `fabnet` on each node or create one FABNet service per
site. FABRIC routes between per-site services over `10.128.0.0/10` or
`2602:fcfb::/40`.

## Key Subnets

- FABRIC IPv4 backbone: `10.128.0.0/10` (FABNetv4)
- FABRIC IPv6 backbone: `2602:fcfb::/40` (FABNetv6)
- Public IPv4: `23.134.232.0/22` (FABNetv4Ext, limited)

## Interface Wiring

When using `create_slice`, just pass node names in `interfaces` — NICs are
auto-created. When writing weave topology directly, you must:
1. Add NIC components to each node's `components` array
2. Reference them in networks as `{node}-{nic-name}-p{port}` (e.g., `node1-nic1-p1`)
3. Each NIC_Basic port connects to at most one network — add multiple NICs for multi-network nodes

See AGENTS.md "Wiring Nodes to Networks" for full details and examples.

## Tips

- FABNetv4 is the simplest cross-site L3 option when used per-node/per-site
- L2PTP is strictly 2 endpoints; use L2STS for more
- Check availability first: `query_sites(component="NIC_ConnectX_6")`
- Co-locate nodes needing low latency at the same site
