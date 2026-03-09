FROM python:3.11-slim

WORKDIR /app

# Install system deps for FABlib (SSH, etc.) + sudo
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libffi-dev libssl-dev openssh-client git tmux sudo \
    && rm -rf /var/lib/apt/lists/*

# Create fabric user with passwordless sudo
RUN useradd -m -s /bin/bash -d /home/fabric fabric && \
    echo "fabric ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/fabric && \
    chmod 0440 /etc/sudoers.d/fabric

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js for AI CLI tools
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install AI CLI tools
RUN pip install --no-cache-dir aider-chat streamlit
RUN pip install --no-cache-dir jupyterlab
# Default JupyterLab terminals to bash
RUN mkdir -p /etc/jupyter && \
    echo "c.ServerApp.terminado_settings = {'shell_command': ['/bin/bash']}" \
    > /etc/jupyter/jupyter_server_config.py
RUN npm install -g @anthropic-ai/claude-code @charmland/crush opencode-ai

COPY scripts/ scripts/
COPY app/ app/

COPY VERSION /app/VERSION

# Copy AI tool configurations (skills, agents, prompts, shared context)
COPY ai-tools/ ai-tools/

# Copy builtin slice-libraries (slice templates, VM templates, recipes) — synced before build
COPY slice-libraries/ slice-libraries/

RUN mkdir -p /home/fabric/work/fabric_config && chown -R fabric:fabric /home/fabric
ENV FABRIC_CONFIG_DIR=/home/fabric/work/fabric_config
ENV FABRIC_STORAGE_DIR=/home/fabric/work
ENV HOME=/home/fabric

EXPOSE 8000

USER fabric
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
