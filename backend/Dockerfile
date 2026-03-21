FROM python:3.11-slim

WORKDIR /app

# Install system deps + Node.js + Python deps in one layer
# gcc, python3-dev, libffi-dev kept for runtime pip installs (e.g. recordclass via fabrictestbed-extensions)
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev libffi-dev libssl-dev \
    openssh-client git tmux sudo curl \
    vim less htop tree wget jq net-tools iputils-ping dnsutils procps nano \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && pip install --no-cache-dir -r requirements.txt \
    && rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

# Create fabric user with passwordless sudo
RUN useradd -m -s /bin/bash -d /home/fabric fabric && \
    echo "fabric ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/fabric && \
    chmod 0440 /etc/sudoers.d/fabric

# Copy AI tool configurations (skills, agents, prompts, shared context)
COPY ai-tools/ ai-tools/

COPY scripts/ scripts/
COPY app/ app/

COPY VERSION /app/VERSION

RUN mkdir -p /home/fabric/work/fabric_config && chown -R fabric:fabric /home/fabric
ENV FABRIC_CONFIG_DIR=/home/fabric/work/fabric_config
ENV FABRIC_STORAGE_DIR=/home/fabric/work
ENV HOME=/home/fabric

EXPOSE 8000

USER fabric
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
