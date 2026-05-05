# LoomAI Kubernetes Deployment

Deploy LoomAI as a multi-user service on Kubernetes using the included Helm chart. Each authenticated user gets a dedicated LoomAI container with persistent storage, FABRIC tokens, and full access to the LoomAI GUI, CLI, and AI tools.

## Architecture

```
Browser ──HTTPS──► LoadBalancer ──► configurable-http-proxy (CHP)
                                       │
                         ┌─────────────┼─────────────┐
                         ▼             ▼             ▼
                    LoomAI Hub    User Pod:alice  User Pod:bob
                    (FastAPI)     (loomai:latest)  (loomai:latest)
                    port 8081     PVC: 2Gi        PVC: 2Gi

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
- TLS certificate for your domain (see Step 3 below)
- DNS A record pointing to the LoadBalancer IP

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

### 3. Prepare TLS Certificates

HTTPS is required for production. The proxy (CHP) terminates TLS directly — no ingress controller needed.

#### Obtain a certificate

Get a TLS certificate for your domain from your institution's CA (e.g., InCommon/Sectigo) or another provider. You need:
- **Private key** (PEM format, e.g., `loomai.key`)
- **Certificate** (PEM format, e.g., `loomai.cer`)

#### Build the full certificate chain

Most CAs issue leaf certificates without the intermediate CA bundled. Browsers need the full chain. Check your cert:

```bash
# Count certificates in the file (should be ≥2 for a full chain)
grep -c "BEGIN CERTIFICATE" loomai.cer
```

If only 1, download the intermediate and build the chain:

```bash
# Example for InCommon RSA Server CA 2
curl -sO http://crt.sectigo.com/InCommonRSAServerCA2.crt
openssl x509 -inform DER -in InCommonRSAServerCA2.crt -out intermediate.pem

# Build full chain: leaf + intermediate
cat loomai.cer intermediate.pem > fullchain.pem

# Verify the key matches the certificate
openssl x509 -in fullchain.pem -noout -modulus | md5
openssl rsa  -in loomai.key    -noout -modulus | md5
# Both hashes must match
```

#### Create the K8s TLS secret

```bash
kubectl create namespace loomai  # if not already created

kubectl create secret tls loomai-proxy-manual-tls \
  --cert=fullchain.pem \
  --key=loomai.key \
  -n loomai
```

The Helm chart expects this secret name. If you also provide `proxy.https.manual.cert` and `proxy.https.manual.key` in your values file, the chart will create the secret for you instead — but creating it manually avoids putting private keys in a values file.

### 4. Create Your Values File

Create a `my-values.yaml` (this file contains secrets — **do not commit it to git**):

```yaml
hub:
  image:
    name: fabrictestbed/loomai-hub
    tag: "0.1.4"
    pullPolicy: Always
  cookie:
    secure: true       # Required for HTTPS
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
    port: 80          # HTTP port (unused when HTTPS enabled)
  https:
    enabled: true
    type: manual
    # Cert/key loaded from pre-created K8s secret (see Step 3).
    # Alternatively, embed PEM content here and the chart creates
    # the secret for you:
    #   manual:
    #     key: |
    #       -----BEGIN PRIVATE KEY-----
    #       ...
    #       -----END PRIVATE KEY-----
    #     cert: |
    #       -----BEGIN CERTIFICATE-----
    #       ...full chain...
    #       -----END CERTIFICATE-----

singleuser:
  image:
    name: fabrictestbed/loomai
    tag: "0.4.0"
    pullPolicy: Always
  resources:
    requests:
      cpu: 50m
      memory: 512M
    limits:
      cpu: "4"
      memory: 2G
  storage:
    capacity: 2Gi    # AI tools disabled in hub mode; 2Gi sufficient for user data

cull:
  timeout: 28800     # 8 hours idle → stop pod
  every: 600         # Check every 10 minutes
  maxAge: 86400      # 24 hour max lifetime

scheduling:
  imagePuller:
    enabled: true    # Pre-pull LoomAI image on all nodes
```

**Important**: Add your values file to `.gitignore` — it contains CILogon secrets and the Core API token.

### 5. Deploy with Helm

```bash
# Create namespace (if not done in Step 3)
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

