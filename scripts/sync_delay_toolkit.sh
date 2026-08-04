#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
LOCK="$ROOT/vendor/delay-analysis-toolkit.upstream.json"
URL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["repository"])' "$LOCK")"
BRANCH="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["branch"])' "$LOCK")"
CURRENT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$LOCK")"
REMOTE="delay-toolkit-upstream"

if git -C "$ROOT" remote get-url "$REMOTE" >/dev/null 2>&1; then
  git -C "$ROOT" remote set-url "$REMOTE" "$URL"
else
  git -C "$ROOT" remote add "$REMOTE" "$URL"
fi
git -C "$ROOT" fetch --quiet "$REMOTE" "$BRANCH"
LATEST="$(git -C "$ROOT" rev-parse "$REMOTE/$BRANCH")"

if [ "$CURRENT" = "$LATEST" ]; then
  echo "Delay Analysis Toolkit is already current at $CURRENT"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "changed=false" >> "$GITHUB_OUTPUT"; fi
  exit 0
fi

git -C "$ROOT" subtree pull --prefix=vendor/delay-analysis-toolkit "$REMOTE" "$BRANCH" --squash
python3 - "$LOCK" "$LATEST" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["commit"] = sys.argv[2]
data["synced_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

echo "Updated toolkit from $CURRENT to $LATEST"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "changed=true" >> "$GITHUB_OUTPUT"
  echo "old_sha=$CURRENT" >> "$GITHUB_OUTPUT"
  echo "new_sha=$LATEST" >> "$GITHUB_OUTPUT"
fi
