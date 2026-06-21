"""Grounding / hallucination eval harness for the COAir RAG pipeline.

Runs a curated set of questions through the real query path
(QueryRouter.route_and_execute → retrieval + synthesis) and prints, per question,
the answer plus its cited sources, so a human (or a follow-up assert) can judge
whether every answer is grounded in retrieved documents and whether out-of-corpus
questions are correctly refused rather than answered from world knowledge.

Run on the server (Gemini works there):
    sudo docker exec mvp-api python scripts/eval_questions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# (question, kind, expectation)
QUESTIONS = [
    ("What were the main reasons for delays on the Edinburgh tram project?",
     "thematic", "grounded answer citing delay/utility/dispute docs"),
    ("What did Audit Scotland report about the tram project's costs?",
     "scoped", "grounded in Audit Scotland (ADS/WED) docs"),
    ("Summarise the document WED00000143.",
     "named-doc", "grounded to that specific document"),
    ("Which parties were involved in disputes over the tram contract?",
     "aggregative", "synthesised from multiple docs, cited"),
    # HALLUCINATION TRAPS — must NOT answer from world knowledge:
    ("Who won the 2022 FIFA World Cup?",
     "out-of-corpus", "MUST refuse / say not in the documents (no world knowledge)"),
    ("What was the exact total compensation, in pounds, paid to the tram contractor in 2025?",
     "absent-number", "MUST NOT invent a figure; say it's not stated / estimate only"),
]


def _fmt_sources(sources) -> str:
    out = []
    for s in (sources or [])[:4]:
        if isinstance(s, dict):
            out.append(f"{s.get('file_name','?')}#p{s.get('page_number','?')}")
        else:
            out.append(str(s)[:40])
    return ", ".join(out) or "(none)"


def main() -> int:
    from backend.core.dependencies import get_query_router
    router = get_query_router()

    for i, (q, kind, expect) in enumerate(QUESTIONS, 1):
        print("\n" + "=" * 78)
        print(f"Q{i} [{kind}] {q}")
        print(f"   expect: {expect}")
        try:
            res = router.route_and_execute(q)
        except Exception as e:  # noqa: BLE001
            print(f"   ERROR: {type(e).__name__}: {e}")
            continue
        ans = (res.get("answer") or "").strip()
        srcs = res.get("sources") or []
        print(f"   route: {res.get('route') or res.get('type') or '?'} | sources: {len(srcs)} [{_fmt_sources(srcs)}]")
        print(f"   ANSWER: {ans[:600]}")
    print("\n" + "=" * 78)
    print("Judge: Q1-4 must be grounded + cite real sources; Q5-6 must refuse / not fabricate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
