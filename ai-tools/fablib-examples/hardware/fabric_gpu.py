# GPU-Accelerated Computing on FABRIC
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: fabric_gpu.ipynb
#
# FABRIC sites host dedicated GPU hardware that researchers can attach to
# experiment VMs as **components** — the same mechanism used for FPGAs,
# SmartNICs, and NVMe storage. Once provisioned, the GPU ...

# # GPU-Accelerated Computing on FABRIC
# ### FABlib API References
# ### Available GPU Component Models
# ### Knowledge Base

# ## Step 1: Configure the Environment

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Select a GPU Type and Find an Available Site

# pick which GPU type we will use (execute this cell). 

# choices include
# GPU_RTX6000
# GPU_TeslaT4
# GPU_A30
# GPU_A40
GPU_CHOICE = 'GPU_RTX6000' 

# don't edit - convert from GPU type to a resource column name
# to use in filter lambda function below
choice_to_column = {
    "GPU_RTX6000": "rtx6000_available",
    "GPU_TeslaT4": "tesla_t4_available",
    "GPU_A30": "a30_available",
    "GPU_A40": "a40_available"
}

column_name = choice_to_column.get(GPU_CHOICE, "Unknown")
print(f'{column_name=}')

# name the slice and the node 
slice_name=f'My Simple GPU Slice with {GPU_CHOICE}'
node_name='gpu-node'

print(f'Will create slice "{slice_name}" with node "{node_name}"')

# find a site with at least one available GPU of the selected type
site_override = None

if site_override:
    site = site_override
else:
    site = fablib.get_random_site(filter_function=lambda x: x[column_name] > 0)
print(f'Preparing to create slice "{slice_name}" with node {node_name} in site {site}')


# ## Step 3: Create the Slice and Attach the GPU

# Create Slice. Note that by default submit() call will poll for 360 seconds every 10-20 seconds
# waiting for slice to come up. Normal expected time is around 2 minutes. 
slice = fablib.new_slice(name=slice_name)

# Add node with a 100G drive and a couple of CPU cores (default)
node = slice.add_node(name=node_name, site=site, disk=100, image='default_ubuntu_22')
node.add_component(model=GPU_CHOICE, name='gpu1')

#Submit Slice Request
slice.submit();


# ## Step 4: Inspect the Slice

slice = fablib.get_slice(name=slice_name)
slice.show();


# ## Step 5: Inspect the Node and GPU Component

node = slice.get_node(node_name) 
node.show()

gpu = node.get_component('gpu1')
gpu.show();


# ## Step 6: Verify the GPU PCI Device

command = "sudo apt-get install -y pciutils && lspci | grep 'NVIDIA|3D controller'"

stdout, stderr = node.execute(command)


# ## Step 7: Install NVIDIA Drivers and CUDA

distro='ubuntu2204'
version='12.6'
architecture='x86_64'

# install prerequisites
commands = [
    'sudo apt-get -q update',
    'sudo apt-get -q install -y linux-headers-$(uname -r) gcc',
]

print("Installing Prerequisites...")
for command in commands:
    print(f"++++ {command}")
    stdout, stderr = node.execute(command)

print("Installing PyTorch...")
commands = [
    'sudo apt install python3-pip -y',
    'pip3 install torch',
    'pip3 install torchvision'
]
for command in commands:
    print(f"++++ {command}")
    stdout, stderr = node.execute(command)

print(f"Installing CUDA {version}")
commands = [
    f'wget https://developer.download.nvidia.com/compute/cuda/repos/{distro}/{architecture}/cuda-keyring_1.1-1_all.deb',
    f'sudo dpkg -i cuda-keyring_1.1-1_all.deb',
    f'sudo apt-get -q update',
    f'sudo apt-get -q install -y cuda-{version.replace(".", "-")}'
]
print("Installing CUDA...")
for command in commands:
    print(f"++++ {command}")
    stdout, stderr = node.execute(command)
    
print("Done installing CUDA")


# ## Step 8: Reboot and Reconnect

reboot = 'sudo reboot'

print(reboot)
node.execute(reboot)

slice.wait_ssh(timeout=360,interval=10,progress=True)

print("Now testing SSH abilites to reconnect...",end="")
slice.update()
slice.test_ssh()
print("Reconnected!")


# ## Step 9: Verify the Driver and CUDA Installation

stdout, stderr = node.execute("nvidia-smi")

print(f"stdout: {stdout}")


# ## Step 10: Run a CUDA "Hello World" Program

node.upload_file('./hello-world.cu', 'hello-world.cu')

stdout, stderr = node.execute(f"/usr/local/cuda-{version}/bin/nvcc -o hello_world hello-world.cu")

stdout, stderr = node.execute("./hello_world")

print(f"stdout: {stdout}")


# ### Congratulations! You have now successfully run a program on a FABRIC GPU!

# ## Step 11: Train a PyTorch Image Classifier

node.upload_file('./pytorch_example.py', 'pytorch_example.py')

stdout, stderr = node.execute("python3 pytorch_example.py")


# ### Congratulations! You have now successfully trained a PyTorch classifier on a FABRIC GPU!

# ## Continue Learning
# ## Step 12: Delete the Slice

fablib.delete_slice(slice_name)
