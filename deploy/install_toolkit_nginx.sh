#!/usr/bin/env bash
#
# Adds the /toolkit/ location to the live COAir nginx site. Run once, as root,
# on the server:
#
#   sudo deploy/install_toolkit_nginx.sh deploy/nginx
#
# Re-running is safe: the snippet is refreshed every time, the include line is
# added only if it is missing, and a config that fails `nginx -t` is rolled
# back to exactly what was there before.
set -euo pipefail

SOURCE_DIR="${1:?source directory is required}"
TARGET="${2:-/etc/nginx/sites-available/default}"
SNIPPET_TARGET="/etc/nginx/snippets/coair-toolkit.conf"
BACKUP="${TARGET}.coair-toolkit-backup"

test -f "$SOURCE_DIR/coair-toolkit.conf"
test -f "$TARGET"

cp "$TARGET" "$BACKUP"
mkdir -p "$(dirname "$SNIPPET_TARGET")"
install -m 0644 "$SOURCE_DIR/coair-toolkit.conf" "$SNIPPET_TARGET"

if ! grep -q 'snippets/coair-toolkit.conf' "$TARGET"; then
  python3 - "$TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
stack = []
blocks = []
for index, line in enumerate(lines):
    code = line.split("#", 1)[0]
    for char in code:
        if char == "{":
            stack.append((index, bool(re.search(r"\bserver\s*\{", code))))
        elif char == "}" and stack:
            start, is_server = stack.pop()
            if is_server:
                body = "".join(lines[start:index + 1])
                if re.search(r"proxy_pass\s+http://(?:127\.0\.0\.1|localhost):8000", body):
                    blocks.append((start, index))

if not blocks:
    raise SystemExit("No COAir nginx server block proxying port 8000 was found")

for _, end in sorted(blocks, reverse=True):
    indent = re.match(r"\s*", lines[end]).group(0) + "    "
    lines.insert(end, f"{indent}include /etc/nginx/snippets/coair-toolkit.conf;\n")
path.write_text("".join(lines), encoding="utf-8")
PY
fi

if ! nginx -t; then
  cp "$BACKUP" "$TARGET"
  nginx -t
  exit 1
fi

systemctl reload nginx
rm -f "$BACKUP"
