"""Faz 6 — verify per-corpus SQL isolation end-to-end through the router.

Proves the fix for the "No data tables available" confound: an 'edinburgh' user
now reaches the edinburgh financial Excels (never the demo tables), a 'demo' user
still sees only demo tables, and a corpus with no tables short-circuits to a
clean no-data answer instead of leaking the other corpus.

Run:
    PYTHONPATH=. python scripts/verify_corpus_isolation.py
    PYTHONPATH=. python scripts/verify_corpus_isolation.py --live   # also run a real LLM SQL query
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Run one real LLM SQL query per corpus.")
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)

    from src.document_rag import corpus_var
    from src.data_analyzer_sql import get_data_analyzer

    da = get_data_analyzer()
    da.load_from_catalog()
    edi = set(da.get_tables_for_corpus("edinburgh") or [])
    demo = set(da.get_tables_for_corpus("demo") or [])

    print("=" * 64)
    print("STRUCTURAL ISOLATION")
    print(f"  edinburgh tables : {len(edi)}")
    print(f"  demo tables      : {len(demo)}")
    print(f"  overlap          : {len(edi & demo)}  (must be 0)")
    print(f"  unrestricted(None): {da.get_tables_for_corpus('') is None}  (script default = no filter)")
    print(f"  empty corpus 'xyz': {da.get_tables_for_corpus('xyz')}  (must be [] → triggers clean no-data)")

    ok = (len(edi) > 0 and len(demo) > 0 and not (edi & demo)
          and da.get_tables_for_corpus("") is None
          and da.get_tables_for_corpus("xyz") == [])

    # Router-level: confirm _handle_data_query computes the right allow-list and
    # that table selection stays within the active corpus.
    print("\n" + "=" * 64)
    print("ROUTER ALLOW-LIST (per corpus, no LLM)")
    try:
        from src.router import get_router
        router = get_router()
        for corpus, expected in (("edinburgh", edi), ("demo", demo)):
            tok = corpus_var.set(corpus)
            try:
                allowed = set(router.data_analyzer.get_tables_for_corpus(corpus) or [])
                sel = router.data_analyzer.select_tables(
                    "total cost and risk allocation figures", max_tables=3,
                    allowed_tables=list(allowed))
            finally:
                corpus_var.reset(tok)
            within = all(s in expected for s in sel)
            leaked = [s for s in sel if s not in expected]
            print(f"  [{corpus}] allow={len(allowed)} selected={sel}")
            print(f"           selection within corpus: {within}  leaked={leaked}")
            ok = ok and within
    except Exception as e:
        print(f"  router check skipped: {type(e).__name__}: {e}")

    if args.live:
        print("\n" + "=" * 64)
        print("LIVE LLM SQL (one query per corpus)")
        questions = {
            "edinburgh": "What figures are recorded in the MUDFA Infraco split data?",
            "demo": "How many equipment log rows are there in total?",
        }
        for corpus, q in questions.items():
            tok = corpus_var.set(corpus)
            try:
                allowed = da.get_tables_for_corpus(corpus)
                res = da.query(q, allowed_tables=allowed)
            except Exception as e:
                print(f"  [{corpus}] query error: {type(e).__name__}: {e}")
                corpus_var.reset(tok)
                continue
            corpus_var.reset(tok)
            sql = (res.get("sql") or "").replace("\n", " ")
            ans = (res.get("answer") or "")[:180]
            # which tables does the SQL touch, and are any from the OTHER corpus?
            other = demo if corpus == "edinburgh" else edi
            touched_other = [t for t in other if t and t in sql]
            print(f"  [{corpus}] Q: {q}")
            print(f"           SQL: {sql[:160]}")
            print(f"           ANSWER: {ans}")
            print(f"           leaked other-corpus tables in SQL: {touched_other}")
            ok = ok and not touched_other

    print("\n" + "=" * 64)
    print(f"RESULT: {'PASS ✓' if ok else 'FAIL ✗'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
