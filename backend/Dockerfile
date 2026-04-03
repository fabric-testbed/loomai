FROM python:3.11-slim

WORKDIR /app

# FABlib branch to install (override at build time or runtime)
ARG FABLIB_BRANCH=fabvis

# Install system deps + Node.js + Python deps in one layer
# gcc, python3-dev, libffi-dev kept for runtime pip installs (e.g. recordclass via fabrictestbed-extensions)
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libffi-dev libssl-dev \
    openssh-client git tmux sudo curl \
    vim less htop tree wget jq net-tools iputils-ping dnsutils procps nano \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && sed -i "s|fabrictestbed-extensions.*|fabrictestbed-extensions @ git+https://github.com/fabric-testbed/fabrictestbed-extensions.git@${FABLIB_BRANCH}|" requirements.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y jupyter-collaboration jupyter-collaboration-ui jupyter-docprovider jupyter-server-ydoc jupyter-server-documents 2>/dev/null || true \
    && rm -f /usr/local/etc/jupyter/jupyter_server_config.d/jupyter_server_documents.json \
       /usr/local/etc/jupyter/jupyter_server_config.d/jupyter_collaboration.json 2>/dev/null || true \
    && rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

# Persist the branch used at build time for runtime comparison
ENV FABLIB_BRANCH_BUILD=${FABLIB_BRANCH}

# Create fabric user with passwordless sudo
RUN useradd -m -s /bin/bash -d /home/fabric fabric && \
    echo "fabric ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/fabric && \
    chmod 0440 /etc/sudoers.d/fabric

# Copy AI tool configurations (skills, agents, prompts, shared context)
COPY ai-tools/ ai-tools/

# Install loomai CLI
COPY cli/ /app/cli/
RUN pip install --no-cache-dir /app/cli/ && rm -rf /app/cli/

COPY scripts/ scripts/
COPY app/ app/

COPY VERSION /app/VERSION

RUN mkdir -p /home/fabric/work/fabric_config && chown -R fabric:fabric /home/fabric
ENV FABRIC_CONFIG_DIR=/home/fabric/work/fabric_config
ENV FABRIC_STORAGE_DIR=/home/fabric/work
ENV HOME=/home/fabric

EXPOSE 8000

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

USER fabric
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
