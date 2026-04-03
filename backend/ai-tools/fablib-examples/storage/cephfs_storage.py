# Distributed Shared Storage on FABRIC — Advanced Demos
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: cephfs_storage.ipynb
#
# This notebook demonstrates three real-world use cases for **CephFS distributed
# shared storage** on FABRIC. With a single `storage=True` flag, FABlib
# provisions a POSIX-compliant shared filesystem a...

# # Distributed Shared Storage on FABRIC — Advanced Demos
# ### FABlib API References

# ## Step 1: Setup

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
fablib.show_config();


# ### Step 2: Discover Available Storage Clusters

import json

clusters = fablib.discover_ceph_clusters()
print(f"Available storage clusters: {json.dumps(clusters, indent=2)}")

user_clusters = fablib.discover_user_ceph_clusters()
print(f"\nClusters with your credentials: {json.dumps(user_clusters, indent=2)}")


# ## Demo 1: Multi-Site Data Sharing

# Pick two random sites for multi-site demo
[site1, site2] = fablib.get_random_sites(count=2)
print(f"Using sites: {site1}, {site2}")

# Create a slice with storage enabled on ALL nodes
slice1 = fablib.new_slice(name="CephFS-MultiSite", storage=True)

node_a = slice1.add_node(name="site-a-node", site=site1, cores=4, ram=8, disk=50)
node_b = slice1.add_node(name="site-b-node", site=site2, cores=4, ram=8, disk=50)

slice1.submit();


# ### Verify Storage on Both Nodes

slice1 = fablib.get_slice(name="CephFS-MultiSite")

for node in slice1.get_nodes():
    print(f"--- {node.get_name()} (storage={node.has_storage()}, cluster={node.get_storage_cluster()}) ---")
    stdout, stderr = node.execute("df -h | grep ceph")


# ### Write at Site A, Read at Site B

node_a = slice1.get_node("site-a-node")
node_b = slice1.get_node("site-b-node")

# Discover the shared storage mount path
stdout, _ = node_a.execute("mount | grep ceph | awk '{print $3}' | head -1", quiet=True)
mount_path = stdout.strip()
print(f"Shared storage mount path: {mount_path}")

# Write a dataset at Site A
print(f"\n--- Writing at {node_a.get_site()} ---")
node_a.execute(f"mkdir -p {mount_path}/demo1")
node_a.execute(f"echo 'Experiment results from {node_a.get_site()}' > {mount_path}/demo1/results.txt")
node_a.execute(f"date >> {mount_path}/demo1/results.txt")
stdout, _ = node_a.execute(f"cat {mount_path}/demo1/results.txt")

# Read the same data at Site B — no copy needed!
print(f"--- Reading at {node_b.get_site()} (same data, no transfer!) ---")
stdout, _ = node_b.execute(f"cat {mount_path}/demo1/results.txt")

# Write back from Site B
print(f"--- {node_b.get_site()} appends to the shared file ---")
node_b.execute(f"echo 'Analysis completed at {node_b.get_site()}' >> {mount_path}/demo1/results.txt")

# Verify at Site A
print(f"--- {node_a.get_site()} sees the update ---")
stdout, _ = node_a.execute(f"cat {mount_path}/demo1/results.txt")


# ### Measure cross-site throughput

# Write a 256MB file at Site A
print(f"--- {node_a.get_site()}: Writing 256MB test file ---")
node_a.execute(f"dd if=/dev/urandom of={mount_path}/demo1/testfile_256m bs=1M count=256 status=progress")

# Read it at Site B and measure throughput
print(f"\n--- {node_b.get_site()}: Reading 256MB file from CephFS ---")
node_b.execute(f"dd if={mount_path}/demo1/testfile_256m of=/dev/null bs=1M status=progress")

# Clean up the test file
node_a.execute(f"rm -f {mount_path}/demo1/testfile_256m", quiet=True)


# ### Clean up Demo 1

# Clean up demo1 directory but keep slice for Demo 2
node_a.execute(f"rm -rf {mount_path}/demo1", quiet=True)
slice1.delete()


# ## Demo 2: Persistent Storage Across Slices

# ### Step 1: Create the First Slice and Write Data

import datetime

[site1] = fablib.get_random_sites(count=1)
print(f"Writer site: {site1}")

# Create first slice with storage
slice2a = fablib.new_slice(name="CephFS-Persist-A", storage=True)
writer = slice2a.add_node(name="writer", site=site1, cores=4, ram=8, disk=50)
slice2a.submit();

slice2a = fablib.get_slice(name="CephFS-Persist-A")
writer = slice2a.get_node("writer")

# Find the mount path
stdout, _ = writer.execute("mount | grep ceph | awk '{print $3}' | head -1", quiet=True)
mount_path = stdout.strip()
print(f"CephFS mount: {mount_path}")

# Write important "experiment results" to CephFS
timestamp = datetime.datetime.now().isoformat()
writer.execute(f"mkdir -p {mount_path}/demo2_persistent")
writer.execute(f"echo 'Experiment ID: EXP-2024-042' > {mount_path}/demo2_persistent/experiment.txt")
writer.execute(f"echo 'Created: {timestamp}' >> {mount_path}/demo2_persistent/experiment.txt")
writer.execute(f"echo 'Result: pi ≈ 3.14159265358979' >> {mount_path}/demo2_persistent/experiment.txt")
writer.execute(f"dd if=/dev/urandom of={mount_path}/demo2_persistent/dataset.bin bs=1M count=10 status=none", quiet=True)

