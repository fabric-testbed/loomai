# Collect Results from Multiple Nodes
# Source: LoomAI — proven pattern for gathering experiment output
#
# Shows how to run a command on each node, collect the output, and
# aggregate results locally. Useful for post-experiment data collection.
# Uses upload_file/download_file (NOT write_file which doesn't exist).

import os
import tempfile

from fabrictestbed_extensions.fablib.fablib import FablibManager


def collect_command_output(slice_name: str, command: str):
    """Run a command on every node and collect stdout.

    Args:
        slice_name: Name of a StableOK slice
        command: Shell command to run on each node

    Returns:
        Dict of {node_name: stdout_string}
    """
    fablib = FablibManager()
    slice_obj = fablib.get_slice(name=slice_name)
    nodes = slice_obj.get_nodes()

    results = {}
    for node in nodes:
        name = node.get_name()
        print(f"### PROGRESS: Running on {name}: {command}")
        try:
            stdout, stderr = node.execute(command, timeout=120)
            results[name] = stdout
            print(f"  {name}: {len(stdout)} bytes")
        except Exception as e:
            results[name] = f"ERROR: {e}"
            print(f"  {name}: ERROR — {e}")

    return results


def download_files_from_nodes(slice_name: str, remote_path: str, local_dir: str):
    """Download a file from every node to a local directory.

    Args:
        slice_name: Name of a StableOK slice
        remote_path: Path on each VM (e.g., "/tmp/results.csv")
        local_dir: Local directory to save files (creates node-named subdirs)

    Returns:
        Dict of {node_name: local_file_path}
    """
    fablib = FablibManager()
    slice_obj = fablib.get_slice(name=slice_name)
    nodes = slice_obj.get_nodes()

    os.makedirs(local_dir, exist_ok=True)
    downloaded = {}

    for node in nodes:
        name = node.get_name()
        local_path = os.path.join(local_dir, f"{name}_{os.path.basename(remote_path)}")
        print(f"### PROGRESS: Downloading {remote_path} from {name}")
        try:
            node.download_file(local_path, remote_path)
            downloaded[name] = local_path
            print(f"  {name}: saved to {local_path}")
        except Exception as e:
            print(f"  {name}: ERROR — {e}")

    return downloaded


def upload_file_to_nodes(slice_name: str, local_path: str, remote_path: str):
    """Upload a local file to every node.

    Args:
        slice_name: Name of a StableOK slice
        local_path: Path to local file
        remote_path: Destination path on each VM

    Note: FABlib uses upload_file(), NOT write_file() (which doesn't exist).
    """
    fablib = FablibManager()
    slice_obj = fablib.get_slice(name=slice_name)
    nodes = slice_obj.get_nodes()

    for node in nodes:
        name = node.get_name()
        print(f"### PROGRESS: Uploading to {name}:{remote_path}")
        try:
            node.upload_file(local_path, remote_path)
            print(f"  {name}: OK")
        except Exception as e:
            print(f"  {name}: ERROR — {e}")


def write_content_to_node(node, content: str, remote_path: str):
    """Write string content to a file on a node.

    FABlib has NO node.write_file() method. Use upload_file with a temp file,
    or echo via execute for small content.
    """
    if len(content) < 4000:
        # Small content: use echo (escape single quotes)
        escaped = content.replace("'", "'\\''")
        node.execute(f"echo '{escaped}' > {remote_path}", timeout=10)
    else:
        # Large content: write temp file then upload
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False) as f:
            f.write(content)
            tmp = f.name
        try:
            node.upload_file(tmp, remote_path)
        finally:
            os.unlink(tmp)


# Example usage
if __name__ == "__main__":
    import sys
    slice_name = sys.argv[1] if len(sys.argv) > 1 else "my-slice"

    # Collect hostname and uptime from all nodes
    results = collect_command_output(slice_name, "hostname && uptime")
    for name, output in results.items():
        print(f"\n--- {name} ---")
        print(output)
