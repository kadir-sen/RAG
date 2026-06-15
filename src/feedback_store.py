"""
Feedback store — the entry point of the data flywheel (Karpathy data engine).

Captures user 👍/👎 (plus optional note/correction) on assistant answers as an
append-only JSONL log. The golden-set builder and flywheel jobs consume this to
improve retrieval keywords, routing few-shot, and jargon over time.

One record per feedback event: who, when, the question, the route taken, the
sources/SQL the answer relied on, the vote, and any correction text.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import STORAGE_DIR
from .logger import logger

FEEDBACK_DIR = STORAGE_DIR / "feedback"
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.jsonl"

_lock = threading.Lock()


def record_feedback(record: Dict) -> Dict:
    """Append one feedback event (with a server timestamp) and sync to GCS."""
    record = dict(record)
    record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with _lock:
        FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        from .gcs_storage import sync_feedback_to_gcs
        sync_feedback_to_gcs()
    except Exception:
        pass
    logger.info(
        f"[Feedback] {record.get('vote')} on msg={record.get('message_id', '?')[:8]} "
        f"route={record.get('route')}"
    )
    return record


def load_feedback(limit: Optional[int] = None) -> List[Dict]:
    """Load feedback events (most recent first when limited)."""
    try:
        from .gcs_storage import sync_feedback_from_gcs
        sync_feedback_from_gcs()
    except Exception:
        pass
    if not FEEDBACK_FILE.exists():
        return []
    rows: List[Dict] = []
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit:
        return rows[-limit:]
    return rows


def summary() -> Dict:
    """Aggregate feedback counts overall and per route."""
    rows = load_feedback()
    up = sum(1 for r in rows if r.get("vote") == "up")
    down = sum(1 for r in rows if r.get("vote") == "down")
    by_route: Dict[str, Dict[str, int]] = {}
    for r in rows:
        route = r.get("route") or "unknown"
        d = by_route.setdefault(route, {"up": 0, "down": 0})
        if r.get("vote") in ("up", "down"):
            d[r["vote"]] += 1
    return {"total": len(rows), "up": up, "down": down, "by_route": by_route}
