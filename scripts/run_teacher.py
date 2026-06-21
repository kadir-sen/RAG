"""Run the periodic Teacher-LLM pass (KOL C).

Reads the accumulated learning substrates (event_timeline + interaction_log +
clusters) and distils stronger structure the live system reads for free:
causal event chains, a scope curriculum from weak answers, and cluster summaries.

Off the query path; cost is cluster/batch-sized (typically ~$1-3) and seldom.
Needs the Gemini LLM (run on the server). Safe to re-run — outputs are additive.

Run:
    PYTHONPATH=. python scripts/run_teacher.py
    sudo docker exec mvp-api python scripts/run_teacher.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.teacher import get_teacher
    stats = get_teacher().run()
    print(f"Teacher pass complete: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
