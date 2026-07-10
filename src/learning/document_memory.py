"""Document-selection memory.

Remembers which documents an analyst used for a given analysis type on a given
project, so a later run can offer the same set — but only ON CONFIRMATION.
Unlike schema_memory (global header signatures), document selection is
PROJECT-SCOPED: the key is (corpus/project, analysis_key), because "the notices
for the blockwork delay" means different files on different projects.

Safety: `suggest` only ever returns a previously **approved** selection, and the
caller (resolver) must ask the user before reusing it — never a silent swap.
JSON-backed, best-effort; a memory failure never breaks a workflow.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import STORAGE_DIR

logger = logging.getLogger(__name__)

_STORE = STORAGE_DIR / "learning" / "document_memory.json"
_LOCK = threading.RLock()


def analysis_key(workflow_id: str, topic: str = "") -> str:
    """Stable key for an analysis type + optional topic (e.g. a delay event)."""
    topic_norm = "-".join(re.findall(r"[a-z0-9]+", (topic or "").lower()))
    return f"{workflow_id}:{topic_norm}" if topic_norm else str(workflow_id)


def _scope_key(corpus: str, project_id: Optional[str], akey: str) -> str:
    return f"{project_id or corpus or 'default'}::{akey}"


def _load() -> Dict[str, Any]:
    try:
        if _STORE.exists():
            return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[DocumentMemory] read failed: {e}")
    return {}


def _save(data: Dict[str, Any]) -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    except Exception as e:
        logger.warning(f"[DocumentMemory] save failed: {e}")


def record_selection(akey: str, doc_ids: List[str], corpus: str = "",
                     project_id: Optional[str] = None,
                     approved: bool = False) -> Dict[str, Any]:
    """Record (or reinforce) a document selection for an analysis. Approval is
    what makes it suggestible later. Never raises."""
    doc_ids = [d for d in (doc_ids or []) if d]
    if not akey or not doc_ids:
        return {"ok": False, "reason": "analysis_key and doc_ids required"}
    try:
        with _LOCK:
            data = _load()
            key = _scope_key(corpus, project_id, akey)
            rec = data.get(key, {"doc_ids": [], "uses": 0, "approved": False})
            rec["doc_ids"] = doc_ids
            rec["uses"] = int(rec.get("uses", 0)) + 1
            rec["approved"] = bool(rec.get("approved")) or approved
            rec["last_used"] = datetime.now().isoformat()
            rec["corpus"] = corpus
            rec["project_id"] = project_id
            data[key] = rec
            _save(data)
        return {"ok": True, "key": key, "approved": rec["approved"]}
    except Exception as e:
        logger.warning(f"[DocumentMemory] record failed: {e}")
        return {"ok": False, "reason": str(e)[:200]}


def confirm_selection(akey: str, doc_ids: List[str], corpus: str = "",
                      project_id: Optional[str] = None) -> Dict[str, Any]:
    """Mark a selection as analyst-approved (suggestible)."""
    return record_selection(akey, doc_ids, corpus, project_id, approved=True)


def suggest(akey: str, corpus: str = "",
            project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return a previously APPROVED selection for this project+analysis, or None.

    The caller must confirm with the user before reuse — this is a suggestion,
    never an automatic input. Never raises."""
    try:
        with _LOCK:
            rec = _load().get(_scope_key(corpus, project_id, akey))
        if not rec or not rec.get("approved") or not rec.get("doc_ids"):
            return None
        return {"doc_ids": list(rec["doc_ids"]),
                "approved": True,
                "uses": int(rec.get("uses", 0)),
                "last_used": rec.get("last_used", "")}
    except Exception as e:
        logger.debug(f"[DocumentMemory] suggest failed: {e}")
        return None
