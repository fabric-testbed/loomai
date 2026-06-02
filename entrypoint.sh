#!/bin/bash
# Entrypoint: fix volume ownership then start supervisord.
# Runs as root so it can chown the mounted volume, then supervisord
# launches backend and nginx as the fabric user.
chown -R fabric:fabric /home/fabric/work 2>/dev/null || true

# If LOOMAI_BASE_PATH is set (K8s sub-path deployment), rewrite all asset
# references in HTML and JS files to use the sub-path prefix, and generate
# an nginx config that serves under the base path.
if [ -n "$LOOMAI_BASE_PATH" ]; then
    echo "window.__LOOMAI_BASE_PATH = '${LOOMAI_BASE_PATH}';" > /usr/share/nginx/html/env-config.js

    # Rewrite /_next/ references in HTML and JS files to use the sub-path.
    # This ensures the browser fetches assets through /user/{uuid}/_next/...
    # which CHP routes to this pod.
    find /usr/share/nginx/html \( -name '*.html' -o -name '*.js' \) -exec sed -i \
        "s|/_next/|${LOOMAI_BASE_PATH}/_next/|g" \
        {} +

    # Also fix icon and env-config paths in HTML
    find /usr/share/nginx/html -name '*.html' -exec sed -i \
        -e "s|href=\"/icon|href=\"${LOOMAI_BASE_PATH}/icon|g" \
        -e "s|src=\"/env-config.js\"|src=\"${LOOMAI_BASE_PATH}/env-config.js\"|g" \
        {} +

    # Extract the username (UUID) from LOOMAI_BASE_PATH (/user/{uuid})
    LOOMAI_USER=$(echo "$LOOMAI_BASE_PATH" | sed 's|^/user/||')
    # Hub internal URL for auth subrequests (default to K8s service name)
    LOOMAI_HUB="${LOOMAI_HUB_URL:-http://loomai-hub:8081}"

    # Rewrite nginx config for sub-path routing with auth
    cat > /etc/nginx/conf.d/default.conf <<NGINX
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;

    client_max_body_size 500m;

    # --- Auth subrequest: validates session cookie via hub ---
    location = /_auth_check {
        internal;
        proxy_pass ${LOOMAI_HUB}/hub/api/auth/check?user=${LOOMAI_USER};
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI \$request_uri;
        proxy_set_header Cookie \$http_cookie;
        proxy_connect_timeout 5s;
        proxy_read_timeout 5s;
    }

    # On 401 (no session) redirect to hub login
    error_page 401 = @login_redirect;
    location @login_redirect {
        return 302 /hub/login;
    }

    # Serve the app under the base path (CHP routes /user/{uuid}/* here)
    # Rewrite strips the base path so root-relative files resolve correctly.
    location ${LOOMAI_BASE_PATH}/ {
        auth_request /_auth_check;
        rewrite ^${LOOMAI_BASE_PATH}/(.*)\$ /\$1 break;
        root /usr/share/nginx/html;
        try_files \$uri \$uri/ /index.html;
    }

    location ${LOOMAI_BASE_PATH}/api/ {
        auth_request /_auth_check;
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    location ${LOOMAI_BASE_PATH}/jupyter/ {
        auth_request /_auth_check;
        set \$jupyter_upstream http://127.0.0.1:8889;
        proxy_pass \$jupyter_upstream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 604800s;
        proxy_send_timeout 604800s;
        proxy_buffering off;
    }

    location ${LOOMAI_BASE_PATH}/aider/ {
        auth_request /_auth_check;
        proxy_pass http://127.0.0.1:9197/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 604800s;
        proxy_send_timeout 604800s;
        proxy_buffering off;
    }

    location ${LOOMAI_BASE_PATH}/opencode/ {
        auth_request /_auth_check;
        proxy_pass http://127.0.0.1:9198/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 604800s;
        proxy_send_timeout 604800s;
        proxy_buffering off;
    }

    location ~ ^${LOOMAI_BASE_PATH}/tunnel/(91[0-9][0-9])/(.*) {
        auth_request /_auth_check;
        proxy_pass http://127.0.0.1:\$1/\$2\$is_args\$args;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 604800s;
        proxy_send_timeout 604800s;
        proxy_buffering off;
    }

    location ${LOOMAI_BASE_PATH}/ws/ {
        auth_request /_auth_check;
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 604800s;
        proxy_send_timeout 604800s;
        proxy_buffering off;
    }

    # Fallbacks for root-path requests (favicon, env-config)
    location /env-config.js {
        alias /usr/share/nginx/html/env-config.js;
    }

    location /icon.svg {
        alias /usr/share/nginx/html/icon.svg;
    }
}
NGINX
fi

