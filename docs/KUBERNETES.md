# LoomAI Kubernetes Deployment

Deploy LoomAI as a multi-user service on Kubernetes using the included Helm chart. Each authenticated user gets a dedicated LoomAI container with persistent storage, FABRIC tokens, and full access to the LoomAI GUI, CLI, and AI tools.

## Architecture

```
Browser ──HTTPS──► LoadBalancer ──► configurable-http-proxy (CHP)
                                       │
                         ┌─────────────┼─────────────┐
                         ▼             ▼             ▼
                    LoomAI Hub    User Pod:alice  User Pod:bob
                    (FastAPI)     (loomai:0.2.4)  (loomai:0.2.4)
                    port 8081     PVC: 5Gi        PVC: 5Gi

Each user pod runs:
  ┌─────────────────────────────────────────────┐
  │  supervisord                                 │
  │  ├── nginx (port 3000)                       │
  │  │   ├── / → static frontend                 │
  │  │   ├── /api/ → backend:8000                │
  │  │   ├── /ws/ → backend:8000 (WebSocket)     │
  │  │   ├── /jupyter/ → JupyterLab:8889         │
  │  │   ├── /aider/ → Streamlit:9197            │
  │  │   ├── /opencode/ → OpenCode:9198          │
  │  │   └── /tunnel/{port}/ → localhost:{port}  │
  │  └── uvicorn (port 8000) — FastAPI backend   │
  └─────────────────────────────────────────────┘
```

### Components

| Component | Image | Purpose |
|-----------|-------|---------|
| **Hub** | `fabrictestbed/loomai-hub` | CILogon OIDC auth, FABRIC authorization, K8s pod spawning, idle culling |
| **Proxy** | `quay.io/jupyterhub/configurable-http-proxy` | Dynamic HTTP routing to hub and user pods |
| **User pods** | `fabrictestbed/loomai` | Per-user LoomAI instances with persistent storage |

### Authentication Flow

1. User visits the site → CHP routes to Hub → Hub redirects to CILogon
2. CILogon OIDC authorization code flow (with PKCE) → Hub gets `id_token` + `refresh_token`
3. Hub calls FABRIC Core API (`/people/services-auth?sub={sub}`) to verify the user has the required role (default: `Jupyterhub`) — same check as `FabricAuthenticator`
4. Hub calls FABRIC Credential Manager to provision FABRIC tokens
5. Hub stores user + tokens in DB, sets signed session cookie
6. Hub spawns a user pod (if not running), creates a K8s Secret with FABRIC tokens, and adds a CHP proxy route
7. Hub redirects browser to `/user/{username}/` → CHP routes to the user pod

### Sub-Path Routing

User pods are accessed at `/user/{uuid}/`. The entrypoint script:
1. Writes `window.__LOOMAI_BASE_PATH = '/user/{uuid}'` to `env-config.js`
2. Rewrites `/_next/` asset paths in HTML/JS files to include the sub-path prefix
3. Generates an nginx config with location blocks prefixed by the base path
4. JupyterLab is started with `--ServerApp.base_url=/user/{uuid}/jupyter/` so its internal redirects work through CHP

## Prerequisites

