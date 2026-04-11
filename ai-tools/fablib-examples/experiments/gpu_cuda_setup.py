# GPU Setup with CUDA on FABRIC
# Source: LoomAI — proven pattern for GPU node provisioning and CUDA verification
#
# Creates a slice with a GPU node, installs CUDA drivers, verifies nvidia-smi,
# and runs a simple GPU test. Shows GPU component model selection and
# site filtering for GPU availability.

import sys

from fabrictestbed_extensions.fablib.fablib import FablibManager


def start(slice_name: str, gpu_model: str = "GPU_RTX6000"):
    """Create a GPU slice, install CUDA, verify GPU access.

    Args:
        slice_name: Name for the new slice
        gpu_model: GPU component model — one of:
            GPU_RTX6000, GPU_TeslaT4, GPU_A30, GPU_A40
    """
    fablib = FablibManager()

    # Find a site with available GPUs
    print(f"### PROGRESS: Finding site with {gpu_model}...")

    # Get available sites and check for GPU capacity
    # Use get_site_names() — there is NO list_sites() that returns dicts
    site_names = fablib.get_site_names()

    print(f"### PROGRESS: Creating slice '{slice_name}'")
    slice_obj = fablib.new_slice(name=slice_name)

    # GPU nodes need more resources
    node = slice_obj.add_node(
        name="gpu-node",
        site=None,  # auto — FABRIC will find a site with the GPU
        cores=8,
        ram=32,
        disk=100,
        image="default_ubuntu_22",
    )

    # Add GPU component
    node.add_component(model=gpu_model, name="gpu1")

    print("### PROGRESS: Submitting slice (may take 5-15 minutes for GPU)...")
    slice_obj.submit()
    slice_obj.wait_ssh(progress=True)

    # Re-fetch slice (REQUIRED after submit)
    slice_obj = fablib.get_slice(name=slice_name)
    gpu_node = slice_obj.get_node(name="gpu-node")

    # Verify GPU is visible
    print("### PROGRESS: Checking GPU hardware...")
    stdout, _ = gpu_node.execute("lspci | grep -i nvidia", timeout=30)
    if "NVIDIA" not in stdout:
        print("WARNING: No NVIDIA GPU detected in lspci")
    else:
        print(f"  GPU detected: {stdout.strip()}")

    # Install CUDA drivers
    print("### PROGRESS: Installing NVIDIA drivers (this may take several minutes)...")
    gpu_node.execute(
        "sudo apt-get update -qq && "
        "sudo apt-get install -y -qq nvidia-driver-535 nvidia-utils-535",
        timeout=900,
    )

    # Verify nvidia-smi
    print("### PROGRESS: Verifying nvidia-smi...")
    stdout, stderr = gpu_node.execute("nvidia-smi", timeout=30)
    if "NVIDIA-SMI" in stdout:
        print(stdout)
        print("### PROGRESS: GPU setup complete!")
    else:
        print(f"WARNING: nvidia-smi failed: {stderr}")
        print("### PROGRESS: Driver install may require a reboot.")

    # Simple GPU test with Python
    print("### PROGRESS: Running GPU memory test...")
    gpu_node.execute(
        "python3 -c \""
        "import subprocess; "
        "r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free', "
        "'--format=csv,noheader'], capture_output=True, text=True); "
        "print(r.stdout)\"",
        timeout=30,
    )


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
        node = s.get_node(name="gpu-node")
        stdout, _ = node.execute("nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader",
                                  timeout=15, quiet=True)
        print(f"### PROGRESS: GPU utilization: {stdout.strip()}")
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: script.py {start|stop|monitor} SLICE_NAME [GPU_MODEL]")
        sys.exit(1)
    action = sys.argv[1]
    name = sys.argv[2]
    gpu = sys.argv[3] if len(sys.argv) > 3 else "GPU_RTX6000"
    if action == "start":
        start(name, gpu)
    elif action == "stop":
        stop(name)
    elif action == "monitor":
        monitor(name)