print("\nData written to CephFS:")
writer.execute(f"ls -lh {mount_path}/demo2_persistent/")
writer.execute(f"cat {mount_path}/demo2_persistent/experiment.txt")


# ### Step 2: Delete the First Slice

slice2a.delete()
print("Slice 'CephFS-Persist-A' deleted!")


# ### Step 3: Create a New Slice and Recover the Data

# Create a completely new slice — even at a different site!
[site2] = fablib.get_random_sites(count=1, avoid=[site1])
print(f"Reader site: {site2} (different from writer site {site1})")

slice2b = fablib.new_slice(name="CephFS-Persist-B", storage=True)
reader = slice2b.add_node(name="reader", site=site2, cores=4, ram=8, disk=50)
slice2b.submit();

slice2b = fablib.get_slice(name="CephFS-Persist-B")
reader = slice2b.get_node("reader")

# Find the mount path
stdout, _ = reader.execute("mount | grep ceph | awk '{print $3}' | head -1", quiet=True)
mount_path = stdout.strip()

# The data from the deleted slice is still here!
print("Data recovered from CephFS (written by the DELETED slice):")
reader.execute(f"ls -lh {mount_path}/demo2_persistent/")
reader.execute(f"cat {mount_path}/demo2_persistent/experiment.txt")
stdout, _ = reader.execute(f"md5sum {mount_path}/demo2_persistent/dataset.bin")
print("\nThe 10MB dataset binary is intact!")


# ### Clean up Demo 2

reader.execute(f"rm -rf {mount_path}/demo2_persistent", quiet=True)
slice2b.delete()


# ## Demo 3: Data Processing Pipeline

# Pick two random sites for the pipeline
[site1, site2] = fablib.get_random_sites(count=2)
print(f"Producer: {site1}, Consumer: {site2}")

# Node-level storage: only producer and consumer get CephFS
slice3 = fablib.new_slice(name="CephFS-Pipeline")

# Producer generates data (needs CephFS)
producer = slice3.add_node(name="producer", site=site1, cores=4, ram=8, disk=50, storage=True)

# Consumer processes data (needs CephFS)
consumer = slice3.add_node(name="consumer", site=site2, cores=4, ram=8, disk=50, storage=True)

slice3.submit();


# ### Verify selective storage

slice3 = fablib.get_slice(name="CephFS-Pipeline")

for node in slice3.get_nodes():
    print(f"--- {node.get_name()} (storage={node.has_storage()}) ---")
    stdout, stderr = node.execute("df -h | grep ceph || echo 'No CephFS mount'")


# ### Producer: Generate a Synthetic Sensor Dataset

producer = slice3.get_node("producer")

# Find the mount path
stdout, _ = producer.execute("mount | grep ceph | awk '{print $3}' | head -1", quiet=True)
mount_path = stdout.strip()

# Generate a synthetic dataset on CephFS
producer.execute(f"mkdir -p {mount_path}/pipeline")

producer.execute(f"""python3 -c "
import csv, random, math
with open('{mount_path}/pipeline/sensor_data.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['timestamp', 'sensor_id', 'temperature', 'humidity', 'pressure'])
    for i in range(10000):
        w.writerow([
            i * 0.1,
            f'sensor_{{random.randint(1,5):02d}}',
            round(20 + 10 * math.sin(i/100) + random.gauss(0, 0.5), 2),
            round(50 + 20 * math.cos(i/150) + random.gauss(0, 1), 2),
            round(1013 + 5 * math.sin(i/200) + random.gauss(0, 0.3), 2),
        ])
print('Dataset generated: 10,000 rows')
" """)

print("Producer output on CephFS:")
producer.execute(f"ls -lh {mount_path}/pipeline/")
producer.execute(f"head -5 {mount_path}/pipeline/sensor_data.csv")


# ### Consumer: Process the Dataset

consumer = slice3.get_node("consumer")

consumer.execute(f"""python3 -c "
import csv
from collections import defaultdict

# Read the producer's dataset directly from CephFS
stats = defaultdict(lambda: {{'count': 0, 'temp_sum': 0, 'temp_min': 999, 'temp_max': -999}})
with open('{mount_path}/pipeline/sensor_data.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        sid = row['sensor_id']
        temp = float(row['temperature'])
        stats[sid]['count'] += 1
        stats[sid]['temp_sum'] += temp
        stats[sid]['temp_min'] = min(stats[sid]['temp_min'], temp)
        stats[sid]['temp_max'] = max(stats[sid]['temp_max'], temp)

# Write summary back to CephFS
with open('{mount_path}/pipeline/summary.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['sensor_id', 'count', 'avg_temp', 'min_temp', 'max_temp'])
    for sid in sorted(stats):
        s = stats[sid]
        w.writerow([sid, s['count'], round(s['temp_sum']/s['count'], 2), s['temp_min'], s['temp_max']])

print('Summary written to CephFS!')
" """)

print("Consumer analysis results:")
consumer.execute(f"cat {mount_path}/pipeline/summary.csv")


# ### Producer Reads the Consumer's Output

print("Producer can see the consumer's analysis:")
producer.execute(f"cat {mount_path}/pipeline/summary.csv")

print("\nFull pipeline directory on CephFS:")
producer.execute(f"ls -lh {mount_path}/pipeline/")


# ### Clean up Demo 3

producer.execute(f"rm -rf {mount_path}/pipeline", quiet=True)
slice3.delete()


# ## Summary
# ### What happens under the hood
# ## Continue Learning
