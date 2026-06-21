"""Teacher-LLM — the periodic pass that strengthens the structure the live system
reads for free.

A cheap "student" (the live query path) runs constantly; an expensive "teacher"
runs occasionally (threshold / cron / admin), reads the accumulated substrates
(event_timeline + interaction_log + enrichment + clusters) and distils them into
better structure. The teacher is NEVER on the query path, so its cost is seldom
and bounded (cluster/batch-sized, not per-query). Everything it writes is additive
and read by the student at no extra LLM cost:

  * event chains       → storage/teacher/event_chains.json   (delay→excuse→decision)
  * scope curriculum   → storage/learned/scope_examples.jsonl (few-shots for
                          router.compute_query_scope — learned from WEAK answers)
  * cluster summaries  → storage/teacher/cluster_summaries.json (RAPTOR-lite)

Learning here is FEEDBACK-FREE: its inputs are the system's own usage (which docs
co-occur, which answers came back weak), not human 👍/👎.

Run:  PYTHONPATH=. python scripts/run_teacher.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .config import STORAGE_DIR
from .logger import logger

TEACHER_DIR = STORAGE_DIR / "teacher"
LEARNED_DIR = STORAGE_DIR / "learned"
EVENT_CHAINS_FILE = TEACHER_DIR / "event_chains.json"
CLUSTER_SUMMARIES_FILE = TEACHER_DIR / "cluster_summaries.json"
SCOPE_EXAMPLES_FILE = LEARNED_DIR / "scope_examples.jsonl"


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_scope_examples(limit: int = 8) -> List[Dict]:
    """Few-shot (question → scope) pairs the teacher distilled from weak answers.
    Read by router.compute_query_scope to improve scope detection over time."""
    if not SCOPE_EXAMPLES_FILE.exists():
        return []
    out: List[Dict] = []
    try:
        for line in SCOPE_EXAMPLES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("question") and isinstance(rec.get("scope"), dict):
                    out.append(rec)
            except Exception:
                continue
    except Exception:
        return []
    return out[-limit:]


class Teacher:
    """Periodic batch passes over the learning substrates."""

    def run(self, max_events: int = 200, max_weak: int = 50) -> Dict[str, int]:
        stats = {"chains": 0, "scope_examples": 0, "cluster_summaries": 0}
        try:
            stats["chains"] = self._link_event_chains(max_events)
        except Exception as e:
            logger.warning(f"[Teacher] event-chain pass failed: {e}")
        try:
            stats["scope_examples"] = self._distil_scope_curriculum(max_weak)
        except Exception as e:
            logger.warning(f"[Teacher] scope-curriculum pass failed: {e}")
        try:
            stats["cluster_summaries"] = self._summarize_clusters()
        except Exception as e:
            logger.warning(f"[Teacher] cluster-summary pass failed: {e}")
        logger.info(f"[Teacher] done: {stats}")
        return stats

    # ── Pass 1: causal event chains (delay → excuse → decision) ───────────
    def _link_event_chains(self, max_events: int) -> int:
        """Ask the LLM to connect date-sorted events into cause→effect chains,
        cross-referenced with the co-retrieval graph. This is what lets the
        chronological route answer 'X was delayed BECAUSE letter Y …'."""
        from .event_timeline import get_event_timeline
        from . import llm_client
        from .prompt_security import build_system_prompt

        events = get_event_timeline().timeline_context(limit=max_events)
        if len(events) < 2:
            return 0

        lines = []
        for i, e in enumerate(events):
            lines.append(
                f"[{i}] {e.get('date','')} {e.get('event_type','')} | "
                f"actor={e.get('actor','')} | {e.get('reason') or e.get('description','')} "
                f"| doc={e.get('file_name','')}"
            )
        prompt = (
            "Below are date-sorted construction-project events. Identify CAUSAL CHAINS "
            "— where one event (e.g. a delay/disruption) is explained by another (an "
            "excuse/decision/claim), typically close in time and sharing an actor or "
            "subject. Return ONE JSON object:\n"
            '{ "chains": [ { "summary": "<one line: what happened and why>", '
            '"event_indices": [<int>, ...], "documents": ["<file>", ...] } ] }\n'
            "Only link events that are genuinely related; use [] if none. JSON only.\n\n"
            + "\n".join(lines)
        )
        try:
            resp = llm_client.generate_json(
                prompt,
                system=build_system_prompt("You build causal timelines. JSON only."),
            )
            data = resp.raw if isinstance(resp.raw, dict) else {}
        except Exception as e:
            logger.warning(f"[Teacher] chain LLM failed: {e}")
            return 0

        chains = [c for c in (data.get("chains") or []) if isinstance(c, dict)]
        # Attach the concrete event rows each chain references (for evidence).
        for c in chains:
            idxs = [i for i in (c.get("event_indices") or []) if isinstance(i, int) and 0 <= i < len(events)]
            c["events"] = [events[i] for i in idxs]
        _save_json(EVENT_CHAINS_FILE, {"chains": chains})
        return len(chains)

    # ── Pass 2: self-supervised scope curriculum from weak answers ────────
    def _distil_scope_curriculum(self, max_weak: int) -> int:
        """Mine queries whose answer came back WEAK/empty and learn what SCOPE
        would have helped — written as few-shots for compute_query_scope. This is
        the system learning from its OWN mistakes, no human feedback."""
        from .interaction_log import get_interaction_log
        from . import llm_client
        from .prompt_security import build_system_prompt

        weak = get_interaction_log().weak_interactions(limit=max_weak)
        if not weak:
            return 0
        qs = [w["query"] for w in weak if w.get("query")][:max_weak]
        if not qs:
            return 0

        listing = "\n".join(f"- {q}" for q in qs)
        prompt = (
            "These user questions produced weak or empty answers. For each, infer the "
            "retrieval SCOPE that would have helped (controlled values only; null when "
            "not implied). Return ONE JSON object:\n"
            '{ "examples": [ { "question": "<verbatim>", "scope": { '
            '"doc_type": <...|null>, "event_type": <delay|disruption|excuse|decision|'
            'milestone|claim|null>, "project": <...|null>, "date_from": <...|null>, '
            '"date_to": <...|null>, "topic": <...|null> } } ] }\n'
            "JSON only.\n\nQUESTIONS:\n" + listing
        )
        try:
            resp = llm_client.generate_json(
                prompt,
                system=build_system_prompt("You infer retrieval scope. JSON only."),
            )
            data = resp.raw if isinstance(resp.raw, dict) else {}
        except Exception as e:
            logger.warning(f"[Teacher] scope LLM failed: {e}")
            return 0

        examples = [e for e in (data.get("examples") or [])
                    if isinstance(e, dict) and e.get("question") and isinstance(e.get("scope"), dict)]
        if not examples:
            return 0
        # Append (dedupe-light) as JSONL few-shots.
        LEARNED_DIR.mkdir(parents=True, exist_ok=True)
        seen = {e["question"] for e in get_scope_examples(limit=500)}
        n = 0
        with open(SCOPE_EXAMPLES_FILE, "a", encoding="utf-8") as f:
            for ex in examples:
                if ex["question"] in seen:
                    continue
                clean_scope = {k: v for k, v in ex["scope"].items()
                               if v not in (None, "", "null")}
                if not clean_scope:
                    continue
                f.write(json.dumps({"question": ex["question"], "scope": clean_scope},
                                   ensure_ascii=False) + "\n")
                n += 1
        return n

    # ── Pass 3: RAPTOR-lite cluster summaries ─────────────────────────────
    def _summarize_clusters(self) -> int:
        """One short summary per document cluster, so global/scoped questions can
        retrieve a summary tier instead of scanning every chunk. Produced here;
        summary-tier retrieval wiring is a follow-up that reads this file."""
        try:
            from .document_clusterer import get_clusterer
            clusters = get_clusterer().list_clusters()
        except Exception as e:
            logger.debug(f"[Teacher] clusterer unavailable: {e}")
            return 0
        if not clusters:
            return 0

        from . import llm_client
        from .prompt_security import build_system_prompt
        try:
            from .document_registry import get_document_registry
            reg = get_document_registry()
        except Exception:
            reg = None

        summaries = {}
        for c in clusters[:40]:
            label = c.get("label", "")
            cid = c.get("cluster_id", "")
            # Use the cluster label + a few member summaries as the basis.
            basis = label
            prompt = (
                "Summarise, in ONE sentence, what this group of construction-project "
                f"documents is about. Group label: '{label}'. Document count: "
                f"{c.get('doc_count', 0)}. Reply with the sentence only."
            )
            try:
                resp = llm_client.generate_text(
                    prompt,
                    system=build_system_prompt("You write one-line group summaries."),
                    max_tokens=80,
                )
                summaries[cid] = {"label": label, "summary": resp.text.strip(),
                                  "doc_count": c.get("doc_count", 0)}
            except Exception:
                continue
        if summaries:
            _save_json(CLUSTER_SUMMARIES_FILE, summaries)
        return len(summaries)


_instance: "Teacher | None" = None


def get_teacher() -> Teacher:
    global _instance
    if _instance is None:
        _instance = Teacher()
    return _instance