### 6. Get the External IP and Configure DNS

```bash
kubectl get svc loomai-proxy-public -n loomai
```

The `EXTERNAL-IP` column shows the LoadBalancer IP. Create a DNS A record for your domain pointing to this IP.

With HTTPS enabled, the service exposes only port 443. Verify:
```bash
kubectl get svc loomai-proxy-public -n loomai
# Should show: 443:xxxxx/TCP (no port 80)
```

### 7. Verify

```bash
# Test TLS handshake and certificate
curl -v https://your-domain.example.com/hub/health 2>&1 | grep "SSL certificate verify"
# Should show: SSL certificate verify ok.

# Test login page
curl -s -o /dev/null -w "%{http_code}" https://your-domain.example.com/hub/login
# Should return: 200
```

Visit `https://your-domain.example.com`. You should see the Hub login page with a CILogon redirect.

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
    tag: "0.4.0"
    pullPolicy: Always
  allowPrivilegeEscalation: true  # Needed for SSH tunnels
  resources:
    requests: { cpu: 500m, memory: 1Gi }
    limits: { cpu: "4", memory: 4Gi }
  storage:
    capacity: 2Gi          # AI tools disabled in hub mode; 2Gi sufficient
    storageClass: ""       # Use cluster default
    homeMountPath: /home/fabric/work
  extraEnv:
    FABRIC_CREDMGR_HOST: cm.fabric-testbed.net
    FABRIC_ORCHESTRATOR_HOST: orchestrator.fabric-testbed.net
    FABRIC_CORE_API_HOST: uis.fabric-testbed.net
    FABRIC_BASTION_HOST: bastion.fabric-testbed.net
  startTimeout: 300        # Seconds to wait for pod readiness
```

**Storage sizing**: The persistent volume stores user data, FABRIC credentials, and notebooks. AI tools are disabled in hub mode, so 2Gi is sufficient. For standalone Docker with all AI tools enabled, ≥5Gi is recommended.

### Proxy (`proxy`)

```yaml
proxy:
  secretToken: ""            # Auto-generated if empty
  service:
    type: LoadBalancer       # or ClusterIP/NodePort
    port: 80                 # HTTP port (only exposed when HTTPS is disabled)
  https:
    enabled: true            # REQUIRED for production
    type: manual             # manual, letsencrypt, or offload
    manual:
      key: ""                # TLS private key (PEM) — optional if K8s secret created manually
      cert: ""               # TLS certificate chain (PEM) — optional if K8s secret created manually
```

**HTTPS types**:
- **`manual`**: You provide TLS cert/key, either as values or as a pre-created K8s secret named `loomai-proxy-manual-tls`. CHP terminates TLS directly.
- **`offload`**: TLS is terminated at the load balancer or ingress level. CHP receives plain HTTP. Use when your cloud provider handles TLS (e.g., AWS ALB, GCP HTTPS LB).
- **`letsencrypt`**: (Not yet implemented) Automatic cert provisioning via Let's Encrypt.

When HTTPS is enabled, the LoadBalancer service exposes only port 443. When disabled, it exposes the configured HTTP port (default 80).

### Idle Culling (`cull`)

```yaml
cull:
  enabled: true
  timeout: 28800    # 8 hours idle → stop pod
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
cd /path/to/loomai

# For amd64 (GKE, most cloud providers):
docker buildx build --platform linux/amd64 \
  -t fabrictestbed/loomai:0.4.0 \
  -t fabrictestbed/loomai:latest \
  -f Dockerfile --push .

# Multi-platform (amd64 + arm64):
docker buildx build --platform linux/amd64,linux/arm64 \
  -t fabrictestbed/loomai:0.4.0 \
  -f Dockerfile --push .

# Or use the build script (includes security audit):
./build/build-multiplatform.sh --push --tag v0.4.0
```

### Hub Image

```bash
cd hub
docker buildx build --platform linux/amd64 \
  -t fabrictestbed/loomai-hub:0.1.4 \
  -t fabrictestbed/loomai-hub:latest \
  -f Dockerfile --push .
