# Running a P4 Application on a Xilinx U280 FPGA
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: fpga_simple_p4.ipynb
#
# This notebook demonstrates how to deploy a **P4 data plane application** on a
# FABRIC Xilinx Alveo U280 FPGA using the [ESnet SmartNIC firmware
# framework](https://github.com/esnet/esnet-smartnic-fw)...

# # Running a P4 Application on a Xilinx U280 FPGA
# ### FABlib API References
# ### Pre-requisites
# ### Knowledge Base

# ## Step 1: Configure the Environment

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                     
fablib.show_config();


# ## Step 2: Select a Site with FPGA Availability

FPGA_CHOICE='FPGA_Xilinx_U280'
SMART_NIC_CHOICE='NIC_ConnectX_6'

# don't edit - convert from FPGA type to a resource column name
# to use in filter lambda function below
choice_to_column = {
    "FPGA_Xilinx_U280": "fpga_u280_available",
}

column_name = choice_to_column.get(FPGA_CHOICE, "Unknown")
print(f'{column_name=}')

# name the slice and the node 
slice_name=f'My Simple FPGA with P4 Slice with {FPGA_CHOICE}'

# if your project has a storage volume at the site of interest you can set this to true and modify the volume name and mount point to how you like
# you can use that storage for storing build artifacts
use_storage = False

if use_storage:
    storage_name='xilinx-tools'
    mount_point = 'xilinx-tools'
    
fpga_node_name='fpga-node'
cx6_node_name='cx-6-node'
l2bridge1_name='l2bridge1'
l2bridge2_name='l2bridge2'

print(f'Will create slice "{slice_name}" with node "{fpga_node_name}" and node "{cx6_node_name}"')

import random

# you can limit to one of the sites on this list (or use None)
allowed_sites = ['CLEM']
#allowed_sites = None

fpga_sites_df = fablib.list_sites(output='pandas', quiet=True, filter_function=lambda x: x[column_name] > 0, force_refresh=True)
# note that list_sites with 'pandas' doesn't actually return a dataframe like doc sez, it returns a Styler 
# based on the dataframe
if fpga_sites_df:
    fpga_sites = fpga_sites_df.data['Name'].values.tolist()
else:
    fpga_sites = []
print(f'All sites with FPGA available: {fpga_sites}')

if len(fpga_sites)==0:
    print('Warning - no sites with available FPGAs found')
else:
    if allowed_sites and len(allowed_sites) > 0:
        fpga_sites = list(set(fpga_sites) & set(allowed_sites))
    if len(fpga_sites) == 0:
        print('Unable to find sites with available FPGAs')
    else:
        print('Selecting a site at random ' + f'among {allowed_sites}' if allowed_sites else '')

        site = random.choice(fpga_sites)
        print(f'Preparing to create slice "{slice_name}" with nodes {fpga_node_name} and {cx6_node_name} in site {site}')
        
# final site override if needed
#site = 'RENC'


# ## Step 3: Create the Slice

# Create Slice. Note that by default submit() call will poll for 360 seconds every 10-20 seconds
# waiting for slice to come up. Normal expected time is around 2 minutes. 
slice = fablib.new_slice(name=slice_name)
image = 'docker_ubuntu_20'

# Add node with a 100G drive and 8 of CPU cores using Ubuntu 20 image
node1 = slice.add_node(name=fpga_node_name, site=site, cores=8, ram=8, disk=100, image=image)
if use_storage:
    node1.add_storage(name=storage_name)
fpga_comp = node1.add_component(model=FPGA_CHOICE, name='fpga1')
fpga_p1 = fpga_comp.get_interfaces()[0]
fpga_p2 = fpga_comp.get_interfaces()[1]

# Add another node with ConnectX-6 cards of similar dimensions
node2 = slice.add_node(name=cx6_node_name, site=site, cores=8, disk=100, image=image)
#node2 = slice.add_node(name=cx6_node_name, site=site, cores=8, disk=100)
cx6_comp = node2.add_component(model=SMART_NIC_CHOICE, name='nic1')
cx6_p1 = cx6_comp.get_interfaces()[0]
cx6_p2 = cx6_comp.get_interfaces()[1]

# Use L2Bridge network services to connect the smart NIC and the FPGA ports
net1 = slice.add_l2network(name=l2bridge1_name, interfaces=[fpga_p1, cx6_p1], type='L2Bridge')
net2 = slice.add_l2network(name=l2bridge2_name, interfaces=[fpga_p2, cx6_p2], type='L2Bridge')

# Submit Slice Request
slice.submit();


# ## Step 4: Configure IOMMU and Hugepages

slice = fablib.get_slice(name=slice_name)
node1 = slice.get_node(name=fpga_node_name)