- Kubernetes cluster (GKE, EKS, AKS, or similar)
- Helm 3.x
- `kubectl` configured for your cluster
- CILogon OIDC client credentials (register at https://cilogon.org/oauth2/register)
- FABRIC Core API service bearer token
- (Optional) TLS certificate for your domain
- (Optional) DNS record pointing to the LoadBalancer IP

## Step-by-Step Deployment Guide

### 1. Register a CILogon OIDC Client

Go to https://cilogon.org/oauth2/register and create a client:
- **Client Name**: LoomAI
- **Scopes**: `openid email profile org.cilogon.userinfo`
- **Callback URL**: `https://your-domain.example.com/hub/oauth_callback`
  (or `http://LOADBALANCER_IP/hub/oauth_callback` for HTTP testing)
- **Skin**: `FABRIC`

Save the `client_id` and `client_secret`.

### 2. Obtain a FABRIC Core API Bearer Token

Request a service bearer token from the FABRIC team for the UIS API (`https://uis.fabric-testbed.net`). This token is used to verify that users have the required FABRIC role.

### 3. Create Your Values File

Create a `my-values.yaml`:

```yaml
hub:
  image:
    name: fabrictestbed/loomai-hub
    tag: "latest"
    pullPolicy: Always
  admin:
    users:
      - your-email@example.com

auth:
  cilogon:
    clientId: "cilogon:/client_id/YOUR_CLIENT_ID"
    clientSecret: "YOUR_CLIENT_SECRET"
    callbackUrl: "https://your-domain.example.com/hub/oauth_callback"
  fabricCoreAPI:
    bearerToken: "YOUR_SERVICE_BEARER_TOKEN"

proxy:
  service:
    type: LoadBalancer
    port: 80
  https:
    enabled: true
    type: manual
    manual:
      key: |
        -----BEGIN PRIVATE KEY-----
        ...your TLS private key...
        -----END PRIVATE KEY-----
      cert: |
        -----BEGIN CERTIFICATE-----
        ...your TLS certificate (full chain)...
        -----END CERTIFICATE-----

singleuser:
  image:
    name: fabrictestbed/loomai
    tag: "0.2.4"
    pullPolicy: Always
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: "4"
      memory: 4Gi
  storage:
    capacity: 5Gi    # Must be ≥5Gi for AI tools

cull:
  timeout: 3600      # 1 hour idle → stop pod
  every: 600         # Check every 10 minutes
  maxAge: 86400      # 24 hour max lifetime

scheduling:
  imagePuller:
    enabled: true    # Pre-pull LoomAI image on all nodes
```

### 4. Deploy with Helm

```bash
# Create namespace
kubectl create namespace loomai

# Install
cd helm
helm install loomai ./loomai -f my-values.yaml --namespace loomai

# Check status
kubectl get pods -n loomai
```

Expected output:
```
NAME                            READY   STATUS    RESTARTS   AGE
loomai-hub-xxxxx                1/1     Running   0          30s
loomai-image-puller-xxxxx       1/1     Running   0          30s
loomai-proxy-xxxxx              1/1     Running   0          30s
```

### 5. Get the External IP

```bash
kubectl get svc loomai-proxy-public -n loomai
```

The `EXTERNAL-IP` column shows the LoadBalancer IP. If using a domain, create a DNS A record pointing to this IP.

### 6. Update the Callback URL

If you deployed without a domain and used an IP-based callback URL, update your CILogon client registration to use the actual LoadBalancer IP:
```
http://EXTERNAL_IP/hub/oauth_callback
```

### 7. Verify

Visit `http://EXTERNAL_IP` (or `https://your-domain.example.com`). You should see the Hub login page with a CILogon redirect.

## Configuration Reference

### Authentication (`auth`)

```yaml
auth:
  cilogon:
    clientId: ""              # REQUIRED: CILogon OIDC client ID
    clientSecret: ""          # REQUIRED: CILogon OIDC client secret
    callbackUrl: ""           # Auto-derived from ingress if empty
    scopes: "openid email profile org.cilogon.userinfo"
    skin: "FABRIC"
  fabricCoreAPI:
    host: "https://uis.fabric-testbed.net"
    bearerToken: ""           # REQUIRED: Service token for Core API
    requiredRole: Jupyterhub  # Role users must have
  fabricCM:
    host: cm.fabric-testbed.net
    tokenLifetime: 4          # Token lifetime in hours
    scope: all
  allowedUsers: []            # Whitelist (empty = allow all authorized)
  blockedUsers: []            # Blacklist
```

### Hub (`hub`)

```yaml
hub:
  image:
    name: fabrictestbed/loomai-hub
    tag: latest
  resources:
    requests: { cpu: 200m, memory: 256Mi }
    limits: { cpu: "1", memory: 512Mi }
  admin:
    users:
      - admin@email.unc.edu
  cookie:
    maxAge: 86400      # Session lifetime (24h)
    secure: true       # Set to false for HTTP testing
  db:
    type: sqlite       # or postgres
    pvc:
      capacity: 1Gi
```

### User Pods (`singleuser`)

```yaml
singleuser:
  image:
    name: fabrictestbed/loomai
    tag: "0.2.4"
    pullPolicy: Always
  allowPrivilegeEscalation: true  # Needed for SSH tunnels
  resources:
    requests: { cpu: 500m, memory: 1Gi }
    limits: { cpu: "4", memory: 4Gi }
  storage:
    capacity: 5Gi          # ≥5Gi recommended for AI tools
    storageClass: ""       # Use cluster default
    homeMountPath: /home/fabric/work
  extraEnv:
    FABRIC_CREDMGR_HOST: cm.fabric-testbed.net
    FABRIC_ORCHESTRATOR_HOST: orchestrator.fabric-testbed.net
    FABRIC_CORE_API_HOST: uis.fabric-testbed.net
    FABRIC_BASTION_HOST: bastion.fabric-testbed.net
  startTimeout: 300        # Seconds to wait for pod readiness
```

**Storage sizing**: The persistent volume stores user data, FABRIC credentials, and lazy-installed AI tools. JupyterLab alone requires ~900MB. Recommended minimum is 5Gi.

### Proxy (`proxy`)

```yaml
proxy:
  secretToken: ""            # Auto-generated if empty
  service:
    type: LoadBalancer       # or ClusterIP/NodePort
    port: 80
  https:
    enabled: false
    type: manual             # manual, letsencrypt, or offload
    manual:
      key: ""                # TLS private key (PEM)
      cert: ""               # TLS certificate chain (PEM)
```

### Idle Culling (`cull`)

```yaml
cull:
  enabled: true
  timeout: 3600     # 1 hour idle → stop pod
  every: 600        # Check every 10 minutes
  maxAge: 86400     # 24 hour max lifetime
```

### Ingress (alternative to LoadBalancer)

```yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: loomai.fabric-testbed.net
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: loomai-tls
      hosts:
        - loomai.fabric-testbed.net
```

### Scheduling

```yaml
scheduling:
  imagePuller:
    enabled: true          # DaemonSet pre-pulls LoomAI image on all nodes
  placeholders:
    enabled: false
    replicas: 3            # Placeholder pods for faster startup
  userPods:
    nodeAffinity:
      matchNodePurpose: prefer   # prefer or require
```

## Hub Service

The Hub is a FastAPI application at `hub/`. It handles:

- **CILogon OIDC** (`hub/app/auth/cilogon.py`): Authorization code flow with PKCE
- **FABRIC authorization** (`hub/app/auth/fabric_auth.py`): Core API role check + CM token provisioning
- **Pod spawning** (`hub/app/spawner/`): K8s pod/service/PVC/secret lifecycle via `kubernetes_asyncio`
- **Proxy management** (`hub/app/proxy/chp_client.py`): Dynamic route management via CHP REST API
- **Idle culling** (`hub/app/culler/idle_culler.py`): Background task to stop idle/expired pods
- **Session management** (`hub/app/auth/session.py`): Signed cookie sessions via `itsdangerous`
- **Error pages** (`hub/app/routes/health.py`): User-friendly error pages for CHP 503/500/404 errors

### Building the Hub Image

```bash
cd hub
docker build -t fabrictestbed/loomai-hub:latest .
docker push fabrictestbed/loomai-hub:latest

# For GKE (amd64):
docker buildx build --platform linux/amd64 -t fabrictestbed/loomai-hub:latest --push .
```

### Hub Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/hub/login` | GET | Login page with CILogon redirect |
| `/hub/oauth_callback` | GET | CILogon OIDC callback |
| `/hub/logout` | GET | Stop user pod, clear session, redirect to login |
| `/hub/spawn` | GET | Spawn user pod or redirect if running |
| `/hub/admin` | GET | Admin dashboard (admin users only) |
| `/hub/health` | GET | Health check (liveness probe) |
| `/hub/ready` | GET | Readiness check (DB connectivity) |
| `/hub/error/{code}` | GET | Error page shown by CHP when target is unreachable |
| `/hub/api/users/{user}/server` | POST/DELETE | Start/stop user server |
| `/hub/api/users/{user}/server/progress` | GET | SSE spawn progress stream |

### Token Injection

The Hub creates a K8s Secret `loomai-tokens-{username}` containing the CILogon refresh token. This is injected into the user pod as the `CILOGON_REFRESH_TOKEN` environment variable. The entrypoint script uses it to:

1. Write the refresh token to `fabric_config/id_token.json`
2. Run FABlib `verify_and_configure()` to obtain a fresh id_token and set up SSH keys
3. Save the FABlib configuration

### Database

By default, the Hub uses SQLite stored on a small PVC. For production with many users, configure PostgreSQL:

```yaml
hub:
  db:
    type: postgres
    url: "postgresql+asyncpg://user:pass@host:5432/loomai_hub"
```

## Building and Pushing Images

### Single-User Image (LoomAI)

```bash
cd /path/to/loomai-dev

# For amd64 (GKE, most cloud providers):
docker buildx build --platform linux/amd64 \
  -t fabrictestbed/loomai:0.2.4 \
  -f Dockerfile --push .

# Multi-platform (amd64 + arm64):
docker buildx build --platform linux/amd64,linux/arm64 \
  -t fabrictestbed/loomai:0.2.4 \
  -f Dockerfile --push .
```

### Hub Image

```bash
cd hub
docker buildx build --platform linux/amd64 \
  -t fabrictestbed/loomai-hub:latest \
  -f Dockerfile --push .
```

**Important**: Always use versioned tags (e.g., `0.2.4`) for the singleuser image instead of `latest`. The `latest` tag causes issues:
- Kubernetes caches the image digest and won't pull a new image even with `pullPolicy: Always` if the digest hasn't changed in the registry
- Rollout restarts don't trigger when the pod spec hasn't changed (same tag)
- Version tags ensure every `helm upgrade` deploys the exact image you built

## Operations

### Upgrading

```bash
# Update image tag in values, then:
helm upgrade loomai ./helm/loomai -f my-values.yaml --namespace loomai

# If using 'latest' tag and need to force a new pull:
kubectl rollout restart deployment loomai-hub -n loomai
kubectl delete pod <user-pod-name> -n loomai  # User pods must be deleted manually
```

### Scaling

The Hub is a single-replica service (it manages state in a local DB). User pods scale horizontally — each user gets their own pod.

### Monitoring

```bash
# Check all pods
kubectl get pods -n loomai

# Hub logs
kubectl logs -l app.kubernetes.io/component=hub -n loomai -f

# Proxy logs
kubectl logs -l app.kubernetes.io/component=proxy -n loomai -f

# User pod logs (nginx + backend)
kubectl logs loomai-<username-uuid> -n loomai -f

# Check nginx status inside user pod
kubectl exec loomai-<uuid> -n loomai -- supervisorctl status

# Check disk usage
kubectl exec loomai-<uuid> -n loomai -- df -h /home/fabric/work
```

### Expanding User PVC

If a user's persistent volume runs out of space:

```bash
# Check if storage class supports expansion
kubectl get sc -o jsonpath='{range .items[*]}{.metadata.name}: {.allowVolumeExpansion}{"\n"}{end}'

# Expand the PVC (no data loss)
kubectl patch pvc loomai-user-<uuid> -n loomai \
  --type merge -p '{"spec":{"resources":{"requests":{"storage":"10Gi"}}}}'

# Delete the pod so it remounts with the expanded volume
kubectl delete pod loomai-<uuid> -n loomai
```

### Shutting Down

```bash
# Scale down (preserves PVCs and secrets)
kubectl scale deployment loomai-hub -n loomai --replicas=0
kubectl scale deployment loomai-proxy -n loomai --replicas=0
kubectl delete daemonset loomai-image-puller -n loomai

# Full teardown (WARNING: deletes PVCs and user data)
helm uninstall loomai -n loomai
kubectl delete pvc --all -n loomai
kubectl delete namespace loomai
```

### Starting Back Up

```bash
# If scaled down:
helm upgrade loomai ./helm/loomai -f my-values.yaml --namespace loomai
# This restores the deployments to their configured replica counts
```

## Troubleshooting

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `{"detail":"Not Found"}` after login | Hub has stale pod state from previous run | Restart hub: `kubectl rollout restart deployment loomai-hub -n loomai` |
| 503 "Server Starting..." loops | Pod is running but nginx failed inside it | Check `kubectl exec <pod> -- supervisorctl status` and nginx logs |
| `ImagePullBackOff` | Wrong platform (arm64 image on amd64 node) | Build with `--platform linux/amd64` and use a new version tag |
| `no match for platform in manifest` | Same as above; node cached old manifest | Push with a new tag (not `latest`) |
| "being installed by another process" | Stale lock files from previous container | Fixed in v0.2.4+; or manually: `kubectl exec <pod> -- rm -rf /home/fabric/work/.ai-tools/.locks/` |
| JupyterLab "Not Found" | JupyterLab base_url doesn't include sub-path | Fixed in v0.2.4+; JupyterLab base_url now reads `LOOMAI_BASE_PATH` |
| Nginx fails with "pcre2_compile" error | Regex `\d{2}` in nginx config — `{` treated as block delimiter | Fixed in v0.2.4+; uses `[0-9][0-9]` instead |
| Disk full / "No space left on device" | PVC too small for AI tools (~900MB for JupyterLab alone) | Expand PVC to ≥5Gi (see Expanding User PVC above) |
| CHP crash "Cannot read properties of null" | Empty proxy route target (HUB_BASE_URL empty) | Fixed in chart; ensure `_helpers.tpl` defaults to `http://loomai-hub:8081` |
| Login redirects to non-existent pod | Hub DB still has "ready" state from previous pod | Restart hub to clear stale state |

### Checking Inside a User Pod

```bash
# Shell into the pod
kubectl exec -it loomai-<uuid> -n loomai -- bash

# Check services
supervisorctl status

# Test nginx config
nginx -t

# Check nginx config content
cat /etc/nginx/conf.d/default.conf

# Check env-config.js
cat /usr/share/nginx/html/env-config.js

# Check LOOMAI_BASE_PATH
echo $LOOMAI_BASE_PATH

# Check disk usage
df -h /home/fabric/work
du -sh /home/fabric/work/.ai-tools/*

# Test backend health
curl http://127.0.0.1:8000/api/health

# Test nginx proxy
curl http://127.0.0.1:3000/user/$(echo $LOOMAI_BASE_PATH | cut -d/ -f3)/api/health
```

## Security Notes

- **HTTPS**: Always use HTTPS in production. Set `proxy.https.enabled: true` with TLS certificates.
- **Cookie security**: Set `hub.cookie.secure: true` (default) when using HTTPS. Set to `false` only for HTTP testing.
- **Tunnel ports**: The nginx proxy restricts web tunnel access to ports 9100-9199 only (`[0-9][0-9]` regex), preventing users from proxying to arbitrary internal services.
- **Token injection**: FABRIC tokens are stored in K8s Secrets (base64 encoded, not encrypted). Consider enabling K8s secret encryption at rest.
- **Network policies**: The chart includes a NetworkPolicy template for user pods. Review and enable in production.

## File Structure

```
hub/                              # Hub service
├── Dockerfile
├── requirements.txt
├── app/
│   ├── main.py                   # FastAPI app, lifespan
│   ├── config.py                 # Pydantic Settings
│   ├── auth/
│   │   ├── cilogon.py            # CILogon OIDC client
│   │   ├── fabric_auth.py        # FABRIC Core API + CM
│   │   └── session.py            # Signed cookie sessions
│   ├── spawner/
│   │   ├── kubespawner.py        # K8s pod lifecycle
│   │   ├── pod_template.py       # Pod manifest builder
│   │   └── pvc.py                # PVC management
│   ├── proxy/
│   │   └── chp_client.py         # CHP REST client
│   ├── culler/
│   │   └── idle_culler.py        # Idle pod culler
│   ├── db/
│   │   ├── models.py             # SQLAlchemy models
│   │   └── session.py            # Async DB session
│   ├── routes/
│   │   ├── login.py              # Auth routes (login, logout)
│   │   ├── spawn.py              # Spawn routes
│   │   ├── admin.py              # Admin routes
│   │   └── health.py             # Health + error pages
│   └── templates/                # Jinja2 HTML
│       ├── base.html
│       ├── login.html
│       ├── spawn.html
│       └── admin.html
helm/loomai/                      # Helm chart
├── Chart.yaml
├── values.yaml                   # Default configuration
├── values.schema.json            # Values validation
└── templates/
    ├── _helpers.tpl              # Template helpers
    ├── NOTES.txt                 # Post-install instructions
    ├── ingress.yaml
    ├── hub/                      # Hub K8s manifests
    ├── proxy/                    # CHP K8s manifests
    ├── singleuser/               # User pod policies
    └── scheduling/               # Image puller, priority classes
```
