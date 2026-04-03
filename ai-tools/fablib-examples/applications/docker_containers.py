# Deploy Docker Containers on FABRIC
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: docker_containers.ipynb
#
# Docker is the most widely-used containerization platform in research
# computing. Running containers on FABRIC nodes lets you package your entire
# experiment environment — software, dependencies, conf...

# # Deploy Docker Containers on FABRIC
# ### FABlib API References
# ### External References

# ## Step 1: Configure the Environment and Import FABlib

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()

fablib.show_config();


# ## Step 2: Create the Experiment Slice with Docker

slice_name = "DockerContainers"

# Create a slice
slice = fablib.new_slice(name=slice_name)

# Add a node with the Docker-enabled Rocky Linux 8 image
# disk=100 provides space for container images (default is 10 GB)
node = slice.add_node(name="Node1", disk=100, image='docker_rocky_8')

# Post-boot task 1: Upload helper scripts (includes enable_docker.sh)
node.add_post_boot_upload_directory('node_tools','.')
# Post-boot task 2: Enable Docker for the specific OS image
node.add_post_boot_execute('node_tools/enable_docker.sh {{ _self_.image }} ')
# Post-boot task 3: Upload Docker Compose configurations
node.add_post_boot_upload_directory('docker_containers','.')
# Post-boot task 4: Start the multitool container via Docker Compose
node.add_post_boot_execute('cd docker_containers/fabric_multitool ; docker compose up -d ')

# Submit the slice — post-boot tasks run automatically during this step
slice.submit();


# ## Step 3: Start a Container from the Command Line

node = slice.get_node('Node1')

stdout, stderr = node.execute("docker run -d -it "
                                "--name fabric_command_line "
                                "fabrictestbed/slice-vm-rocky8-multitool:0.0.1 "
                                , output_file=f"{node.get_name()}.log");


# ## Step 4: View Running Containers

stdout, stderr = node.execute('docker ps -a')


# ## Step 5: Execute a Command Inside a Container

stdout, stderr = node.execute('docker exec fabric_command_line ip addr list')


# ## Step 6: Delete the Slice

slice.delete()

# ## Continue Learning
