#!/usr/bin/env bash
# ConstructionIQ — Lightsail deploy (run from local Mac).
#
# Strategy:
#   1. Local cross-build (Apple Silicon → linux/amd64) via buildx
#   2. docker save | gzip | ssh | docker load (no registry needed)
#   3. rsync compose + scripts; scp .env.production (chmod 600 remote)
#   4. Optional: rsync data/ + storage/ (--with-data)
#   5. Compose down + up; healthcheck loop
#
# Flags:
#   --with-data       Sync local data/ and storage/ to remote (off by default)
#   --skip-build      Skip docker build (re-use existing local mvp-api:latest tag)
#
# Required local files:
#   .env.production   (copied from .env.production.example, real secrets filled)
#   SSH key at $SSH_KEY_PATH

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────
SSH_HOST="${SSH_HOST:-63.184.32.196}"
SSH_USER="${SSH_USER:-ubuntu}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/Downloads/LightsailDefaultKey-eu-central-1.pem}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/opt/mvp-api}"
IMAGE_TAG="${IMAGE_TAG:-mvp-api:latest}"
PLATFORM="${PLATFORM:-linux/amd64}"
HEALTH_URL="${HEALTH_URL:-http://${SSH_HOST}/api/health}"

WITH_DATA=0
SKIP_BUILD=0
REMOTE_BUILD=0

for arg in "$@"; do
    case "$arg" in
        --with-data)    WITH_DATA=1 ;;
        --skip-build)   SKIP_BUILD=1 ;;
        --remote-build) REMOTE_BUILD=1 ;;
        -h|--help)
            sed -n '2,20p' "$0"; exit 0 ;;
        *)
            echo "Unknown flag: $arg" >&2; exit 2 ;;
    esac
done

# Auto-fallback: no local Docker → remote-build mode
if [ "$REMOTE_BUILD" -eq 0 ] && ! command -v docker >/dev/null 2>&1; then
    REMOTE_BUILD=1
    echo "[info] No local Docker found — switching to --remote-build mode."
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

SSH="ssh -i $SSH_KEY_PATH -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
SSH_TARGET="${SSH_USER}@${SSH_HOST}"

