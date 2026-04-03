# Persistent Storage for FPGA tools
# Source: FABRIC Jupyter Examples - fablib_api
# Notebook: fpga_tools_storage.ipynb
#
# This notebook shows how to create, re-create, renew and use a slice with a VM
# connected to FABNetv4 network on EDC on which you can store FPGA tool packages
# - the transfer of Xilinx tools into VMs ...

# # Persistent Storage for FPGA tools

# ## Step 0: Import the FABlib Library

from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager

fablib = fablib_manager()
                         
fablib.show_config();


# ## Step 1: Initialize slice parameters

# Replace with your project's volume name and site
site = "EDC"
storage_name = "fpga-tools"
node_name = "Storage-VM"
slice_name = "Xilinx Tools Storage Slice"
mount_point = "fpga-tools"

# this is the username, password to be used when downloading packages from this node. Change the password!
nginx_user = "fpga_tools"
nginx_password = "secret-password"


# ## Step 2: Create the Storage Slice

# Create a slice
slice = fablib.new_slice(name=slice_name)

# Add a node with storage and FABNetv4
node = slice.add_node(name=node_name, site=site)
node.add_storage(name=storage_name)
node.add_fabnet()

# Submit the slice
slice.submit();


# ## Step 3: Inspect the slice and get IP address information

slice = fablib.get_slice(slice_name)

node = slice.get_node(name=node_name)              

node_addr = node.get_interface(network_name=f'FABNET_IPv4_{node.get_site()}').get_ip_addr()

slice.show()
slice.list_nodes()
slice.list_networks()
print(f'Node FABNetV4 IP Address is {node_addr}')


# ## Step 4: Format the Volume (only run this the first time you attach the volume, skip otherwise)

node = slice.get_node(node_name)

storage = node.get_storage(storage_name)

print(f"Storage Device Name: {storage.get_device_name()}")  

stdout,stderr = node.execute(f"sudo mkfs.ext4 {storage.get_device_name()}")


# ## Step 5: Mount the Volume

node = slice.get_node(node_name)
storage = node.get_storage(storage_name)

stdout,stderr = node.execute(f"sudo mkdir /mnt/{mount_point}; "
                     f"sudo mount {storage.get_device_name()} /mnt/{mount_point}; "
                     f"df -h")


# ## Step 6: Install and configure NGINX

command = "sudo dnf install -y nginx httpd-tools"

print('Installing NGINX and apache tools')
stdout, stderr = node.execute(command)

command = "sudo systemctl enable nginx"
print('Enabling NGINX on reboot')
stdout, stderr = node.execute(command)

command = f"sudo htpasswd -bc2 /etc/nginx/htpasswd {nginx_user} {nginx_password}"

print('Setting username and password for downloads')
stdout, stderr = node.execute(command)

# install SSL server configuration
node.upload_file('ssl-server.conf', 'ssl-server.conf')
command = "sudo mv ssl-server.conf /etc/nginx/conf.d/; sudo chown nginx:nginx /etc/nginx/conf.d/ssl-server.conf"
stdout, stderr = node.execute(command)

# generate a self-signed key/cert
command = 'sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout /etc/nginx/server.key -out /etc/nginx/server.crt ' \
          '-subj="/C=US/ST=NC/L=Chapel Hill/O=UNC/OU=FABRIC/CN=fabric-testbed.net"; ' \
          'sudo chown nginx:nginx /etc/nginx/server.crt /etc/nginx/server.key'
stdout, stderr = node.execute(command)

# install location configuration
nginx_config = """
location /fpga-tools {
      alias /mnt/""" + mount_point + """/static;
      auth_basic "Restricted Access!";     
      auth_basic_user_file htpasswd;
      autoindex on;
      autoindex_format json;
      
      
      dav_methods PUT DELETE MKCOL COPY MOVE;
      dav_access user:rw group:rw all:rw;
      client_max_body_size 0;
      create_full_put_path on;
      client_body_temp_path /tmp/nginx-uploads;
}
"""
# transfer the config to the node
command = f"echo '{nginx_config}' | sudo tee /etc/nginx/default.d/static.conf"
stdout, stderr = node.execute(command)

# create a /mnt/fpga-tools/static/ directory if it doesn't exist already for staging files
command =f"sudo mkdir -p /mnt/{mount_point}/static; sudo chown rocky:rocky /mnt/{mount_point}/static; chmod go+w /mnt/{mount_point}/static"
stdout, stderr = node.execute(command)

# create a /mnt/fpga-tools/static/smartnic-docker-images direcory for ESnet workflow files
command =f"sudo mkdir -p /mnt/{mount_point}/static/smartnic-docker-images; sudo chown rocky:rocky /mnt/{mount_point}/static/smartnic-docker-images; chmod go+w /mnt/{mount_point}/static/smartnic-docker-images"
stdout, stderr = node.execute(command)

# create top-level directory for user artifacts
command =f"sudo mkdir -p /mnt/{mount_point}/static/artifacts; sudo chown rocky:rocky /mnt/{mount_point}/static/artifacts; chmod go+w /mnt/{mount_point}/static/artifacts"
stdout, stderr = node.execute(command)

# transfer SELinux policy module file to the node, compile and install it
# the file was originally created using `grep nginx /var/log/audit/audit.log | audit2allow -m nginx > nginx.te` 
# This policy allows nginx to read files and directories in general locations, including the attached storage
# Note that if you have issues with nginx not being able to read files, SELinux is likely to blame
# change `error_log /var/log/nginx/error.log;` to `error_log /var/log/nginx/error.log debug;` in /etc/nginx/nginx.conf
# and then restart NGINX to see what the problem may be
nginx_te = """

module nginx 1.0;

require {
        type init_t;
        type httpd_t;
        type httpd_tmp_t;
        type unlabeled_t;
        class file { create getattr open read rename unlink write };
        class dir { add_name remove_name rmdir write };
}

#============= httpd_t ==============
allow httpd_t unlabeled_t:dir { add_name remove_name write };
allow httpd_t unlabeled_t:file getattr;
allow httpd_t unlabeled_t:file { create open read rename unlink write };

#============= init_t ==============
allow init_t httpd_tmp_t:dir rmdir;

"""

command = f"echo '{nginx_te}' | sudo tee /etc/nginx/nginx.te"
stdout, stderr = node.execute(command)

# compile and install
command = """
sudo checkmodule -M -m -o /etc/nginx/nginx.mod /etc/nginx/nginx.te;
sudo semodule_package -o /etc/nginx/nginx.pp -m /etc/nginx/nginx.mod;
sudo semodule -i /etc/nginx/nginx.pp;
sudo semodule -l | grep nginx
"""
stdout, stderr = node.execute(command)

# add ability to access user home directories
command = "sudo setsebool -P httpd_read_user_content 1"
stdout, stderr = node.execute(command)

command = "sudo systemctl restart nginx; sudo systemctl status nginx"

stdout, stderr = node.execute(command)


# ## Step 7: Use the storage

# ## Step 8: Extend the slice

slice = fablib.get_slice(name=slice_name)
slice.show()

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


# ## Step 9: Delete the Slice

slice = fablib.get_slice(name=slice_name)
slice.delete()
