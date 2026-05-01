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

    # Rewrite nginx config for sub-path routing
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

    # Serve the app under the base path (CHP routes /user/{uuid}/* here)
    # Rewrite strips the base path so root-relative files resolve correctly.
    location ${LOOMAI_BASE_PATH}/ {
        rewrite ^${LOOMAI_BASE_PATH}/(.*)\$ /\$1 break;
        root /usr/share/nginx/html;
        try_files \$uri \$uri/ /index.html;
    }

    location ${LOOMAI_BASE_PATH}/api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    location ${LOOMAI_BASE_PATH}/jupyter/ {
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
    # Write only the refresh token; FABlib will use it to obtain a fresh id_token
    with open(token_file, \"w\") as f:
        json.dump({\"refresh_token\": refresh_token}, f)
    os.chmod(token_file, 0o600)
    print(\"FABlib: wrote refresh token to id_token.json\")

try:
    from fabrictestbed_extensions.fablib.fablib import FablibManager as fablib_manager
    fablib = fablib_manager()
    fablib.verify_and_configure()
    fablib.save_config()
    print(\"FABlib: verify_and_configure completed successfully\")
except Exception as e:
    print(f\"WARN: FABlib verify_and_configure failed: {e}\")
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

exec supervisord -c /etc/supervisor/supervisord.conf