commands = list()
#commands.append("sudo sed -i 's/GRUB_CMDLINE_LINUX=\"\\(.*\\)\"/GRUB_CMDLINE_LINUX=\"\\1 amd_iommu=on iommu=pt default_hugepagesz=1G hugepagesz=1G hugepages=8\"/' /etc/default/grub")
commands.append("sudo sed -i 's/GRUB_CMDLINE_LINUX=\"\"/GRUB_CMDLINE_LINUX=\"amd_iommu=on iommu=pt default_hugepagesz=1G hugepagesz=1G hugepages=8\"/' /etc/default/grub")
commands.append("sudo grub-mkconfig -o /boot/grub/grub.cfg")
commands.append("sudo update-grub")

for command in commands:
    print(f'Executing {command}')
    stdout, stderr = node1.execute(command)
    
print('Done')

reboot = 'sudo reboot'

print(reboot)
node1.execute(reboot)

slice.wait_ssh(timeout=360,interval=10,progress=True)

print("Now testing SSH abilites to reconnect...",end="")
slice.update()
slice.test_ssh()
print("Reconnected!")

command = 'dmesg | grep -i IOMMU'

print('Observe that the modifications to boot configuration took place and IOMMU is detected')
stdout, stderr = node1.execute(command)

node1.config()

# Enable unsafe_noiommu_mode for the vfio module
command = "echo 1 | sudo tee /sys/module/vfio/parameters/enable_unsafe_noiommu_mode"

stdout, stderr = node1.execute(command)


# ## Step 5: Install Docker Compose and BuildX

commands = ["sudo usermod -G docker ubuntu", 
            "mkdir -p ~/.docker/cli-plugins/",
            "curl -SL https://github.com/docker/compose/releases/download/v2.17.2/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose",
            "chmod +x ~/.docker/cli-plugins/docker-compose",
            "curl -SL https://github.com/docker/buildx/releases/download/v0.11.2/buildx-v0.11.2.linux-amd64 -o ~/.docker/cli-plugins/docker-buildx",
            "chmod +x ~/.docker/cli-plugins/docker-buildx",
            "docker compose version",
            "docker container ps"
           ]

for command in commands:
    print(f'Executing {command}')
    stdout, stderr = node1.execute(command)
    
print('Done')


# ## Step 6: Mount the Persistent Storage Volume (Optional)

if use_storage:

    storage = node1.get_storage(storage_name)

    stdout,stderr = node1.execute(f"sudo mkdir -p /mnt/{mount_point}; sudo chmod go+rw /mnt/{mount_point};"
                                  f"sudo mount {storage.get_device_name()} /mnt/{mount_point}; "
                                  f"df -h")
else:
    print("Storage not specified, skipping")


# ## Step 7: Load Docker Containers and the P4 Artifact

#
# the following step ONLY works if you attached storage with docker containers and artifacts to the fpga-node
# if you did not you need to download/build those by other means (e.g. scp from elsewhere or
# install from docker repositories)
#

if use_storage:
    #
    # install existing dpdk and xilinx-labtools containers (pre-built) from
    # https://github.com/esnet/smartnic-dpdk-docker and https://github.com/esnet/xilinx-labtools-docker
    #
    dpdk_docker = 'smartnic-dpdk-docker.tar.gz'
    xilinx_labtools_docker = 'xilinx-labtools-docker-2023.1_0507_1903.tar.gz'
    artifact = '/mnt/xilinx-tools/artifacts/msada/v0/artifacts.au280.p4_only.0.zip'
    
    commands = [
        f"docker load < /mnt/{mount_point}/esnet-dockers/{dpdk_docker}",
        f"docker load < /mnt/{mount_point}/esnet-dockers/{xilinx_labtools_docker}",
        f"docker image ls",
        f"cp {artifact} ~/"
    ]
    for command in commands:
        print(f'Executing {command}')
        stdout, stderr = node1.execute(command)
else:
    print('Please build dpdk, xilinx-labtools dockers and install them on fpga-node manually, also place your artifact file in ~/')

# clone the esnet-smartnic-fw repo according to instructions https://github.com/esnet/esnet-smartnic-fw/tree/main (as of 09/2023)
# create a configuration environment file and build a container

# if the artifact file is called artifacts.au280.p4_only.0.zip then it translates into
# the following environment parameters

# update the env_file values to match the name of the artifact file
env_file = """
SN_HW_VER=0
SN_HW_BOARD=au280
SN_HW_APP_NAME=p4_only
"""

# update the artifact name as needed
artifact = '~/artifacts.au280.p4_only.0.zip'

