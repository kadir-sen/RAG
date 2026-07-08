"""Backfill the Named Entity Registry from existing corpora.

Sources, per corpus:
  * chunk_store text — deterministic proper-noun n-gram extraction (works for
    the edinburgh corpus, which has no notices/enrichment). A name enters the
    registry only if it appears in >= --min-chunks DISTINCT chunks (noise gate).
  * data/notices/*.json — sender/recipient/cc/subject (demo corpus only).

Corpus membership: "edinburgh" = the chunk-store file_name allow-list
(document_rag.edinburgh_filenames()); everything else in the chunk store is
treated as "demo" for backfill purposes.

Alias folding: after extraction, names within a corpus are fuzzy-clustered —
token_set_ratio >= --alias-cutoff makes the lower-count name an alias of the
higher-count canonical (e.g. "Mott Macdonald" → "Mott MacDonald").

Idempotent: stable entity_id = sha256(corpus|canonical_lower); re-runs merge.

Run:
    PYTHONPATH=. python scripts/build_entity_registry.py --corpus all --dry-run
    PYTHONPATH=. python scripts/build_entity_registry.py --corpus edinburgh
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def extract_corpus_names(corpus: str, min_chunks: int, batch: int = 5000):
    """Stream chunk_store text and count proper-noun n-grams per corpus.

    Returns ({name_lower: canonical_name}, {name_lower: chunk_count},
             {name_lower: set(doc_ids capped)}).
    """
    from src.chunk_store import get_chunk_store
    from src.document_rag import edinburgh_filenames
    from src.trust_guard import _capitalized_ngrams, _ENTITY_STOPWORDS

    con = get_chunk_store().connection()
    edin = edinburgh_filenames() or set()

    canonical: dict[str, str] = {}
    counts: dict[str, int] = defaultdict(int)
    docs: dict[str, set] = defaultdict(set)

    offset = 0
    total_chunks = 0
    while True:
        rows = con.execute(
            "SELECT chunk_id, doc_id, file_name, text FROM chunks "
            "ORDER BY chunk_id LIMIT ? OFFSET ?", [batch, offset],
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        for chunk_id, doc_id, file_name, text in rows:
            row_corpus = "edinburgh" if (file_name in edin and edin) else "demo"
            # When both corpora share the chunk store, edinburgh_filenames()
            # covers everything — fall back to treating all rows as the
            # requested corpus in that degenerate case is handled by caller.
            if corpus != "all" and row_corpus != corpus:
                continue
            total_chunks += 1
            seen_in_chunk = set()
            for ngram in _capitalized_ngrams(text or ""):
                words = ngram.split()
                while words and words[0].lower() in _ENTITY_STOPWORDS:
                    words = words[1:]
                if len(words) < 2:
                    continue
                name = " ".join(words)
                low = name.lower()
                if low in seen_in_chunk:
                    continue
                seen_in_chunk.add(low)
                key = f"{row_corpus}|{low}"
                counts[key] += 1
                canonical.setdefault(key, name)
                if len(docs[key]) < 20 and doc_id:
                    docs[key].add(doc_id)
    print(f"  scanned {total_chunks} chunks, {len(counts)} raw names")
    kept = {k for k, c in counts.items() if c >= min_chunks}
    return ({k: canonical[k] for k in kept},
            {k: counts[k] for k in kept},
            {k: docs[k] for k in kept})


def fold_aliases(names: dict, counts: dict, cutoff: int):
    """Cluster near-duplicate names: lower-count → alias of higher-count.

    Returns {canonical_key: [alias_names]} and the set of alias keys to drop.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        print("  rapidfuzz unavailable — skipping alias folding")
        return {}, set()

    by_corpus: dict[str, list] = defaultdict(list)
    for key in names:
        by_corpus[key.split("|", 1)[0]].append(key)

    aliases: dict[str, list] = defaultdict(list)
    dropped: set = set()
    for corpus, keys in by_corpus.items():
        ranked = sorted(keys, key=lambda k: -counts[k])
        for i, hi in enumerate(ranked):
            if hi in dropped:
                continue
            hi_low = hi.split("|", 1)[1]
            for lo in ranked[i + 1:]:
                if lo in dropped:
                    continue
                lo_low = lo.split("|", 1)[1]
                if fuzz.token_set_ratio(hi_low, lo_low) >= cutoff:
                    aliases[hi].append(names[lo])
                    dropped.add(lo)
    return aliases, dropped


def ingest_notices(registry, ts: str, dry_run: bool) -> int:
    """Fold demo-corpus notice metadata (sender/recipient/cc/subject) in."""
    try:
        from src.notice_extractor import get_notice_extractor
        extractor = get_notice_extractor()
    except Exception as e:
        print(f"  notices unavailable: {e}")
        return 0
    n, bad = 0, 0
    for doc_id in extractor.list_notices():
        try:
            notice = extractor.load_notice(doc_id)
            if notice is None:
                continue
            d = notice if isinstance(notice, dict) else notice.__dict__
            if dry_run:
                n += 1
                continue
            registry.ingest_from_notice(
                doc_id=d.get("doc_id") or doc_id,
                file_name=d.get("file_name") or "",
                notice_summary={
                    "sender": d.get("sender"),
                    "recipient": d.get("recipient"),
                    "cc_list": d.get("cc_list") or [],
                    "subject": d.get("subject"),
                },
                corpus="demo",
                ts=ts,
            )
            n += 1
        except Exception:
            bad += 1  # malformed notice JSON — skip, keep going
    if bad:
        print(f"  {bad} malformed notice file(s) skipped")
    return n


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=["edinburgh", "demo", "all"], default="all")
    parser.add_argument("--min-chunks", type=int, default=2,
                        help="name must appear in >= N distinct chunks")
    parser.add_argument("--alias-cutoff", type=int, default=90,
                        help="token_set_ratio >= N folds a name into an alias")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from src.entity_registry import get_entity_registry

    ts = datetime.now().isoformat()
    registry = get_entity_registry()

    print(f"[1/3] Extracting proper nouns from chunk store (corpus={args.corpus})...")
    names, counts, docs = extract_corpus_names(args.corpus, args.min_chunks)
    print(f"  {len(names)} names past the >= {args.min_chunks}-chunk gate")

    print(f"[2/3] Folding aliases (cutoff={args.alias_cutoff})...")
    aliases, dropped = fold_aliases(names, counts, args.alias_cutoff)
    print(f"  {len(dropped)} names folded into {len(aliases)} canonicals")

    print("[3/3] Writing registry...")
    written = 0
    for key, name in sorted(names.items(), key=lambda kv: -counts[kv[0]]):
        if key in dropped:
            continue
        corpus, _ = key.split("|", 1)
        if args.dry_run:
            written += 1
            continue
        # Confidence scales with corpus frequency (cap 0.9 — text-derived).
        conf = min(0.9, 0.5 + 0.05 * counts[key])
        registry.bulk_upsert(name, "other", corpus,
                             doc_ids=sorted(docs.get(key) or []),
                             aliases=aliases.get(key) or [],
                             confidence=conf, ts=ts)
        written += 1
    print(f"  {written} canonical entities {'(dry run)' if args.dry_run else 'written'}")

    if args.corpus in ("demo", "all"):
        print("[+] Folding demo notices...")
        n = ingest_notices(registry, ts, args.dry_run)
        print(f"  {n} notices processed")

    for corpus in ("demo", "edinburgh"):
        print(f"  registry[{corpus}] = {registry.count(corpus)} entities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
