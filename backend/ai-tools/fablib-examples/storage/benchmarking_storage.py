# Benchmarking FABRIC Storage: Local Disk vs. NVMe
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: benchmarking_storage.ipynb
#
# FABRIC offers two types of node-attached storage, and their performance
# characteristics differ significantly. This notebook benchmarks both using `dd`
# — a standard Unix utility for raw block I/O me...

# # Benchmarking FABRIC Storage: Local Disk vs. NVMe
# ### FABlib API References

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config()


# ## Step 3: Configure Slice Parameters

slice_name = 'StorageBenchmark'
site = fablib.get_random_site()
node_name = 'Node1'
cores = 4
ram = 16
disk = 100

nvme_name = 'nvme1'


# ## Step 4: Create the Slice

try:
    #Create Slice
    slice = fablib.new_slice(name=slice_name)

    # Add node with local disk
    node = slice.add_node(name=node_name, cores=cores, ram=ram, disk=disk)
    
    #Add an NVME Drive
    node.add_component(model='NVME_P4510', name=nvme_name)

    #Submit Slice Request
    slice.submit()
except Exception as e:
    print(f"Exception: {e}")


# ## Step 5: Retrieve the Slice

try:
    slice = fablib.get_slice(name=slice_name)
    print(f"{slice}")
except Exception as e:
    print(f"Exception: {e}")


# ## Step 6: Inspect the Node and NVMe Component

try:
    node = slice.get_node(node_name) 
    print(f"{node}")
  
    nvme1 = node.get_component(nvme_name)
    print(f"{nvme1}")
    
except Exception as e:
    print(f"Exception: {e}")


# ## Step 7: Configure the NVMe Device

try:
    nvme1.configure_nvme()
except Exception as e:
    print(f"Exception: {e}")


# ## Step 8: Benchmark the Local Disk
# ### Understanding the Caching Layers
# ### Verify the Local Disk Mount Point

try:
    stdout, stderr = node.execute('df /tmp')
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ### Test 1a: 1 GB Write — Buffered

command='dd if=/dev/zero of=/tmp/output bs=1G count=1'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ### Test 1b: 1 GB Write — Direct I/O (`oflag=direct`)

command='dd if=/dev/zero of=/tmp/output bs=1G count=1 oflag=direct'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ### Why the 1 GB Direct I/O Result May Still Be Fast
# ### Test 1c: 5 GB Write — Direct I/O

command='dd if=/dev/zero of=/tmp/output bs=5G count=1 oflag=direct'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ### Test 1d: 25 GB Write — Direct I/O

command='dd if=/dev/zero of=/tmp/output bs=25G count=1 oflag=direct'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")

# ## Step 9: Benchmark the NVMe Device
# ### Test 2a: 1 GB Write — Buffered

command='sudo dd if=/dev/zero of=/mnt/nvme_mount/output bs=1G count=1'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ### Test 2b: 1 GB Write — Direct I/O

command='sudo dd if=/dev/zero of=/mnt/nvme_mount/output bs=1G count=1 oflag=direct'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ### Test 2c: 5 GB Write — Direct I/O

command='sudo dd if=/dev/zero of=/mnt/nvme_mount/output bs=5G count=1 oflag=direct'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ### Test 2d: 100 GB Write — Sustained Throughput

command='sudo dd if=/dev/zero of=/mnt/nvme_mount/output bs=1G count=100 oflag=direct'
try:
    stdout, stderr = node.execute(command)
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
except Exception as e:
    print(f"Exception: {e}")


# ## Continue Learning
# ## Step 10: Delete the Slice

try:
    slice = fablib.get_slice(name=slice_name)
    slice.delete()
except Exception as e:
    print(f"Exception: {e}")