commands = [
    "git clone https://github.com/esnet/esnet-smartnic-fw.git",
    "cd ~/esnet-smartnic-fw; git submodule init; git submodule update",
    f"cp {artifact} ~/esnet-smartnic-fw/sn-hw/",
    f"echo '{env_file}' | sudo tee ~/esnet-smartnic-fw/.env",
]

for command in commands:
    print(f'Executing {command}')
    stdout, stderr = node1.execute(command)

# finally build, logging to a file
node_thread = node1.execute_thread("cd ~/esnet-smartnic-fw/; ./build.sh", output_file='esnet-smartnic-fw-docker.log')
stdout, stderr = node_thread.result()

command = "docker image ls"
stdout, stderr = node1.execute(command)


# ## Step 8: Start the ESnet Stack and Test the FPGA

# set the FPGA device and the profile we want to execute
env_file = """
FPGA_PCIE_DEV=0000:00:1f
COMPOSE_PROFILES=smartnic-mgr-vfio-unlock
"""

# set execution profile to smartnic-mgr-vfio-unlock and run the stack
# notice we append to the pre-generated .env (it was generated as part of previous build)
commands = [
    f"echo '{env_file}' | tee -a ~/esnet-smartnic-fw/sn-stack/.env",
    "cd ~/esnet-smartnic-fw/sn-stack; docker compose up -d"
]

for command in commands:
    print(f'Executing {command}')
    stdout, stderr = node1.execute(command)

stdout, stderr = node1.execute("cd esnet-smartnic-fw/sn-stack/; docker container logs sn-stack-ubuntu-smartnic-devbind-1")


# ### Test sn-cli, configure CMACs

command = "cd esnet-smartnic-fw/sn-stack/; docker compose exec smartnic-fw sn-cli dev version"

stdout, stderr = node1.execute(command)

# upload sn-cli config script
sn_cli_script = 'sn-cli-setup'

result = node1.upload_file(sn_cli_script, sn_cli_script)

commands = [
    f"chmod a+x {sn_cli_script}",
    f"mv {sn_cli_script} ~/esnet-smartnic-fw/sn-stack/scratch",
    f"cd ~/esnet-smartnic-fw/sn-stack/; docker compose exec smartnic-fw scratch/{sn_cli_script}"
]

for command in commands:
    print(f'Executing {command}')
    stdout, stderr = node1.execute(command)


# ## Step 9: Run pktgen and Observe Traffic on the ConnectX-6 Node

# bring down the stack

command = "cd esnet-smartnic-fw/sn-stack/; docker compose down"

stdout, stderr = node1.execute(command)

# modify the profile to be `smartnic-mgr-dpdk-manual`
commands = [
    "sed -i 's/COMPOSE_PROFILES=smartnic-mgr-vfio-unlock/COMPOSE_PROFILES=smartnic-mgr-dpdk-manual/' ~/esnet-smartnic-fw/sn-stack/.env",
    "tail ~/esnet-smartnic-fw/sn-stack/.env"
]

for command in commands:
    print(f'Executing {command}')
    stdout, stderr = node1.execute(command)

command = "cd ~/esnet-smartnic-fw/sn-stack; docker compose up -d"
stdout, stderr = node1.execute(command)

node2 = slice.get_node(name=cx6_node_name)
cx_6_port0 = "ens7"
cx_6_port1 = "ens8"

commands = [
    f"sudo ip link set up {cx_6_port0}",
    f"sudo ip link set up {cx_6_port1}"
]

for command in commands:
    print(f'Executing {command}')
    stdout, stderr = node2.execute(command)

pktcount = 10
print(f"LISTENING ON {cx_6_port0}")
command = f"sudo tcpdump -nlvvxx -i {cx_6_port0} -c {pktcount} tcp"

stdout, stderr = node2.execute(command)
print("LISTENING ON {cx_6_port1}")
command = f"sudo tcpdump -nlvvxx -i {cx_6_port1} -c {pktcount} tcp"

stdout, stderr = node2.execute(command)

command = "cd ~/esnet-smartnic-fw/sn-stack; docker compose down"

stdout, stderr = node1.execute(command)


# ## Step 10: Extend the Slice (Optional)

slice = fablib.get_slice(name=slice_name)
a = slice.show()
nets = slice.list_networks()
nodes = slice.list_nodes()

from datetime import datetime
from datetime import timezone
from datetime import timedelta

# Set end host to now plus 14 days
end_date = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S %z")

try:
    slice = fablib.get_slice(name=slice_name)

    slice.renew(end_date)
except Exception as e:
    print(f"Exception: {e}")


# ## Continue Learning
# ## Step 11: Delete the Slice

slice = fablib.get_slice(name=slice_name)
slice.delete()
