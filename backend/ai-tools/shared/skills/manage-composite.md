name: manage-composite
description: Create and manage composite slices spanning FABRIC and Chameleon
---
Help the user create and manage composite slices — cross-testbed experiments
that group FABRIC and Chameleon resources together.

## What Is a Composite Slice?
A meta-slice that references existing FABRIC and Chameleon slices. It provides:
- Unified topology view across testbeds
- One-click parallel deployment
- Cross-testbed connectivity via FABNetv4

## Create a Composite Experiment

### Via WebUI (Recommended)
1. Enable Composite Slices view in Settings → Chameleon → "Enable Composite Slices"
2. Switch to the "Composite Slices" view
3. Click "New" → name the composite
4. In the editor's **Composite** tab:
   - Check FABRIC slices to include as members
   - Check Chameleon slices to include as members
5. In the **FABRIC** tab: edit FABRIC members inline (add nodes, networks)
6. In the **Chameleon** tab: edit Chameleon members inline (add servers, configure NICs)
7. Click "Submit" → all member slices deploy in parallel

### Via CLI + Tools
1. Create a FABRIC slice with FABNetv4:
   ```
   create_slice("my-fabric", nodes=[...], networks=[{type: "FABNetv4", ...}])
   submit_slice("my-fabric")
   ```

2. Create Chameleon servers with fabnetv4 on NIC 1:
   ```
   create_chameleon_lease("CHI@TACC", "my-chameleon", "compute_haswell", 2, 8)
   # Wait for ACTIVE, then launch instances with fabnetv4 network
   ```

3. Group in composite via WebUI

## Cross-Testbed Connectivity

### FABNetv4 (Standard Method)
Both FABRIC and Chameleon support FABNetv4 networks:
- FABRIC nodes: add FABNetv4 network → auto-assigned 10.128.x.x IP
- Chameleon nodes: connect NIC 1 to `fabnetv4` → gets FABNet IP
- All nodes on FABNet can reach each other via the FABRIC backbone

### Verify Connectivity
```bash
# From FABRIC VM:
ssh_execute("my-fabric", "node1", "ping -c 3 10.128.x.x")

# From Chameleon server:
ssh cc@<floating-ip> "ping -c 3 10.128.y.y"
```

## Design Guidelines
- **FABRIC for**: VMs, GPUs, SmartNICs, FPGAs, complex networking, quick iterations
- **Chameleon for**: Bare-metal access, specific hardware platforms, OS-level experiments
- **Both**: Use FABNetv4 on both sides for seamless connectivity
- **Monitoring**: WebUI composite topology shows live state from all testbeds