# If CILogon refresh token is injected via env var (K8s hub), write the token
# file and run FABlib to configure credentials. Only overwrite if the existing
# token is expired or missing.
if [ -n "$CILOGON_REFRESH_TOKEN" ]; then
    export FABRIC_TOKEN_LOCATION=/home/fabric/work/fabric_config/id_token.json

    su -c 'python3 -c "
import json, os, time, base64

token_file = os.environ.get(\"FABRIC_TOKEN_LOCATION\", \"/home/fabric/work/fabric_config/id_token.json\")
os.makedirs(os.path.dirname(token_file), exist_ok=True)
refresh_token = os.environ[\"CILOGON_REFRESH_TOKEN\"]

# Check if existing token file has a valid (non-expired) id_token
needs_update = True
if os.path.exists(token_file):
    try:
        with open(token_file) as f:
            existing = json.load(f)
        id_tok = existing.get(\"id_token\", \"\")
        if id_tok:
            payload = id_tok.split(\".\")[1]
            payload += \"=\" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            if claims.get(\"exp\", 0) > time.time():
                needs_update = False
                print(\"FABlib: existing id_token still valid, skipping update\")
    except Exception:
        pass  # missing, corrupt, or no id_token — update

if needs_update:
    # Write the refresh token; FABlib verify_and_configure will use it to obtain a fresh id_token
    with open(token_file, \"w\") as f:
        json.dump({\"refresh_token\": refresh_token}, f)
    os.chmod(token_file, 0o600)
    print(\"FABlib: wrote refresh token to id_token.json\")

# Auto-set project_id from FABRIC_PROJECT_ID env var (injected by hub authenticator)
storage_dir = os.environ.get(\"FABRIC_STORAGE_DIR\", \"/home/fabric/work\")
settings_file = os.path.join(storage_dir, \".loomai\", \"settings.json\")
fabric_rc_file = os.path.join(storage_dir, \"fabric_config\", \"fabric_rc\")
hub_project_id = os.environ.get(\"FABRIC_PROJECT_ID\", \"\")

settings = {}
if os.path.exists(settings_file):
    try:
        with open(settings_file) as f:
            settings = json.load(f)
    except Exception:
        pass

current_project = settings.get(\"fabric\", {}).get(\"project_id\", \"\")

if not current_project and hub_project_id:
    # First launch — use the project_id injected by the hub authenticator
    settings.setdefault(\"fabric\", {})[\"project_id\"] = hub_project_id
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)
    with open(settings_file, \"w\") as f:
        json.dump(settings, f, indent=2)

    # Update fabric_rc
    if os.path.exists(fabric_rc_file):
        with open(fabric_rc_file) as f:
            rc_lines = f.readlines()
        found = False
        for i, line in enumerate(rc_lines):
            if line.startswith(\"export FABRIC_PROJECT_ID=\"):
                rc_lines[i] = f\"export FABRIC_PROJECT_ID={hub_project_id}\\n\"
                found = True
                break
        if not found:
            rc_lines.append(f\"export FABRIC_PROJECT_ID={hub_project_id}\\n\")
        with open(fabric_rc_file, \"w\") as f:
            f.writelines(rc_lines)

    print(f\"FABlib: set project_id from hub: {hub_project_id}\")
elif current_project:
    # Returning user — ensure env var matches persisted setting
    os.environ[\"FABRIC_PROJECT_ID\"] = current_project
    print(f\"FABlib: using existing project_id {current_project}\")

# Auto-set bastion_username from FABRIC_BASTION_LOGIN env var (injected by hub)
hub_bastion_login = os.environ.get(\"FABRIC_BASTION_LOGIN\", \"\")
current_bastion = settings.get(\"fabric\", {}).get(\"bastion_username\", \"\")
if not current_bastion and hub_bastion_login:
    settings.setdefault(\"fabric\", {})[\"bastion_username\"] = hub_bastion_login
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)
    with open(settings_file, \"w\") as f:
        json.dump(settings, f, indent=2)

    # Update fabric_rc
    if os.path.exists(fabric_rc_file):
        with open(fabric_rc_file) as f:
            rc_lines = f.readlines()
        found = False
        for i, line in enumerate(rc_lines):
            if line.startswith(\"export FABRIC_BASTION_USERNAME=\"):
                rc_lines[i] = f\"export FABRIC_BASTION_USERNAME={hub_bastion_login}\\n\"
                found = True
                break
        if not found:
            rc_lines.append(f\"export FABRIC_BASTION_USERNAME={hub_bastion_login}\\n\")
        with open(fabric_rc_file, \"w\") as f:
            f.writelines(rc_lines)

    print(f\"FABlib: set bastion_username from hub: {hub_bastion_login}\")
elif current_bastion:
    print(f\"FABlib: using existing bastion_username {current_bastion}\")

try:
    from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager
    fablib = fablib_manager()
    fablib.verify_and_configure()
    print(\"FABlib: verify_and_configure completed successfully\")
    fablib.save_config()
    print(\"FABlib: save_config completed\")
except Exception as e:
    print(f\"WARN: FABlib verify_and_configure/save_config failed: {e}\")

# Ensure id_token.json is valid JSON (FABlib may produce concatenated output)
try:
    with open(token_file) as f:
        raw = f.read().strip()
    # Try normal parse first
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        # Find the last complete JSON object (FABlib appends a second one)
        decoder = json.JSONDecoder()
        pos = 0
        last_obj = None
        while pos < len(raw):
            try:
                obj, end = decoder.raw_decode(raw, pos)
                last_obj = obj
                pos = end
            except json.JSONDecodeError:
                pos += 1
        if last_obj is not None:
            with open(token_file, \"w\") as f:
                json.dump(last_obj, f, indent=2)
            os.chmod(token_file, 0o600)
            print(\"FABlib: fixed concatenated JSON in id_token.json\")
except Exception as e:
    print(f\"WARN: token file validation failed: {e}\")
"' fabric
fi

# ---------------------------------------------------------------------------
# Standalone Docker password protection
# ---------------------------------------------------------------------------
# Skip auth setup in K8s mode (Hub handles authentication)
if [ -z "$LOOMAI_BASE_PATH" ] && [ "$LOOMAI_NO_AUTH" != "1" ]; then
    export LOOMAI_AUTH_ENABLED=1
    HASH_FILE="${FABRIC_STORAGE_DIR:-/home/fabric/work}/.loomai/password_hash"

    if [ -n "$LOOMAI_PASSWORD" ]; then
        # User-supplied password — write bcrypt hash
        python3 -c "
import bcrypt, os, sys
password = sys.argv[1]
path = sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
with open(path, 'wb') as f:
    f.write(hashed)
os.chmod(path, 0o600)
" "$LOOMAI_PASSWORD" "$HASH_FILE"
        chown fabric:fabric "$(dirname "$HASH_FILE")" "$HASH_FILE" 2>/dev/null || true
        echo "=========================================="
        echo "  LoomAI password set from LOOMAI_PASSWORD"
        echo "=========================================="
    elif [ -f "$HASH_FILE" ]; then
        # Existing hash file — reuse stored password
        echo "=========================================="
        echo "  LoomAI: Using existing password"
        echo "=========================================="
    else
        # Generate random password
        GENERATED_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
        python3 -c "
import bcrypt, os, sys
password = sys.argv[1]
path = sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
with open(path, 'wb') as f:
    f.write(hashed)
os.chmod(path, 0o600)
" "$GENERATED_PASSWORD" "$HASH_FILE"
        chown fabric:fabric "$(dirname "$HASH_FILE")" "$HASH_FILE" 2>/dev/null || true
        echo "=========================================="
        echo "  LoomAI password: ${GENERATED_PASSWORD}"
        echo "  Save this password — it won't be shown again"
        echo "  (Set LOOMAI_PASSWORD env var to use your own)"
        echo "=========================================="
    fi
fi

# ---------------------------------------------------------------------------
# Add JupyterLab to supervisord so it auto-restarts on crash
# ---------------------------------------------------------------------------
if [ -n "$LOOMAI_BASE_PATH" ]; then
    JUPYTER_BASE_URL="${LOOMAI_BASE_PATH}/jupyter/"
else
    JUPYTER_BASE_URL="/jupyter/"
fi

cat >> /etc/supervisor/conf.d/fabric-webui.conf <<JLAB

[program:jupyterlab]
command=jupyter lab --no-browser --ip=0.0.0.0 --port=8889
    --ServerApp.token=
    --ServerApp.password=
    --ServerApp.disable_check_xsrf=True
    --ServerApp.allow_origin=*
    --ServerApp.allow_remote_access=True
    --ServerApp.base_url=${JUPYTER_BASE_URL}
    --ServerApp.root_dir=/home/fabric/work
    --ServerApp.terminado_settings={'shell_command': ['/bin/bash']}
directory=/home/fabric/work
user=fabric
autostart=true
autorestart=true
startretries=5
startsecs=10
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
JLAB

exec supervisord -c /etc/supervisor/supervisord.conf
