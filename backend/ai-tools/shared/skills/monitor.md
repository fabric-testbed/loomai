name: monitor
description: Set up monitoring (Prometheus + Grafana) for a FABRIC slice
---
Help the user set up monitoring for their FABRIC experiment.

1. **Assess the setup**: How many nodes? What metrics matter? Is Prometheus already
   deployed, or do we need a full monitoring stack?

2. **Options**:
   - **Node Exporter only**: Install `node_exporter` on worker nodes for basic
     system metrics (CPU, RAM, disk, network). Lightweight.
   - **Full stack**: Prometheus + Grafana on a dedicated monitor node, with
     `node_exporter` on all workers. More complete.

3. **For node_exporter setup**, create or reference the install script:
   ```bash
   #!/bin/bash
   set -e
   ### PROGRESS: Installing node_exporter
   wget -q https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
   tar xzf node_exporter-1.7.0.linux-amd64.tar.gz
   sudo cp node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/
   sudo useradd -rs /bin/false node_exporter || true
   sudo tee /etc/systemd/system/node_exporter.service > /dev/null <<'EOF'
   [Unit]
   Description=Node Exporter
   After=network.target
   [Service]
   User=node_exporter
   ExecStart=/usr/local/bin/node_exporter
   [Install]
   WantedBy=multi-user.target
   EOF
   sudo systemctl daemon-reload
   sudo systemctl enable --now node_exporter
   ### PROGRESS: node_exporter running on :9100
   ```

4. **For full stack**, reference or create the Prometheus + Grafana Stack template.

5. **Verify**: Check that metrics endpoints are accessible.
