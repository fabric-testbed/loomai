name: web-tunnel
description: Set up SSH tunnels to access web services running on FABRIC VMs
---
Set up web tunnels to access HTTP services (Grafana, Jupyter, web apps) running
on FABRIC VMs through the LoomAI WebUI.

## How It Works

Web tunnels create SSH port forwards from the container to FABRIC VMs, making
remote web services accessible through the WebUI's "Web Apps" panel.

## Steps

1. **Ensure the service is running** on the FABRIC VM:
   ```bash
   # Example: check if Grafana is running on port 3000
   fabric_slice_ssh(slice_name, node_name, "curl -s http://localhost:3000/api/health")
   ```

2. **Create the tunnel via REST API**:
   ```bash
   curl -X POST http://localhost:8000/api/slices/<slice_id>/nodes/<node_name>/tunnels \
     -H "Content-Type: application/json" \
     -d '{
       "remote_port": 3000,
       "label": "Grafana Dashboard"
     }'
   ```

   Response includes the assigned local port:
   ```json
   {"local_port": 9100, "remote_port": 3000, "label": "Grafana Dashboard", "status": "active"}
   ```

3. **Access the service**: The service is now available at the local port
   (9100-9199 range) through the WebUI's Web Apps panel.

4. **List active tunnels**:
   ```bash
   curl -s http://localhost:8000/api/slices/<slice_id>/nodes/<node_name>/tunnels
   ```

5. **Remove a tunnel**:
   ```bash
   curl -X DELETE http://localhost:8000/api/slices/<slice_id>/nodes/<node_name>/tunnels/<local_port>
   ```

## Common Services to Tunnel

| Service | Default Port | Image/Install |
|---------|-------------|---------------|
| Grafana | 3000 | `docker run -d -p 3000:3000 grafana/grafana` |
| Prometheus | 9090 | `docker run -d -p 9090:9090 prom/prometheus` |
| Jupyter | 8888 | `jupyter lab --ip=0.0.0.0 --port=8888 --no-browser` |
| Streamlit | 8501 | `streamlit run app.py --server.port 8501` |
| Node-RED | 1880 | `docker run -d -p 1880:1880 nodered/node-red` |
| Open WebUI | 3000 | `docker run -d -p 3000:8080 ghcr.io/open-webui/open-webui` |

## Tips

- Tunnel ports are assigned from 9100-9199 range (first available)
- Tunnels persist until the container restarts or the slice is deleted
- Services must bind to `0.0.0.0` or `localhost` on the VM
- For auth-protected services, disable auth or set up credentials before tunneling
- The WebUI "Web Apps" panel shows all active tunnels with clickable links
