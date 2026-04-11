# Web Service Deployment on FABRIC
# Source: LoomAI — proven pattern for deploying a web app and accessing it via tunnel
#
# Creates a node, installs a Python Flask web app, and shows how to access it
# through an SSH tunnel. This pattern works for any web service (nginx, Grafana,
# Jupyter, etc.).

import sys

from fabrictestbed_extensions.fablib.fablib import FablibManager


def start(slice_name: str):
    """Deploy a simple web service on FABRIC."""
    fablib = FablibManager()

    print(f"### PROGRESS: Creating slice '{slice_name}'")
    slice_obj = fablib.new_slice(name=slice_name)

    node = slice_obj.add_node(
        name="web-server",
        site=None,
        cores=2,
        ram=8,
        disk=10,
        image="default_ubuntu_22",
    )

    print("### PROGRESS: Submitting slice...")
    slice_obj.submit()
    slice_obj.wait_ssh(progress=True)

    # Re-fetch (REQUIRED)
    slice_obj = fablib.get_slice(name=slice_name)
    server = slice_obj.get_node(name="web-server")

    mgmt_ip = server.get_management_ip()
    print(f"### PROGRESS: Server management IP: {mgmt_ip}")

    # Install Python and Flask
    print("### PROGRESS: Installing Flask...")
    server.execute(
        "sudo apt-get update -qq && sudo apt-get install -y -qq python3-pip && "
        "pip3 install flask",
        timeout=300,
    )

    # Deploy a simple Flask app
    # Use execute with echo — FABlib has NO node.write_file() method
    flask_app = '''
from flask import Flask, jsonify
import socket, platform, datetime

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "time": str(datetime.datetime.now()),
        "message": "Hello from FABRIC!"
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
'''
    # Write the app file via SSH (no write_file method in FABlib)
    server.execute(f"cat > /home/ubuntu/app.py << 'FLASK_EOF'\n{flask_app}\nFLASK_EOF", timeout=10)

    # Start the app in background
    print("### PROGRESS: Starting Flask app on port 5000...")
    server.execute("cd /home/ubuntu && nohup python3 app.py > app.log 2>&1 &", timeout=10)

    import time
    time.sleep(3)

    # Verify the app is running
    stdout, _ = server.execute("curl -s http://localhost:5000/", timeout=10)
    print(f"### PROGRESS: App response: {stdout.strip()}")

    # Show how to access via SSH tunnel
    ssh_cmd = server.get_ssh_command()
    print(f"\n### PROGRESS: Web service running!")
    print(f"  Internal URL: http://localhost:5000")
    print(f"  Access via SSH tunnel:")
    print(f"    ssh -L 5000:localhost:5000 {ssh_cmd.split('ssh ')[-1] if 'ssh ' in ssh_cmd else mgmt_ip}")
    print(f"  Then open: http://localhost:5000 in your browser")
    print(f"  Or use LoomAI Web Apps tab to create a tunnel")


def stop(slice_name: str):
    fablib = FablibManager()
    try:
        fablib.get_slice(name=slice_name).delete()
        print("### PROGRESS: Slice deleted.")
    except Exception as e:
        print(f"### PROGRESS: {e}")


def monitor(slice_name: str):
    fablib = FablibManager()
    try:
        s = fablib.get_slice(name=slice_name)
        if "StableOK" not in str(s.get_state()):
            sys.exit(1)
        node = s.get_node(name="web-server")
        stdout, _ = node.execute("curl -s http://localhost:5000/health", timeout=10, quiet=True)
        if '"ok"' in stdout:
            print("### PROGRESS: Web service healthy")
        else:
            print("### PROGRESS: Web service not responding")
            sys.exit(1)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: script.py {start|stop|monitor} SLICE_NAME")
        sys.exit(1)
    {"start": start, "stop": stop, "monitor": monitor}[sys.argv[1]](sys.argv[2])
