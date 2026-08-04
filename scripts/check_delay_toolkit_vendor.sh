#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
LOCK="$ROOT/vendor/delay-analysis-toolkit.upstream.json"
UPSTREAM_URL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["repository"])' "$LOCK")"
UPSTREAM_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$LOCK")"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

git -C "$ROOT" fetch --quiet "$UPSTREAM_URL" "$UPSTREAM_SHA"
git -C "$ROOT" archive "$UPSTREAM_SHA" | tar -x -C "$TEMP_DIR"
diff -qr --exclude='__pycache__' --exclude='*.pyc' \
  "$TEMP_DIR" "$ROOT/vendor/delay-analysis-toolkit"
echo "Vendor tree matches upstream $UPSTREAM_SHA"