log()  { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. Pre-flight checks ──────────────────────────────────────────────
log "Pre-flight checks"

if [ ! -f "$SSH_KEY_PATH" ]; then
    fail "SSH key not found: $SSH_KEY_PATH"
fi
chmod 400 "$SSH_KEY_PATH"
echo "✓ SSH key OK ($SSH_KEY_PATH, chmod 400)"

if [ ! -f .env.production ]; then
    fail ".env.production not found. Copy .env.production.example and fill real secrets."
fi
chmod 600 .env.production
echo "✓ .env.production found and chmod 600"

if ! grep -q '^GOOGLE_API_KEY=.\+' .env.production; then
    warn "GOOGLE_API_KEY appears empty in .env.production"
fi
if ! grep -q '^PINECONE_API_KEY=.\+' .env.production; then
    warn "PINECONE_API_KEY appears empty in .env.production"
fi

if [ "$REMOTE_BUILD" -eq 0 ]; then
    if ! command -v docker >/dev/null; then
        fail "Docker not installed locally. Re-run with --remote-build or install Docker Desktop."
    fi
    if ! docker buildx version >/dev/null 2>&1; then
        fail "docker buildx not available"
    fi
    echo "✓ Docker + buildx OK (local-build mode)"
else
    echo "✓ Remote-build mode (server will build the image)"
fi

log "SSH connectivity test"
if ! $SSH -o BatchMode=yes -o ConnectTimeout=10 "$SSH_TARGET" \
        'echo CONNECTED && hostname && uname -m'; then
    fail "SSH connection failed. Check key path, instance status, and Lightsail firewall (port 22)."
fi

# ── 2. Build + ship image ─────────────────────────────────────────────
if [ "$REMOTE_BUILD" -eq 0 ]; then
    # ── 2a. Local build → save → load on remote ──
    if [ "$SKIP_BUILD" -eq 0 ]; then
        log "Setting up QEMU/binfmt for cross-arch build (idempotent)"
        docker run --privileged --rm tonistiigi/binfmt --install all >/dev/null 2>&1 || true

        log "Building $IMAGE_TAG for $PLATFORM (local)"
        docker buildx build \
            --platform "$PLATFORM" \
            --load \
            -t "$IMAGE_TAG" \
            .
        docker image inspect "$IMAGE_TAG" \
            --format '{{.Architecture}}/{{.Os}} size={{.Size}}' \
            || fail "Build did not produce $IMAGE_TAG"
    else
        warn "--skip-build: re-using local $IMAGE_TAG"
    fi

    log "Shipping image to $SSH_HOST (docker save | gzip | ssh | docker load)"
    docker save "$IMAGE_TAG" | gzip | \
        $SSH "$SSH_TARGET" 'gunzip | sudo docker load'

    log "Syncing compose + scripts to $REMOTE_APP_DIR"
    rsync -avz \
        -e "$SSH" \
        docker-compose.prod.yml \
        "$SSH_TARGET:$REMOTE_APP_DIR/"
    rsync -avz \
        -e "$SSH" \
        --exclude '__pycache__' \
        scripts/ \
        "$SSH_TARGET:$REMOTE_APP_DIR/scripts/"
else
    # ── 2b. Remote build: rsync source, build on server ──
    log "Syncing source tree to $REMOTE_APP_DIR (remote-build)"
    rsync -az --delete \
        --exclude '.git' \
        --exclude '.env' \
        --exclude '.env.*' \
        --exclude '*.pem' --exclude '*.key' \
        --exclude '.venv' --exclude 'venv' \
        --exclude '__pycache__' --exclude '.pytest_cache' \
        --exclude 'frontend/node_modules' \
        --exclude 'frontend/dist' \
        --exclude 'frontend/playwright-report' \
        --exclude 'frontend/test-results' \
        --exclude 'data' \
        --exclude 'storage' \
        --exclude 'logs' --exclude 'cache' --exclude '.cache' \
        --exclude 'uploads' \
        --exclude '.DS_Store' \
        --exclude '26.02.07*' \
        --exclude '.claude' --exclude '.mcp.json' \
        -e "$SSH" \
        ./ "$SSH_TARGET:$REMOTE_APP_DIR/"

    if [ "$SKIP_BUILD" -eq 0 ]; then
        log "Remote build (this can take 5–15 min on a 2 GB instance)"
        $SSH "$SSH_TARGET" "set -e; cd $REMOTE_APP_DIR && sudo docker compose -f docker-compose.prod.yml build"
    else
        warn "--skip-build: re-using existing $IMAGE_TAG on server"
    fi
fi

# ── 5. Ship .env.production (separate, chmod 600 remote) ──────────────
log "Shipping .env.production"
scp -i "$SSH_KEY_PATH" -o IdentitiesOnly=yes \
    .env.production \
    "$SSH_TARGET:$REMOTE_APP_DIR/.env.production"
$SSH "$SSH_TARGET" "chmod 600 $REMOTE_APP_DIR/.env.production"

# ── 6. Optional: data/ + storage/ sync ────────────────────────────────
if [ "$WITH_DATA" -eq 1 ]; then
    log "Syncing data/ and storage/ (opt-in)"
    # --omit-dir-times --no-perms: the remote dirs are owned by the container
    # (root), so rsync as the ubuntu SSH user cannot set dir times/perms and
    # would abort with exit 23 under `set -e` — before storage/ (the parquet
    # tables) ever syncs. Skipping dir time/perm preservation copies content
    # cleanly; the root container reads the files regardless.
    rsync -rlvz --omit-dir-times --no-perms -e "$SSH" \
        --exclude '.cache' --exclude '__pycache__' \
        data/    "$SSH_TARGET:$REMOTE_APP_DIR/data/"
    rsync -rlvz --omit-dir-times --no-perms -e "$SSH" \
        --exclude '__pycache__' \
        storage/ "$SSH_TARGET:$REMOTE_APP_DIR/storage/"
else
    echo "(skipping data/storage sync; pass --with-data to include)"
fi

# ── 7. Restart compose stack ──────────────────────────────────────────
log "Restarting docker compose on remote (no -v, volumes preserved)"
$SSH "$SSH_TARGET" "
    set -e
    cd $REMOTE_APP_DIR
    QDRANT_SERVER_API_KEY=\$(sudo sed -n 's/^QDRANT_API_KEY=//p' .env.production | tail -1)
    if [ -z "\$QDRANT_SERVER_API_KEY" ]; then
        echo "QDRANT_API_KEY must be non-empty in .env.production" >&2
        exit 1
    fi
    export QDRANT_SERVER_API_KEY
    sudo docker compose -f docker-compose.prod.yml down || true
    sudo env QDRANT_SERVER_API_KEY=\"\$QDRANT_SERVER_API_KEY\" docker compose -f docker-compose.prod.yml up -d
    sudo docker compose -f docker-compose.prod.yml ps
"

# ── 8. Healthcheck loop ───────────────────────────────────────────────
log "Healthcheck on $HEALTH_URL"
HEALTH_OK=0
for i in $(seq 1 30); do
    if curl -fsS --max-time 4 "$HEALTH_URL" >/dev/null 2>&1; then
        HEALTH_OK=1
        break
    fi
    printf '.'
    sleep 2
done
echo

if [ "$HEALTH_OK" -ne 1 ]; then
    warn "Healthcheck failed. Last 100 log lines:"
    $SSH "$SSH_TARGET" "sudo docker logs --tail 100 mvp-api" || true
    fail "Deployment unhealthy"
fi

log "Healthcheck OK"
curl -fsS "$HEALTH_URL" && echo

# ── 8b. Self-prune: keep the 2GB box from filling with old versions ───
# Each `docker load` untags the previous mvp-api:latest, leaving a ~2.8GB
# dangling image; remote builds also pile up build cache. Reclaim both now
# that the new image is verified healthy. `image prune -f` only removes
# UNTAGGED images, so mvp-api:latest and the mvp-api:previous rollback survive.
log "Pruning old images + build cache on remote (self-clean)"
$SSH "$SSH_TARGET" "
    sudo docker image prune -f || true
    # Cap build cache. Newer Docker renamed --keep-storage to --reserved-space;
    # try the new flag, fall back to the old one, then to an unbounded prune.
    sudo docker builder prune -f --reserved-space 2GB \
        || sudo docker builder prune -f --keep-storage 2GB \
        || sudo docker builder prune -f || true
    echo '--- docker disk usage after prune ---'
    sudo docker system df || true
" || warn "Prune step failed (non-fatal)"

# ── 9. Final summary ──────────────────────────────────────────────────
cat <<EOF

╔══════════════════════════════════════════════════════════════════╗
║  Deploy successful                                              ║
╠══════════════════════════════════════════════════════════════════╣
║  SPA:        http://${SSH_HOST}/                                  ║
║  API docs:   http://${SSH_HOST}/docs                              ║
║  Health:     http://${SSH_HOST}/api/health                        ║
╚══════════════════════════════════════════════════════════════════╝

Useful commands:
  Logs:     ssh -i $SSH_KEY_PATH $SSH_TARGET "sudo docker logs -f mvp-api"
  Restart:  ssh -i $SSH_KEY_PATH $SSH_TARGET "cd $REMOTE_APP_DIR && sudo docker compose -f docker-compose.prod.yml restart"
  Stop:     ssh -i $SSH_KEY_PATH $SSH_TARGET "cd $REMOTE_APP_DIR && sudo docker compose -f docker-compose.prod.yml stop"
  Status:   ssh -i $SSH_KEY_PATH $SSH_TARGET "sudo docker ps && free -h"
EOF
