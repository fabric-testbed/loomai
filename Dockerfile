# Combined single-image Dockerfile for fabric-webui
# Serves both the FastAPI backend and nginx frontend in one container

# --- Stage 1: Build frontend ---
FROM node:18-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# --- Stage 2: Final image ---
FROM python:3.11-slim

WORKDIR /app

# Install system deps for FABlib + nginx + supervisord + tmux + sudo
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libffi-dev libssl-dev openssh-client git \
    nginx supervisor tmux sudo \
    && rm -rf /var/lib/apt/lists/*

# Create fabric user with passwordless sudo
RUN useradd -m -s /bin/bash -d /home/fabric fabric && \
    echo "fabric ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/fabric && \
    chmod 0440 /etc/sudoers.d/fabric

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install JupyterLab for per-slice notebook environments
RUN pip install --no-cache-dir jupyterlab
# Default JupyterLab terminals to bash
RUN mkdir -p /etc/jupyter && \
    echo "c.ServerApp.terminado_settings = {'shell_command': ['/bin/bash']}" \
    > /etc/jupyter/jupyter_server_config.py

# Install Node.js for AI CLI tools
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install AI CLI tools
RUN pip install --no-cache-dir aider-chat streamlit
RUN npm install -g @anthropic-ai/claude-code @charmland/crush opencode-ai

# Copy backend code
COPY backend/app/ app/

# Copy version file for update checks (read by backend)
COPY frontend/src/version.ts /app/VERSION

# Copy builtin slice-libraries (slice templates, VM templates, recipes)
COPY slice-libraries/ slice-libraries/

# Copy AI tools config (skills, agents, shared context)
COPY ai-tools/ ai-tools/

# Copy built frontend
COPY --from=frontend-build /app/dist /usr/share/nginx/html

# Nginx config — use localhost since backend runs in same container
RUN rm -f /etc/nginx/sites-enabled/default
# Set pid file to a writable location for non-root nginx
RUN sed -i 's|pid /run/nginx.pid;|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf || \
    sed -i '1i pid /tmp/nginx.pid;' /etc/nginx/nginx.conf
RUN cat > /etc/nginx/conf.d/default.conf <<'NGINX'
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;

    client_max_body_size 500m;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /jupyter/ {
        proxy_pass http://127.0.0.1:8889;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 604800s;
        proxy_send_timeout 604800s;
        proxy_buffering off;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 604800s;
        proxy_send_timeout 604800s;
        proxy_buffering off;
    }
}
NGINX

# Fix nginx directories for non-root operation
RUN mkdir -p /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /var/lib/nginx && \
    chown -R fabric:fabric /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /var/lib/nginx

# Supervisord config to run both nginx and uvicorn as fabric user
RUN cat > /etc/supervisor/conf.d/fabric-webui.conf <<'CONF'
[supervisord]
nodaemon=true
user=root
logfile=/dev/stdout
logfile_maxbytes=0

[program:backend]
command=uvicorn app.main:app --host 0.0.0.0 --port 8000
directory=/app
user=fabric
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:nginx]
command=nginx -g "daemon off;"
user=fabric
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
CONF

# Set up fabric user home and storage
RUN mkdir -p /home/fabric/work/fabric_config && chown -R fabric:fabric /home/fabric
ENV FABRIC_CONFIG_DIR=/home/fabric/work/fabric_config
ENV FABRIC_STORAGE_DIR=/home/fabric/work
ENV HOME=/home/fabric

# Copy entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Frontend on 3000, backend on 8000, 8889 for JupyterLab, 9100-9199 for SSH tunnel proxies
EXPOSE 3000 8000 8889 9100-9199

ENTRYPOINT ["/app/entrypoint.sh"]
