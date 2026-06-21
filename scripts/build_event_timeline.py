"""Build the event-timeline store from per-document enrichment outputs.

Reads storage/enrichment/{doc_id}.json (produced by the unified ingest enrichment
in file_router._enrich_document_llm) and loads each document's structured events
(delay / disruption / excuse / decision / milestone) into the event_timeline
DuckDB store, so chronological/aggregative questions are answered deterministically.

Idempotent (stable event ids). Run after enrichment has populated storage/enrichment/
(that step needs the Gemini LLM, so it typically runs on the server).

Run:
    PYTHONPATH=. python scripts/build_event_timeline.py [--project "Edinburgh Tram Inquiry"]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enrichment-dir", default=str(ROOT / "storage" / "enrichment"))
    parser.add_argument("--project", default="")
    args = parser.parse_args()

    from src.event_timeline import get_event_timeline

    enrich_dir = Path(args.enrichment_dir)
    if not enrich_dir.exists():
        print(f"No enrichment dir at {enrich_dir} — run ingest enrichment first "
              f"(needs Gemini; typically on the server).")
        return 1

    store = get_event_timeline()
    files = sorted(enrich_dir.glob("*.json"))
    print(f"Reading {len(files)} enrichment files…")

    total = 0
    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = []
        for ev in data.get("events") or []:
            if not isinstance(ev, dict):
                continue
            rows.append({
                "doc_id": data.get("doc_id", fp.stem),
                "file_name": data.get("file_name", ""),
                "project": args.project,
                "date": ev.get("date", ""),
                "event_type": ev.get("type", ""),
                "actor": ev.get("actor", ""),
                "reason": ev.get("reason", "") or ev.get("description", ""),
                "severity": ev.get("severity", ""),
                "status": ev.get("status", ""),
                "description": ev.get("description", ""),
                "source": "enrichment",
            })
        total += store.add_events(rows)

    print(f"\nEvent timeline built: {store.count()} events total (+{total} new).")
    print("By type:", store.type_counts())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
