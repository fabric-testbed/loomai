# Distributed Shared Storage — Quick Start
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: cephfs_storage_basic.ipynb
#
# The fastest way to give your FABRIC nodes a **shared distributed filesystem**.
# Pass `storage=True` when creating your slice and every node automatically gets
# access to the same CephFS volume — no S...

# # Distributed Shared Storage — Quick Start
# ### FABlib API References

# ## Step 1: Setup

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
fablib.show_config();


# ## Step 2a: Slice-Level Storage

SLICE_NAME = "CephFS-QuickStart"

[site1, site2] = fablib.get_random_sites(count=2)
print(f"Using sites: {site1}, {site2}")

slice1 = fablib.new_slice(name=SLICE_NAME, storage=True)
node1 = slice1.add_node(name="node1", site=site1, cores=4, ram=8, disk=50)
node2 = slice1.add_node(name="node2", site=site2, cores=4, ram=8, disk=50)
slice1.submit();


# ### Step 3a: Verify the Storage Mount

slice1 = fablib.get_slice(name=SLICE_NAME)
node1 = slice1.get_node("node1")
node2 = slice1.get_node("node2")

for node in [node1, node2]:
    print(f"{node.get_name()}: storage={node.has_storage()}, cluster={node.get_storage_cluster()}")
    node.execute("df -h | grep ceph")


# ### Step 4a: Shared Storage in Action

# Discover the mount path
stdout, _ = node1.execute("mount | grep ceph | awk '{print $3}' | head -1", quiet=True)
mount_path = stdout.strip()
print(f"CephFS mount path: {mount_path}")

# Write a file on node1
node1.execute(f"echo 'Hello from node1!' > {mount_path}/hello.txt")
print("--- Written on node1 ---")
node1.execute(f"cat {mount_path}/hello.txt")

# Read the same file from node2
print("--- Read from node2 ---")
node2.execute(f"cat {mount_path}/hello.txt")

# Write from node2, read from node1
node2.execute(f"echo 'Reply from node2!' >> {mount_path}/hello.txt")
print("--- Both lines visible on node1 ---")
node1.execute(f"cat {mount_path}/hello.txt")


# ### Step 5a: Clean Up Slice-Level Example

node1.execute(f"rm -f {mount_path}/hello.txt", quiet=True)
slice1.delete()
print("Slice deleted.")


# ## Step 2b: Node-Level Storage

SLICE_NAME_2 = "CephFS-NodeLevel"

[site1, site2] = fablib.get_random_sites(count=2)
print(f"Using sites: {site1}, {site2}")

slice2 = fablib.new_slice(name=SLICE_NAME_2)

# Only this node gets shared storage
storage_node = slice2.add_node(name="with-storage", site=site1, cores=4, ram=8, disk=50, storage=True)

# This node does NOT get shared storage
compute_node = slice2.add_node(name="compute-only", site=site2, cores=4, ram=8, disk=50)

slice2.submit();


# ### Step 3b: Verify Selective Storage

slice2 = fablib.get_slice(name=SLICE_NAME_2)

for node in slice2.get_nodes():
    has = node.has_storage()
    cluster = node.get_storage_cluster() if has else "N/A"
    print(f"{node.get_name():20s}  storage={has!s:5s}  cluster={cluster}")
    node.execute("df -h | grep ceph || echo '  No CephFS mount'")


# ### Step 4b: Clean Up Node-Level Example

slice2.delete()
print("Slice deleted.")


# ## Quick Reference
# ## Continue Learning
