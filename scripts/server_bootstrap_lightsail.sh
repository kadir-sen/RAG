#!/usr/bin/env bash
# Lightsail Ubuntu server bootstrap (one-time).
# Idempotent: safe to re-run.
#
# Usage (from local Mac):
#   scp -i ~/Downloads/LightsailDefaultKey-eu-central-1.pem \
#       scripts/server_bootstrap_lightsail.sh ubuntu@63.184.32.196:/tmp/
#   ssh -i ~/Downloads/LightsailDefaultKey-eu-central-1.pem \
#       ubuntu@63.184.32.196 'bash /tmp/server_bootstrap_lightsail.sh'

set -euo pipefail

REMOTE_APP_DIR="/opt/mvp-api"
SWAP_SIZE_MB=2048
SWAPFILE="/swapfile"

log() { printf '\n=== %s ===\n' "$*"; }

# ── 1. System packages ─────────────────────────────────────────────────
log "apt update + base packages"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg rsync jq htop unzip

# ── 2. Swap (2 GB) ─────────────────────────────────────────────────────
log "Swap setup (2 GB)"
if swapon --show | grep -q "$SWAPFILE"; then
    echo "Swap already active on $SWAPFILE"
else
    if [ ! -f "$SWAPFILE" ]; then
        echo "Creating $SWAPFILE (${SWAP_SIZE_MB} MB)"
        if ! sudo fallocate -l "${SWAP_SIZE_MB}M" "$SWAPFILE" 2>/dev/null; then
            sudo dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_SIZE_MB" status=progress
        fi
        sudo chmod 600 "$SWAPFILE"
        sudo mkswap "$SWAPFILE"
    fi
    sudo swapon "$SWAPFILE"
    if ! grep -q "^$SWAPFILE " /etc/fstab; then
        echo "$SWAPFILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
    fi
fi
free -h

# ── 3. Docker engine + compose plugin (official repo) ──────────────────
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker already installed: $(docker --version)"
else
    log "Installing Docker Engine + Compose plugin"
    for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
        sudo apt-get remove -y "$pkg" 2>/dev/null || true
    done
    sudo install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/docker.asc ]; then
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
             -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc
    fi
    if [ ! -f /etc/apt/sources.list.d/docker.list ]; then
        ARCH="$(dpkg --print-architecture)"
        CODENAME="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
        echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
            | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    fi
    sudo apt-get update -y
    sudo apt-get install -y \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
fi

sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu || true

# ── 4. Docker daemon: log rotation ─────────────────────────────────────
log "Docker daemon log rotation"
DAEMON_JSON="/etc/docker/daemon.json"
sudo mkdir -p /etc/docker
if [ ! -f "$DAEMON_JSON" ]; then
    sudo tee "$DAEMON_JSON" >/dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "20m",
    "max-file": "3"
  }
}
EOF
    sudo systemctl restart docker
    echo "Wrote $DAEMON_JSON and restarted docker"
else
    echo "$DAEMON_JSON exists; leaving untouched. Current contents:"
    sudo cat "$DAEMON_JSON"
fi

# ── 5. App directories ─────────────────────────────────────────────────
log "App directory $REMOTE_APP_DIR"
sudo mkdir -p "$REMOTE_APP_DIR"/{storage,data}
sudo chown -R ubuntu:ubuntu "$REMOTE_APP_DIR"
ls -la "$REMOTE_APP_DIR"

# ── 6. Smoke test ──────────────────────────────────────────────────────
log "Docker hello-world smoke test"
sudo docker run --rm hello-world | tail -5

# ── 7. Summary ─────────────────────────────────────────────────────────
log "Bootstrap complete"
docker --version || sudo docker --version
docker compose version || sudo docker compose version
echo
echo "Memory:"; free -h
echo "Disk:";   df -h /
echo
echo "NOTE: 'ubuntu' was added to docker group; existing SSH session may need re-login"
echo "      for sudo-less docker. Use 'sudo docker' in the meantime."
