"""Download the NON-PDF (Excel) evidence from the Edinburgh Tram Inquiry archive.

Companion to ``download_edinburgh_tram.py`` (which harvested the ~7k PDFs). The
official "Published Evidence Documents Record" lists 122 documents whose file
format is XLS/XLSX (68 Excel-only + 54 published as both Excel *and* PDF). The
PDF harvest skipped them because its url regex only matched ``.pdf``.

Two resolution strategies (cheap first, crawl only if needed):

  A. Extension-swap (free, no crawl) — for the 54 dual-format refs we already
     have the ``.pdf`` url in ``url_map.json``; the Excel sits at the SAME
     ``/uploads/YYYY/MM/<REF>.<ext>`` path. We just swap the extension.
  B. FacetWP harvest (crawl) — the 68 Excel-only refs are absent from
     ``url_map.json``; we re-page the FacetWP grid with an extended regex that
     captures ``.xls/.xlsx`` urls and key them by reference (url stem + any
     reference token in the row title). Cached to ``file_url_map.json``.

Reuses the WAF-clearing session / HTTP helpers from ``download_edinburgh_tram``
so the proven PDF pipeline is untouched.

Run:
    PYTHONPATH=. python scripts/download_edinburgh_excels.py --probe        # test strategy A on a few dual refs, report coverage
    PYTHONPATH=. python scripts/download_edinburgh_excels.py --resolve-only # resolve every target url (A then B), write manifest, download nothing
    PYTHONPATH=. python scripts/download_edinburgh_excels.py                 # full: resolve + download (resumable)
    PYTHONPATH=. python scripts/download_edinburgh_excels.py --limit 10      # small end-to-end test
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse the battle-tested WAF session + HTTP + FacetWP plumbing.
from scripts.download_edinburgh_tram import (  # noqa: E402
    BASE,
    REFRESH_API,
    REF_RE,
    TITLE_RE,
    WRAPPER_SPLIT,
    _refresh_payload,
    get_bytes,
    make_session,
)

OUT_DIR = ROOT / "data" / "edinburgh_tram"
EXCEL_DIR = OUT_DIR / "excels"
TARGETS_JSON = OUT_DIR / "excel_targets.json"          # written by the manifest-filter step
URL_MAP_JSON = OUT_DIR / "url_map.json"                # existing pdf url map (for strategy A)
FILE_URL_MAP_JSON = OUT_DIR / "file_url_map.json"      # harvested non-pdf url map (strategy B cache)

# Capture any uploads url with a document-ish extension (pdf/xls/xlsx/txt/csv/doc/docx).
UPLOADS_FILE_RE = re.compile(
    r"/wp-content/uploads/(\d{4}/\d{2}/[^\"'?#<> ]+?\.(?:pdf|xlsx|xls|txt|csv|docx|doc))",
    re.IGNORECASE,
)


def _ext_for_format(fmt: str) -> str:
    """'XLSX,PDF' -> 'xlsx', 'XLS,PDF' -> 'xls'."""
    f = fmt.upper()
    return "xlsx" if "XLSX" in f else "xls"


def load_targets() -> list[dict[str, str]]:
    if not TARGETS_JSON.exists():
        print(f"ERROR: {TARGETS_JSON} missing — run the manifest-filter step first.", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(TARGETS_JSON.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Strategy A — extension-swap from the known pdf url (dual-format refs).
# --------------------------------------------------------------------------- #
def swap_ext(pdf_url: str, ext: str) -> str:
    return re.sub(r"\.pdf$", f".{ext}", pdf_url, flags=re.IGNORECASE)


def head_ok(session, url: str) -> tuple[bool, int]:
    """Confirm a url exists/serves content (GET — the WAF dislikes HEAD)."""
    status, body = get_bytes(session, url, retries=2, timeout=45)
    return (status == 200 and len(body) > 0), status


# --------------------------------------------------------------------------- #
# Strategy B — harvest non-pdf urls from the FacetWP grid.
# --------------------------------------------------------------------------- #
def _parse_wrapper_files(template_html: str) -> list[dict[str, Any]]:
    """Each docWrapper -> {title, refs_in_title, files: [{ext, url, stem}]}."""
    rows: list[dict[str, Any]] = []
    for chunk in WRAPPER_SPLIT.split(template_html)[1:]:
        title_m = TITLE_RE.search(chunk)
        title = html_lib.unescape(title_m.group(1).strip()) if title_m else ""
        refs_in_title = REF_RE.findall(title.upper())
        files = []
        for m in UPLOADS_FILE_RE.finditer(chunk):
            rel = m.group(1)  # YYYY/MM/stem.ext
            fname = rel.rsplit("/", 1)[-1]
            stem, _, ext = fname.rpartition(".")
            files.append({"ext": ext.lower(), "url": f"{BASE}/wp-content/uploads/{rel}",
                          "stem": stem.upper()})
        if files:
            rows.append({"title": title, "refs_in_title": refs_in_title, "files": files})
    return rows


def harvest_file_urls(session, max_pages: int, throttle: float) -> dict[str, dict[str, str]]:
    """Page FacetWP. Returns {reference: {ext: url}} for non-pdf-resolvable refs.

    A file is keyed under (a) its url stem and (b) every reference token found in
    its row title, so Excel files uploaded under a descriptive name still attach
    to the right reference.
    """
    out: dict[str, dict[str, str]] = {}
    total_pages, page, nonpdf = max_pages, 1, 0
    while page <= total_pages:
        try:
            r = session.post(REFRESH_API, json=_refresh_payload(page), timeout=60)
            data = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"  page {page}: request failed ({type(e).__name__}: {e}) — retry once", file=sys.stderr)
            time.sleep(2.0)
            try:
                data = session.post(REFRESH_API, json=_refresh_payload(page), timeout=60).json()
            except Exception as e2:  # noqa: BLE001
                print(f"  page {page}: failed again ({e2}); stopping", file=sys.stderr)
                break
        if isinstance(data, dict):
            pager = data.get("settings", {}).get("pager", {}) if isinstance(data.get("settings"), dict) else {}
            if pager.get("total_pages"):
                total_pages = min(max_pages, int(pager["total_pages"]))
            for w in _parse_wrapper_files(data.get("template", "")):
                keys = set(w["refs_in_title"])
                for f in w["files"]:
                    keys.add(f["stem"])
                    if f["ext"] != "pdf":
                        nonpdf += 1
                for ref in keys:
                    if not REF_RE.fullmatch(ref):
                        continue
                    slot = out.setdefault(ref, {})
                    for f in w["files"]:
                        slot.setdefault(f["ext"], f["url"])
            if page == 1 or page % 50 == 0 or page == total_pages:
                print(f"  page {page}/{total_pages}: refs={len(out)} non-pdf-files={nonpdf}")
        page += 1
        time.sleep(throttle)
    return out


def load_or_harvest(session, max_pages: int, throttle: float, refresh: bool) -> dict[str, dict[str, str]]:
    if FILE_URL_MAP_JSON.exists() and not refresh:
        m = json.loads(FILE_URL_MAP_JSON.read_text(encoding="utf-8"))
        print(f"  loaded cached file url map: {len(m)} refs ({FILE_URL_MAP_JSON.name})")
        return m
    print("  harvesting FacetWP grid for non-pdf urls (this re-pages the full grid)…")
    m = harvest_file_urls(session, max_pages, throttle)
    FILE_URL_MAP_JSON.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ harvested {len(m)} refs -> {FILE_URL_MAP_JSON.name}")
    return m


# --------------------------------------------------------------------------- #
# Resolution: target ref -> excel url (strategy A first, then B).
# --------------------------------------------------------------------------- #
def resolve_urls(session, targets: list[dict[str, str]], pdf_map: dict[str, dict[str, str]],
                 do_harvest: bool, max_pages: int, throttle: float,
                 refresh: bool) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    file_map: dict[str, dict[str, str]] = {}
    resolved: list[dict[str, Any]] = []

    # Strategy A: extension-swap for refs whose pdf url we already know. The
    # probe confirmed the Excel sits at the same path as its sibling pdf, so we
    # construct the url without a verifying GET — download() records any miss.
    a_ok = 0
    for t in targets:
        ref, ext = t["reference"], _ext_for_format(t["format"])
        url, src = "", ""
        if ref in pdf_map and pdf_map[ref].get("url", "").lower().endswith(".pdf"):
            url, src = swap_ext(pdf_map[ref]["url"], ext), "ext-swap"
            a_ok += 1
        resolved.append({**t, "ext": ext, "url": url, "source": src})
    print(f"  strategy A (ext-swap): resolved {a_ok}/{len(targets)}")

    unresolved = [r for r in resolved if not r["url"]]
    if unresolved and do_harvest:
        file_map = load_or_harvest(session, max_pages, throttle, refresh)
        b_ok = 0
        for r in resolved:
            if r["url"]:
                continue
            slot = file_map.get(r["reference"], {})
            cand = slot.get(r["ext"]) or slot.get("xlsx") or slot.get("xls")
            if cand:
                r["url"], r["source"] = cand, "harvest"
                b_ok += 1
        print(f"  strategy B (harvest): resolved {b_ok}/{len(unresolved)} of the remainder")
    elif unresolved:
        print(f"  {len(unresolved)} unresolved (harvest skipped — pass without --probe to crawl)")

    return resolved, file_map


# --------------------------------------------------------------------------- #
def download(session, resolved: list[dict[str, Any]], throttle: float, limit: int) -> None:
    EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    rows = [r for r in resolved if r["url"]]
    if limit:
        rows = rows[:limit]
    counts: dict[str, int] = {}
    log: list[dict[str, Any]] = []
    for i, r in enumerate(rows, 1):
        dest = EXCEL_DIR / f"{r['reference']}.{r['ext']}"
        if dest.exists() and dest.stat().st_size > 0:
            label, status, nbytes = "skipped", 200, dest.stat().st_size
        else:
            status, body = get_bytes(session, r["url"])
            if status == 200 and body:
                dest.write_bytes(body)
                label, nbytes = "downloaded", len(body)
            else:
                label, nbytes = "failed", 0
            time.sleep(throttle)
        counts[label] = counts.get(label, 0) + 1
        log.append({"reference": r["reference"], "ext": r["ext"], "url": r["url"],
                    "http_status": status, "bytes": nbytes, "status": label})
        if i % 20 == 0 or label == "failed":
            print(f"  [{i}/{len(rows)}] {counts.get('downloaded',0)} dl, "
                  f"{counts.get('skipped',0)} skip, {counts.get('failed',0)} fail")
    with (OUT_DIR / "excel_download_log.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["reference", "ext", "url", "http_status", "bytes", "status"])
        w.writeheader(); w.writerows(log)
    print(f"\n  download: {counts}")


def write_manifest(resolved: list[dict[str, Any]]) -> None:
    cols = ["reference", "category", "format", "ext", "source", "url", "description"]
    with (OUT_DIR / "excel_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in resolved:
            w.writerow({c: r.get(c, "") for c in cols})
    miss = [r for r in resolved if not r["url"]]
    with (OUT_DIR / "excel_missing.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["reference", "format", "description"])
        w.writeheader()
        for r in miss:
            w.writerow({k: r.get(k, "") for k in ("reference", "format", "description")})
    print(f"  ✓ excel_manifest.csv ({len(resolved)}), excel_missing.csv ({len(miss)})")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--probe", action="store_true",
                   help="Test strategy A on the dual-format refs only; no harvest, no download.")
    p.add_argument("--resolve-only", action="store_true", help="Resolve urls + manifest; download nothing.")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--throttle", type=float, default=0.4)
    p.add_argument("--max-pages", type=int, default=800)
    p.add_argument("--refresh-harvest", action="store_true", help="Ignore file_url_map.json cache.")
    args = p.parse_args()

    targets = load_targets()
    pdf_map = json.loads(URL_MAP_JSON.read_text(encoding="utf-8")) if URL_MAP_JSON.exists() else {}
    print(f"Targets: {len(targets)} Excel docs · pdf url_map: {len(pdf_map)} refs\n")

    session = make_session()

    if args.probe:
        # Only the dual refs can be probed via ext-swap; sample up to 8.
        dual = [t for t in targets if "PDF" in t["format"].upper() and t["reference"] in pdf_map][:8]
        print(f"Probing strategy A on {len(dual)} dual-format refs:")
        ok = 0
        for t in dual:
            ext = _ext_for_format(t["format"])
            cand = swap_ext(pdf_map[t["reference"]]["url"], ext)
            good, status = head_ok(session, cand)
            ok += good
            print(f"  {'✓' if good else '✗'} {t['reference']}.{ext}  (HTTP {status})  {cand.split('/uploads/')[-1]}")
            time.sleep(args.throttle)
        print(f"\nProbe: {ok}/{len(dual)} dual Excel urls resolve by extension-swap.")
        print("If high → strategy A covers the 54 dual; the 68 Excel-only still need --resolve-only (harvest).")
        return 0

    do_harvest = not args.probe
    resolved, _ = resolve_urls(session, targets, pdf_map, do_harvest,
                               args.max_pages, args.throttle, args.refresh_harvest)
    write_manifest(resolved)
    n_ok = sum(1 for r in resolved if r["url"])
    print(f"\nResolved {n_ok}/{len(resolved)} excel urls "
          f"(A={sum(1 for r in resolved if r['source']=='ext-swap')}, "
          f"B={sum(1 for r in resolved if r['source']=='harvest')})")

    if args.resolve_only:
        return 0
    print("\nDownloading…")
    download(session, resolved, args.throttle, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
