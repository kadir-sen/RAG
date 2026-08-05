#!/usr/bin/env bash
set -Eeuo pipefail

# Create an immutable pre-deploy copy of every host-mounted COAir data source.
# The script never deletes data or old backups. A failed backup restarts the
# currently deployed API and exits non-zero, preventing the image switch.

APP_DIR="${APP_DIR:-/opt/mvp-api}"
BACKUP_ROOT="${BACKUP_ROOT:-$APP_DIR/.deploy-backups}"
API_CONTAINER="${API_CONTAINER:-mvp-api}"
QDRANT_CONTAINER="${QDRANT_CONTAINER:-mvp-qdrant}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-coair}"
QDRANT_API_KEY="${QDRANT_API_KEY:-}"

case "$APP_DIR" in
  ""|/|/opt|/usr|/var|/home) echo "Unsafe APP_DIR: $APP_DIR" >&2; exit 2 ;;
esac
case "$BACKUP_ROOT" in
  ""|/) echo "Unsafe BACKUP_ROOT: $BACKUP_ROOT" >&2; exit 2 ;;
esac

for path in storage data qdrant_storage qdrant_snapshots; do
  if [ ! -d "$APP_DIR/$path" ]; then
    echo "Required persistent directory is missing: $APP_DIR/$path" >&2
    exit 3
  fi
done

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$BACKUP_ROOT/$timestamp"
mkdir -p "$backup_dir"

api_was_running=false
if docker inspect -f '{{.State.Running}}' "$API_CONTAINER" 2>/dev/null | grep -qx true; then
  api_was_running=true
fi

restart_previous_api() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$api_was_running" = true ]; then
    echo "Backup failed; restarting the unchanged API container." >&2
    docker start "$API_CONTAINER" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap restart_previous_api EXIT INT TERM

# Refuse to start unless there is enough free space for a conservative full
# application archive plus one Qdrant collection snapshot. This is deliberately
# pessimistic: safety is preferable to a partial backup followed by deployment.
application_kib="$(du -sk "$APP_DIR/storage" "$APP_DIR/data" \
  | awk '{total += $1} END {print total + 0}')"
qdrant_kib="$(du -sk "$APP_DIR/qdrant_storage" \
  | awk '{total += $1} END {print total + 0}')"
available_kib="$(df -Pk "$BACKUP_ROOT" | awk 'NR == 2 {print $4}')"
# Qdrant may require space for both its native snapshot and the protected copy
# outside the live snapshot mount. Add a further 20% margin and 256 MiB.
source_kib="$((application_kib + qdrant_kib * 2))"
required_kib="$((source_kib + source_kib / 5 + 262144))"
if [ "$available_kib" -lt "$required_kib" ]; then
  echo "Insufficient backup space: need ${required_kib} KiB, have ${available_kib} KiB." >&2
  exit 4
fi

# Stop only the API writer. Qdrant stays up so it can produce its supported,
# transactionally consistent collection snapshot. No container or volume is
# removed by this script.
if [ "$api_was_running" = true ]; then
  docker stop --time 45 "$API_CONTAINER" >/dev/null
fi

snapshot_response="$backup_dir/qdrant-snapshot-response.json"
if docker inspect -f '{{.State.Running}}' "$QDRANT_CONTAINER" 2>/dev/null | grep -qx true; then
  if [ -z "$QDRANT_API_KEY" ]; then
    echo "QDRANT_API_KEY is required to create the pre-deploy snapshot." >&2
    exit 5
  fi
  curl -fsS -X POST \
    -H "api-key: $QDRANT_API_KEY" \
    "http://127.0.0.1:6333/collections/$QDRANT_COLLECTION/snapshots?wait=true" \
    > "$snapshot_response"
  snapshot_name="$(python3 - "$snapshot_response" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
name = str((payload.get("result") or {}).get("name") or "").strip()
if not name:
    raise SystemExit("Qdrant did not return a snapshot name")
print(name)
PY
)"
  snapshot_path="$(find "$APP_DIR/qdrant_snapshots" -type f -name "$snapshot_name" -print -quit)"
  if [ -z "$snapshot_path" ] || [ ! -s "$snapshot_path" ]; then
    echo "Qdrant snapshot was reported but not found on the persistent mount: $snapshot_name" >&2
    exit 6
  fi
  cp --preserve=mode,timestamps "$snapshot_path" "$backup_dir/$snapshot_name"
else
  echo "Qdrant container is not running; refusing an incomplete deploy backup." >&2
  exit 7
fi

# storage contains user/project/billing/report databases and derived artifacts;
# data contains original uploaded source files. Tar preserves permissions and
# relative paths, and writing to a new timestamped directory never overwrites a
# previous backup.
tar -C "$APP_DIR" -cf "$backup_dir/application-data.tar" storage data

(
  cd "$backup_dir"
  sha256sum application-data.tar "$snapshot_name" > SHA256SUMS
  sha256sum -c SHA256SUMS
)

storage_files="$(find "$APP_DIR/storage" -type f | wc -l | tr -d ' ')"
data_files="$(find "$APP_DIR/data" -type f | wc -l | tr -d ' ')"
cat > "$backup_dir/manifest.txt" <<EOF
created_at=$timestamp
app_dir=$APP_DIR
api_container=$API_CONTAINER
qdrant_collection=$QDRANT_COLLECTION
qdrant_snapshot=$snapshot_name
storage_files=$storage_files
data_files=$data_files
application_archive=application-data.tar
checksums=SHA256SUMS
EOF

test -s "$backup_dir/application-data.tar"
test -s "$backup_dir/$snapshot_name"
test -s "$backup_dir/SHA256SUMS"
test -s "$backup_dir/manifest.txt"

# On success the old API intentionally remains stopped; the deploy workflow
# immediately starts the new image. Its rollback path starts the previous image
# if the new health check fails.
trap - EXIT INT TERM
echo "Verified pre-deploy backup: $backup_dir"