```

**Important**: Always use versioned tags (e.g., `0.3.1`) for the singleuser image instead of `latest`. The `latest` tag causes issues:
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
| "being installed by another process" | Stale lock files from previous container | Fixed in v0.4.0+; or manually: `kubectl exec <pod> -- rm -rf /home/fabric/work/.ai-tools/.locks/` |
| JupyterLab "Not Found" | JupyterLab base_url doesn't include sub-path | Fixed in v0.4.0+; JupyterLab base_url now reads `LOOMAI_BASE_PATH` |
| Nginx fails with "pcre2_compile" error | Regex `\d{2}` in nginx config — `{` treated as block delimiter | Fixed in v0.4.0+; uses `[0-9][0-9]` instead |
| Disk full / "No space left on device" | PVC too small for user data | Expand PVC to ≥2Gi (see Expanding User PVC above); AI tools are disabled in hub mode |
| CHP crash "Cannot read properties of null" | Empty proxy route target (HUB_BASE_URL empty) | Fixed in chart; ensure `_helpers.tpl` defaults to `http://loomai-hub:8081` |
| Login redirects to non-existent pod | Hub DB still has "ready" state from previous pod | Restart hub to clear stale state |
| HTTPS connection refused | TLS secret missing or proxy not restarted | Verify: `kubectl get secret loomai-proxy-manual-tls -n loomai` and check proxy logs |
| Certificate not trusted by browser | Missing intermediate CA in cert chain | Build full chain: `cat leaf.cer intermediate.pem > fullchain.pem` and recreate the secret |
| Login fails after switching to HTTPS | CILogon callback URL still uses HTTP | Update callback to `https://...` in both CILogon registration and values file |
| Cookies not persisting (login loop) | `cookie.secure: true` but using HTTP | Set `cookie.secure: false` for HTTP testing, or enable HTTPS |

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

## TLS Certificate Renewal

When your TLS certificate expires, update it without downtime:

```bash
# Build new full chain (leaf + intermediate)
cat new-cert.cer intermediate.pem > fullchain.pem

# Verify key still matches
openssl x509 -in fullchain.pem -noout -modulus | md5
openssl rsa  -in loomai.key    -noout -modulus | md5

# Replace the K8s secret
kubectl delete secret loomai-proxy-manual-tls -n loomai
kubectl create secret tls loomai-proxy-manual-tls \
  --cert=fullchain.pem \
  --key=loomai.key \
  -n loomai

# Restart the proxy to pick up the new cert
kubectl rollout restart deployment loomai-proxy -n loomai

# Verify
curl -v https://your-domain.example.com/hub/health 2>&1 | grep "expire date"
```

If using a new key (not just a renewed cert), also update `proxy.https.manual.key` in your values file if you embedded it there.

## AI Tools in Hub Mode

In hub mode (K8s), each user gets a container with limited persistent storage (default 2Gi PVC). Installing all AI tools would exceed this budget:

| Tool | Install Size | Hub Mode |
|------|-------------|----------|
| **LoomAI** | Built-in (0 MB) | Available |
| **Aider** | ~900 MB | Disabled |
| **Claude Code** | ~1 GB | Disabled |
| **OpenCode** | ~200 MB | Disabled |
| **Crush** | ~150 MB | Disabled |
| **Deep Agents** | ~500 MB | Disabled |

In hub mode, installable AI tools are greyed out in the AI Companion view with a "Local Install Only" badge. LoomAI (the built-in chat assistant) remains fully available since it requires no installation.

**How hub mode is detected**: The frontend checks for `window.__LOOMAI_BASE_PATH`, which is set by the hub spawner when running in K8s. This variable is absent in standalone Docker deployments, where all tools are available.

To use the full set of AI tools, users should run LoomAI locally via Docker:
```bash
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/loomai/main/install.sh | bash
```

## Security Notes

- **HTTPS**: Always use HTTPS in production. Set `proxy.https.enabled: true` with TLS certificates (see Step 3). When enabled, the service exposes only port 443.
- **Cookie security**: Set `hub.cookie.secure: true` (default) when using HTTPS. Set to `false` only for HTTP testing. Secure cookies will not work over plain HTTP.
- **Values file**: Never commit your values file to git — it contains CILogon secrets and the Core API bearer token.
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
