#!/usr/bin/env python3
"""Configure FABNetv4 routes and upload monitoring config to the monitor node.

Runs on the webgui container with FABlib access. Called by deploy.sh.
Collects all node FABNet IPs, generates prometheus.yml with explicit static
targets, processes the Grafana dashboard for file provisioning, and uploads
everything to ~/monitoring-config/ on the monitor node.
"""
import os, sys, json, ipaddress, tempfile

FABNETV4_SUBNET = ipaddress.ip_network("10.128.0.0/10")
slice_name = os.environ["SLICE_NAME"]
build_dir = os.environ["BUILD_DIR"]

from fabrictestbed_extensions.fablib.fablib import FablibManager
fablib = FablibManager()

s = fablib.get_slice(name=slice_name)
s.update()

# ── Phase 1: Configure FABNetv4 routes and collect IPs ──────────────
node_ips = {}   # node_name -> fabnet_ip
errors = []

for node in s.get_nodes():
    for iface in node.get_interfaces():
        net = iface.get_network()
        if net and str(net.get_type()) in ("FABNetv4", "FABNetv4Ext"):
            gw = net.get_gateway()
            if gw:
                try:
                    node.ip_route_add(subnet=FABNETV4_SUBNET, gateway=gw)
                    print(f"  {node.get_name()}: route 10.128.0.0/10 via {gw}")
                except Exception as e:
                    if "File exists" not in str(e):
                        errors.append(f"{node.get_name()} route: {e}")
            fd = iface.get_fablib_data()
            ip = fd.get("addr")
            if ip:
                node_ips[node.get_name()] = ip

if errors:
    print("=== Route config had errors ===")
    for e in errors:
        print(f"  ERROR: {e}")
    sys.exit(1)

print("")
for name, ip in node_ips.items():
    role = "monitor" if name == "monitor" else "worker"
    print(f"  {name} ({role}): FABNet IP = {ip}")

# ── Phase 2: Generate prometheus.yml with explicit static targets ────
print("\n### PROGRESS: Generating Prometheus config with static targets")

monitor_ip = node_ips.get("monitor", "localhost")
all_targets = [f"{ip}:9100" for ip in node_ips.values()]

prometheus_yml = f"""global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ['localhost:9090']

  - job_name: node
    static_configs:
      - targets: {json.dumps(all_targets)}
"""

# ── Phase 3: Process dashboard JSON for file provisioning ────────────
print("### PROGRESS: Preparing Grafana dashboard for provisioning")

dashboard_src = os.path.join(build_dir, "node-exporter-full.json")
with open(dashboard_src) as f:
    dash_text = f.read()

# Replace datasource variable references with our configured uid
dash_text = dash_text.replace("${DS_PROMETHEUS}", "prometheus")

dash = json.loads(dash_text)
dash.pop("__inputs", None)
dash.pop("__requires", None)
dash["id"] = None  # required for file provisioning

processed_dashboard = json.dumps(dash)

# ── Phase 4: Upload everything to the monitor node ───────────────────
print("### PROGRESS: Uploading monitoring config to monitor node")

monitor_node = s.get_node("monitor")
monitor_node.execute(
    "mkdir -p ~/monitoring-config/grafana-provisioning/datasources "
    "~/monitoring-config/grafana-provisioning/dashboards",
    quiet=True,
)


def _upload_text(text, remote_path, suffix=".yml"):
    """Write text to a temp file and upload it to the monitor node."""
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        monitor_node.upload_file(tmp, remote_path)
    finally:
        os.unlink(tmp)


# prometheus.yml with static targets
_upload_text(prometheus_yml, "monitoring-config/prometheus.yml")

# Processed dashboard JSON
_upload_text(processed_dashboard, "monitoring-config/grafana-provisioning/dashboards/node-exporter-full.json", suffix=".json")

# Grafana datasource provisioning
monitor_node.upload_file(
    os.path.join(build_dir, "grafana-datasource.yml"),
    "monitoring-config/grafana-provisioning/datasources/datasource.yml",
)

# Grafana dashboard provider config
monitor_node.upload_file(
    os.path.join(build_dir, "grafana-dashboard-provider.yml"),
    "monitoring-config/grafana-provisioning/dashboards/dashboard.yml",
)

print("### PROGRESS: Monitoring config uploaded to monitor node")
print(f"\n=== Deploy complete ===")
print(f"  Monitor: {monitor_ip}")
print(f"  Targets: {', '.join(all_targets)}")
print(f"  Prometheus will be at: http://{monitor_ip}:9090")
print(f"  Grafana will be at:    http://{monitor_ip}:3000")
