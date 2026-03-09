#!/bin/bash
# Install P4 BMv2 switch and p4c compiler on Debian/Ubuntu
set -euo pipefail

echo "=== Installing dependencies ==="
apt-get update
apt-get install -y git automake cmake libtool g++ libboost-all-dev \
    libgc-dev bison flex libfl-dev pkg-config python3-pip \
    libgrpc++-dev protobuf-compiler-grpc libprotobuf-dev \
    docker.io

systemctl enable --now docker

echo "=== Installing BMv2 via Docker ==="
docker pull pruth/fabric-images:0.0.2j

echo "=== Installing p4c compiler ==="
docker pull p4lang/p4c:stable

# Create convenience wrapper scripts
cat > /usr/local/bin/p4c-wrapper <<'SCRIPT'
#!/bin/bash
docker run --rm -v "$(pwd):/work" -w /work p4lang/p4c:stable p4c "$@"
SCRIPT
chmod +x /usr/local/bin/p4c-wrapper

# Create auto-connect watcher for BMv2
cat > /usr/local/bin/p4-auto-connect.sh <<'SCRIPT'
#!/bin/bash
# Auto-detect new dataplane interfaces for P4 BMv2
KNOWN_FILE="/var/run/p4-known-interfaces"
touch "$KNOWN_FILE"
for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -v -E '^(lo|eth0|ens3|docker|br|ovs|veth|virbr)'); do
    if ! grep -qx "$iface" "$KNOWN_FILE"; then
        echo "$iface" >> "$KNOWN_FILE"
        logger "p4-auto-connect: detected new interface $iface — available for BMv2"
    fi
done
SCRIPT
chmod +x /usr/local/bin/p4-auto-connect.sh

cat > /etc/systemd/system/p4-auto-connect.service <<'EOF'
[Unit]
Description=P4 BMv2 Auto-Connect Dataplane Interfaces
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/p4-auto-connect.sh
EOF

cat > /etc/systemd/system/p4-auto-connect.timer <<'EOF'
[Unit]
Description=P4 BMv2 Auto-Connect Timer

[Timer]
OnBootSec=10
OnUnitActiveSec=15

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now p4-auto-connect.timer

echo "=== P4 BMv2 Switch installed with auto-connect timer ==="
docker images | grep -E "(pruth|p4lang)" || true
