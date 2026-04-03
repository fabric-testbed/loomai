name: fablib
description: Manage FABRIC slices, resources, and experiments using built-in FABlib tools and Python scripts
---
Help the user interact with FABRIC using the built-in tools or Python scripts.
For detailed reference tables (component models, network types, images, node
specs), see AGENTS.md — it is loaded as context automatically.

## Tool Categories

**Slice Lifecycle:** `list_slices`, `get_slice`, `create_slice`,
`submit_slice`, `submit_slice`, `delete_slice`,
`renew_slice`, `refresh_slice`

**SSH & Files:** `ssh_execute`, `write_vm_file`, `read_vm_file`,
`get_slice`

**Resources:** `query_sites`, `get_site_hosts`, `list_images`,
`list_component_models`, `query_sites`

**Config:** `get_config`, `update_settings`, `get_config`,
`list_projects`, `switch_project`

**Templates:** `list_templates`, `load_template`

## When to Use Tools vs Python Scripts

**Use tools** for: listing/inspecting slices and sites, creating slices (up to ~10 nodes),
running commands on nodes, uploading/downloading files, modifying/deleting/renewing slices.

**Write a Python script** (using `FablibManager()`) for:
- Sub-interfaces and VLAN tagging
- Port mirroring (traffic capture)
- Facility ports (external connectivity)
- CPU pinning and NUMA tuning
- Persistent storage (CephFS)
- Batch operations across many slices
- Complex data analysis with pandas/matplotlib
- Custom network configurations
- Advanced resource queries and availability checks

## Python Script Template

```python
from fabrictestbed_extensions.fablib.fablib import FablibManager
fablib = FablibManager()

# Your FABlib code here
slices = fablib.get_slices()
for s in slices:
    print(f"{s.get_name()}: {s.get_state()}")
```

Save scripts anywhere under `/home/fabric/work/` — they can be run directly.

## Key FABlib Operations

```python
# Create slice with components
slice = fablib.new_slice(name="experiment")
node = slice.add_node(name="n1", site="STAR", cores=4, ram=16, disk=50,
                       image="default_ubuntu_22")
nic = node.add_component(model="NIC_Basic", name="nic1")
gpu = node.add_component(model="GPU_RTX6000", name="gpu1")
nvme = node.add_component(model="NVME_P4510", name="nvme1")

# Networks
net = slice.add_l2network(name="net1", interfaces=[nic.get_interfaces()[0]])
l3 = slice.add_l3network(name="fabnet", type="IPv4", interfaces=[...])

# Easy cross-site L3
node.add_fabnet(net_type="IPv4")

# Sub-interfaces
iface = nic.get_interfaces()[0]
child = iface.add_sub_interface("vlan100", vlan="100")

# Facility ports
fp = slice.add_facility_port(name="ext", site="STAR", vlan="100")

# Submit and execute
slice.submit()
slice.wait_ssh(progress=True)
stdout, stderr = node.execute("hostname")
node.upload_file("local.txt", "~/remote.txt")
node.upload_directory("tools/", "~/tools/")

# Resource queries
resources = fablib.get_resources()
site = resources.get_site("STAR")
print(f"Available cores: {site.get_cpu_available()}")
```

## Authentication

Token: `/home/fabric/work/fabric_config/id_token.json`
Config: `/home/fabric/work/fabric_config/fabric_rc`

FABlib is pre-configured — all tools use the user's credentials automatically.
If token errors occur, direct the user to refresh via the Configure view.
Token expires every ~1 hour.
