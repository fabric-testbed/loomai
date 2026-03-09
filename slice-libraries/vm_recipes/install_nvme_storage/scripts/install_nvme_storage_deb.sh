#!/bin/bash
# Setup NVMe storage on Debian/Ubuntu systems
set -euo pipefail

echo "=== Installing NVMe tools ==="
apt-get update
apt-get install -y nvme-cli

echo "=== Detecting NVMe devices ==="
COUNTER=0
for dev in $(lsblk -d -n -o NAME,TYPE | awk '$2=="disk" && $1~/^nvme/ {print $1}'); do
    MOUNT="/mnt/nvme${COUNTER}"
    echo "  Formatting /dev/${dev} as ext4 → ${MOUNT}"
    mkfs.ext4 -F "/dev/${dev}"
    mkdir -p "${MOUNT}"
    mount "/dev/${dev}" "${MOUNT}"
    chown "$(logname 2>/dev/null || echo ubuntu):$(logname 2>/dev/null || echo ubuntu)" "${MOUNT}"

    # Add to fstab if not already present
    if ! grep -q "/dev/${dev}" /etc/fstab; then
        echo "/dev/${dev}  ${MOUNT}  ext4  defaults,nofail  0  2" >> /etc/fstab
    fi
    COUNTER=$((COUNTER + 1))
done

if [ "$COUNTER" -eq 0 ]; then
    echo "WARNING: No NVMe devices found. Ensure NVME_P4510 component is attached."
else
    echo "=== ${COUNTER} NVMe device(s) formatted and mounted ==="
fi
df -h /mnt/nvme* 2>/dev/null || true
