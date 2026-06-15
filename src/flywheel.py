"""
Data flywheel — periodically turns captured feedback into system improvements.

Karpathy data-engine loop, applied without model fine-tuning:
  1. Routing few-shot: 👍 answers become (question → route) examples the LLM
     router sees, reinforcing correct routing over time.
  2. Jargon growth: corrections phrased "X means Y" / "X = Y" become custom jargon.
  3. Document-keyword strengthening: 👍 answers push the question's salient terms
     into their source documents' llm_topics, feeding the lexical retrieval lane.

Every change is additive, deduped, logged, and reversible (new records, never
destructive overwrites). Trigger manually (admin endpoint) or on a schedule.
"""
import json
import re
import threading
from pathlib import Path
from typing import Dict, List

from .config import STORAGE_DIR
from .logger import logger

LEARNED_DIR = STORAGE_DIR / "learned"
ROUTING_EXAMPLES_FILE = LEARNED_DIR / "routing_examples.jsonl"

_lock = threading.Lock()

# Generic words that should never become jargon or doc keywords.
_STOPWORDS = {
    "the", "and", "for", "what", "which", "show", "list", "how", "many", "does",
    "are", "was", "were", "from", "with", "this", "that", "about", "give", "tell",
    "ne", "nedir", "kaç", "hangi", "için", "ve", "bir", "göster",
}


def get_learned_routing_examples(limit: int = 8) -> List[Dict]:
    """Return recent learned (question → route) examples for the router few-shot."""
    if not ROUTING_EXAMPLES_FILE.exists():
        return []
    rows = []
    with open(ROUTING_EXAMPLES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-limit:]


def _existing_routing_keys() -> set:
    return {
        (r.get("question", "").lower(), r.get("route"))
        for r in get_learned_routing_examples(limit=10_000)
    }


def apply_flywheel() -> Dict[str, int]:
    """Consume feedback and apply additive improvements. Returns a summary."""
    from .feedback_store import load_feedback

    feedback = load_feedback()
    learned_routes = _learn_routing(feedback)
    learned_jargon = _learn_jargon(feedback)
    boosted_docs = _strengthen_doc_keywords(feedback)

    summary = {
        "feedback_seen": len(feedback),
        "routing_examples_added": learned_routes,
        "jargon_terms_added": learned_jargon,
        "docs_keyword_boosted": boosted_docs,
    }
    logger.info(f"[Flywheel] applied: {summary}")
    return summary


def _learn_routing(feedback: List[Dict]) -> int:
    """Append (question → route) examples from 👍 answers (deduped)."""
    existing = _existing_routing_keys()
    added = 0
    with _lock:
        LEARNED_DIR.mkdir(parents=True, exist_ok=True)
        with open(ROUTING_EXAMPLES_FILE, "a", encoding="utf-8") as f:
            for fb in feedback:
                if fb.get("vote") != "up":
                    continue
                q = (fb.get("question") or "").strip()
                route = fb.get("route")
                if not q or not route:
                    continue
                key = (q.lower(), route)
                if key in existing:
                    continue
                existing.add(key)
                f.write(json.dumps({"question": q, "route": route}, ensure_ascii=False) + "\n")
                added += 1
    return added


def _learn_jargon(feedback: List[Dict]) -> int:
    """Parse corrections like 'EOT means Extension of Time' / 'BOQ = Bill of Quantities'."""
    from .jargon_manager import get_jargon_manager
    jm = get_jargon_manager()
    added = 0
    pattern = re.compile(
        r"\b([A-Z]{2,8})\b\s*(?:=|means|stands for|:|demek|açılımı)\s*(.+)",
        re.IGNORECASE,
    )
    for fb in feedback:
        corr = (fb.get("correction") or "").strip()
        if not corr:
            continue
        mobj = pattern.search(corr)
        if not mobj:
            continue
        abbr = mobj.group(1).strip().upper()
        full = mobj.group(2).strip().rstrip(".").strip()
        if not abbr or len(full) < 3:
            continue
        try:
            jm.add_custom_term(abbr, full)
            added += 1
            logger.info(f"[Flywheel] learned jargon: {abbr} → {full}")
        except Exception:
            # Built-in or duplicate — skip silently.
            pass
    return added


def _strengthen_doc_keywords(feedback: List[Dict]) -> int:
    """For 👍 answers, push the question's salient terms into the source docs'
    llm_topics so the lexical lane finds them next time."""
    from .document_registry import get_document_registry
    reg = get_document_registry()
    boosted = 0
    for fb in feedback:
        if fb.get("vote") != "up":
            continue
        files = fb.get("source_files") or []
        terms = _salient_terms(fb.get("question") or "")
        if not files or not terms:
            continue
        for fname in files:
            for rec in reg.search_by_name(fname):
                existing = [t.lower() for t in (getattr(rec, "llm_topics", None) or [])]
                new = [t for t in terms if t.lower() not in existing]
                if not new:
                    continue
                merged = list(getattr(rec, "llm_topics", None) or []) + new
                reg.set_llm_enrichment(rec.doc_id, topics=merged[:20])
                boosted += 1
    return boosted


def _salient_terms(question: str, max_terms: int = 5) -> List[str]:
    toks = [t for t in re.split(r"[^a-zA-Z0-9]+", (question or "").lower()) if t]
    out = []
    for t in toks:
        if len(t) >= 4 and t not in _STOPWORDS and t not in out:
            out.append(t)
    return out[:max_terms]
