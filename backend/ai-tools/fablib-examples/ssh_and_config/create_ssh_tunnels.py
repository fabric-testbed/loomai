# Accessing Services on FABRIC Nodes via SSH Tunnels
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: create_ssh_tunnels.ipynb
#
# FABRIC VMs are not directly reachable from the public Internet. Access to the
# management interface is always routed through a **bastion host** — a hardened
# SSH jump server — which provides a securi...

# # Accessing Services on FABRIC Nodes via SSH Tunnels
# ### FABlib API References
# ### Knowledge Base

# ## Step 1: Configure the Environment
# ## Step 2: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()


# ## Step 3: Create the Slice

slice_name = "MySlice-tunnels"

# Create a slice
slice = fablib.new_slice(name=slice_name)

# Add a node
node = slice.add_node(name="Node1", disk=100, image='docker_rocky_8')

node.add_post_boot_upload_directory('node_tools','.')
node.add_post_boot_execute('node_tools/enable_docker.sh {{ _self_.image }}')


# Submit the slice
slice.submit();


# ## Step 4: Start a Web Service on the Node

slice = fablib.get_slice(slice_name)
node = slice.get_node('Node1')

node.execute("docker run -d "
                "--name filebrowser "
                "-p 127.0.0.1:5555:5555 "
                f"-v /home/{node.get_username()}/data:/data "
                "-e FB_BASEURL=/filebrowser "
                "-e FB_ROOT=/data "
                "-e FB_PORT=5555 "
                "-e FB_NOAUTH=noauth "
                "filebrowser/filebrowser "
                , quiet=True, output_file=f"{node.get_name()}.log");


# ## Step 5: Set Up the SSH Tunnel on Your Laptop

fablib.create_ssh_tunnel_config(overwrite=True)


# ### Port Forwarding Command

import os
# Port on your local machine that you want to map the File Browser to.
local_port='5555'
# Local interface to map the File Browser to (can be `localhost`)
local_host='127.0.0.1'

# Port on the node used by the File Browser Service
target_port='5555'

# Username/node on FABRIC
target_host=f'{node.get_username()}@{node.get_management_ip()}'

print(f'ssh  -L {local_host}:{local_port}:127.0.0.1:{target_port} -i {os.path.basename(fablib.get_default_slice_public_key_file())[:-4]} -F ssh_config {target_host}')


# ## Step 6: Browse to the File Browser Service
# ## Continue Learning

# ## Step 7: Delete the Slice

slice.delete()
