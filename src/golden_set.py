"""
Golden set builder — turns captured feedback into a labeled evaluation set.

Part of the data flywheel: 👍 answers become positive (question → expected route)
examples; 👎 answers become review items (with any correction). The routing
golden test and the flywheel both read this. Append-only, deduped by question+route.
"""
import json
import threading
from pathlib import Path
from typing import Dict, List

from .config import STORAGE_DIR
from .logger import logger

GOLDEN_DIR = STORAGE_DIR / "golden"
GOLDEN_FILE = GOLDEN_DIR / "golden.jsonl"

_lock = threading.Lock()


def build_golden_set() -> Dict[str, int]:
    """(Re)build the golden set from feedback. Returns counts."""
    from .feedback_store import load_feedback

    rows: List[Dict] = []
    seen = set()
    positives = reviews = 0
    for fb in load_feedback():
        q = (fb.get("question") or "").strip()
        route = fb.get("route")
        if not q:
            continue
        key = (q.lower(), route, fb.get("vote"))
        if key in seen:
            continue
        seen.add(key)
        if fb.get("vote") == "up":
            rows.append({"question": q, "expected_route": route, "label": "good",
                         "source_files": fb.get("source_files", [])})
            positives += 1
        elif fb.get("vote") == "down":
            rows.append({"question": q, "route_taken": route, "label": "needs_review",
                         "correction": fb.get("correction")})
            reviews += 1

    with _lock:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        with open(GOLDEN_FILE, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"[Golden] built {len(rows)} rows ({positives} good, {reviews} review)")
    return {"total": len(rows), "good": positives, "needs_review": reviews}


def load_golden_set() -> List[Dict]:
    if not GOLDEN_FILE.exists():
        return []
    out = []
    with open(GOLDEN_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out
