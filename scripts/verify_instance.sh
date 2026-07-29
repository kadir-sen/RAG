#!/usr/bin/env bash
# Compare a COAir instance against the record it is supposed to be serving.
#
# Written for the 2 GB → 8 GB Lightsail move: run it against the old box to take
# a baseline, then against the new one and diff the two outputs. Anything that
# did not survive the move shows up as a changed number.
#
#   ./scripts/verify_instance.sh http://18.185.38.217  > baseline.txt
#   ./scripts/verify_instance.sh http://<new-ip>       > after.txt
#   diff baseline.txt after.txt
#
# The chat check is the one that matters most and the one that is easiest to
# skip: every other number can come back correct while qdrant_storage/ is
# missing, and the only symptom would be a chatbot that quietly stops finding
# anything. It costs one LLM call.
#
# Note: that check creates a conversation, so the conversation count rises by
# one per run. A +1 between baseline and after is the script's own doing, not a
# migration artefact.
#
# Usage: verify_instance.sh <base-url> [username] [password]
set -uo pipefail

BASE="${1:?usage: verify_instance.sh <base-url> [username] [password]}"
USER_NAME="${2:-admin2}"
PASS="${3:-admin123}"
BASE="${BASE%/}"

say() { printf '%-34s %s\n' "$1" "$2"; }

# ── health ──────────────────────────────────────────────────────────────
health=$(curl -s --max-time 30 "$BASE/api/health" 2>/dev/null)
say "health" "${health:-UNREACHABLE}"
[ -z "$health" ] && { echo "Cannot reach $BASE — stopping."; exit 1; }

# ── auth ────────────────────────────────────────────────────────────────
TOKEN=$(curl -s --max-time 60 -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER_NAME\",\"password\":\"$PASS\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
if [ -z "$TOKEN" ]; then
  say "login" "FAILED — users.db did not come across?"
  exit 1
fi
say "login" "ok"
AUTH=(-H "Authorization: Bearer $TOKEN")

# ── the corpus ──────────────────────────────────────────────────────────
say "documents (library)" "$(curl -s --max-time 180 "${AUTH[@]}" "$BASE/api/library" \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo ERROR)"

say "events (chronology)" "$(curl -s --max-time 120 "${AUTH[@]}" "$BASE/api/chronology/summary" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("total_events","ERROR"))' 2>/dev/null || echo ERROR)"

say "authored chronologies" "$(curl -s --max-time 60 "${AUTH[@]}" "$BASE/api/chronology/subjects" \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("subjects",[])))' 2>/dev/null || echo ERROR)"

say "conversations" "$(curl -s --max-time 120 "${AUTH[@]}" "$BASE/api/conversations" \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo ERROR)"

# ── the viewer: a PDF page must render, not just resolve ────────────────
read -r -d '' PY_VIEWER <<'PY' || true
import sys, json
d = json.load(sys.stdin)
if d.get("error") in (None, "None", ""):
    print("%s p.%s/%s image=%s" % (d.get("type"), d.get("page"),
                                   d.get("total_pages"), bool(d.get("image_base64"))))
else:
    print("FAILED: %s" % d.get("error"))
PY
say "pdf viewer" "$(curl -s --max-time 90 "${AUTH[@]}" \
  "$BASE/api/docs/CEC00381196_PART1.pdf/content?anchor=page_5" \
  | python3 -c "$PY_VIEWER" 2>/dev/null || echo ERROR)"

# ── retrieval: the check nothing else can stand in for ──────────────────
CID=$(curl -s --max-time 60 -X POST "$BASE/api/conversations" "${AUTH[@]}" \
  -H 'Content-Type: application/json' -d '{"title":"instance verification"}' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("id") or d.get("conversation_id") or "")' 2>/dev/null)

if [ -n "$CID" ]; then
  body=$(python3 -c 'import json,sys;print(json.dumps({
    "message":"What caused the delay to construction of the depot?",
    "conversation_id":sys.argv[1],"request_id":"verify"}))' "$CID")
  read -r -d '' PY_CHAT <<'PY' || true
import sys, json
d = json.load(sys.stdin)
n = len(d.get("citations") or [])
warn = "" if n else "   <-- NO CITATIONS: check qdrant_storage/"
print("%d citations, route=%s%s" % (n, d.get("route"), warn))
PY
  say "chat (vectors present?)" "$(curl -s --max-time 300 -X POST "$BASE/api/chat" "${AUTH[@]}" \
    -H 'Content-Type: application/json' -d "$body" \
    | python3 -c "$PY_CHAT" 2>/dev/null || echo ERROR)"
else
  say "chat (vectors present?)" "SKIPPED — could not create a conversation"
fi

echo
echo "Expected on a healthy instance:"
echo "  documents 7404 · events 27676 · chronologies 6 · conversations 106+"
echo "  pdf viewer 'pdf p.5/32 image=True' · chat with citations > 0"
