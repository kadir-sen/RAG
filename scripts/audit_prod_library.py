"""Sweep the production library: for every document the backend exposes,
verify that the /docs/{doc_id}/content endpoint resolves it cleanly.

Run:
    python scripts/audit_prod_library.py
    python scripts/audit_prod_library.py --base-url http://localhost:8000
    python scripts/audit_prod_library.py --output /tmp/prod_doc_audit.json

The report has one row per registry document with status (OK / BROKEN /
DATA_ONLY) and any error text returned by the viewer. Combine with
``scripts/audit_pinecone.py`` for vector-side coverage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_BASE = "http://18.185.38.217"


def _http_get(url: str, timeout: int = 15) -> tuple[int, Any]:
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            return e.code, json.loads(body) if body.startswith("{") else body
        except Exception:
            return e.code, str(e)
    except (URLError, TimeoutError, ConnectionError) as e:
        return 0, f"{type(e).__name__}: {e}"


def _classify(doc: Dict[str, Any], content_status: int, content: Any) -> str:
    if content_status == 200 and isinstance(content, dict) and not content.get("error"):
        return "OK"
    ext = (doc.get("extension") or "").lower()
    file_type = (doc.get("file_type") or "").lower()
    if ext in (".xlsx", ".xls", ".csv") or file_type == "data":
        return "DATA_ONLY" if content_status == 200 else "BROKEN"
    return "BROKEN"


def _viewer_meta(content: Any) -> tuple[str, str]:
    if not isinstance(content, dict):
        return "", str(content)[:200]
    return content.get("type", "") or "", content.get("error", "") or ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE,
        help=f"Server base URL (default: {DEFAULT_BASE})",
    )
    parser.add_argument("--output", default="prod_doc_audit.json")
    parser.add_argument(
        "--anchor", default="",
        help="Anchor to request for every doc (e.g. 'page_1')",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Cap the number of documents (0 = all)",
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    library_url = f"{base}/api/library"
    print(f"Fetching {library_url} …")
    status, library = _http_get(library_url)
    if status != 200 or not isinstance(library, list):
        print(f"  failed: {status} — {str(library)[:200]}", file=sys.stderr)
        return 2
    print(f"  library has {len(library)} document(s)")

    if args.limit:
        library = library[: args.limit]

    rows: List[Dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for i, doc in enumerate(library, 1):
        doc_id = doc.get("doc_id") or ""
        file_name = doc.get("file_name") or ""
        url = f"{base}/api/docs/{quote(doc_id, safe='')}/content"
        if args.anchor:
            url += f"?anchor={quote(args.anchor)}"
        c_status, c_body = _http_get(url)
        verdict = _classify(doc, c_status, c_body)
        viewer_type, viewer_error = _viewer_meta(c_body)
        rows.append({
            "doc_id": doc_id,
            "file_name": file_name,
            "extension": doc.get("extension"),
            "file_type": doc.get("file_type"),
            "content_status": c_status,
            "viewer_type": viewer_type,
            "viewer_error": viewer_error,
            "verdict": verdict,
        })
        counts[verdict] += 1
        if i % 25 == 0:
            print(f"  scanned {i}/{len(library)}")

    Path(args.output).write_text(json.dumps({
        "base_url": base,
        "total_documents": len(library),
        "counts": dict(counts),
        "documents": rows,
    }, indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"Base:           {base}")
    print(f"Library size:   {len(library)}")
    for verdict in ("OK", "DATA_ONLY", "BROKEN"):
        print(f"  {verdict:<10} {counts.get(verdict, 0)}")
    print("=" * 60)
    broken = [r for r in rows if r["verdict"] == "BROKEN"]
    if broken:
        print("\nBroken documents (first 20):")
        for r in broken[:20]:
            err = r["viewer_error"] or f"status={r['content_status']}"
            print(f"  - {r['file_name']} [{r['doc_id']}] — {err}")
    print(f"\nFull report written to: {args.output}")
    return 0 if counts.get("BROKEN", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
