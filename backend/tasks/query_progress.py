"""Thread-safe in-memory query-time activity store.

Mirrors ``backend/tasks/progress.py`` (indexing progress) but for the chat
query path: the synchronous router/agent code deep in src/ publishes ordered
"activity" steps ("reading cdf2392.pdf", "analysing…") for the in-flight
request, and the frontend polls ``GET /chat/progress/{request_id}`` to render a
live feed instead of a frozen "Analyzing…" spinner.

Correlation rides a ContextVar (``query_request_var``) set by the orchestrator
before ``asyncio.to_thread`` — ContextVars propagate into the worker thread, so
the deep code calls ``report_step(...)`` without threading request_id through
every signature (same trick as ``current_file_var`` for indexing).
"""

import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Caps so a runaway agent loop or an abandoned request can't grow unbounded.
_STEP_CAP = 200          # max steps retained per request
_TTL_SECONDS = 900       # drop activities older than this on the next start()


@dataclass
class QueryStep:
    seq: int
    ts: float
    kind: str            # thinking | searching | reading | related | analysing | tool | answer
    label: str           # human-facing line, e.g. "reading cdf2392.pdf"
    detail: str = ""


@dataclass
class QueryActivity:
    request_id: str
    created_at: float
    updated_at: float
    steps: List[QueryStep] = field(default_factory=list)
    done: bool = False


class QueryProgress:
    def __init__(self):
        self._store: Dict[str, QueryActivity] = {}
        self._lock = threading.Lock()

    def _purge_locked(self, now: float) -> None:
        stale = [rid for rid, a in self._store.items() if now - a.updated_at > _TTL_SECONDS]
        for rid in stale:
            self._store.pop(rid, None)

    def start(self, request_id: str) -> None:
        if not request_id:
            return
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            self._store[request_id] = QueryActivity(
                request_id=request_id, created_at=now, updated_at=now,
            )

    def add(self, request_id: str, kind: str, label: str, detail: str = "") -> None:
        if not request_id:
            return
        now = time.time()
        with self._lock:
            act = self._store.get(request_id)
            if act is None:
                # report_step may fire before start() (or after purge) — create lazily.
                act = QueryActivity(request_id=request_id, created_at=now, updated_at=now)
                self._store[request_id] = act
            if len(act.steps) >= _STEP_CAP:
                return
            act.steps.append(QueryStep(seq=len(act.steps), ts=now, kind=kind,
                                       label=label, detail=detail))
            act.updated_at = now

    def finish(self, request_id: str) -> None:
        if not request_id:
            return
        with self._lock:
            act = self._store.get(request_id)
            if act is not None:
                act.done = True
                act.updated_at = time.time()

    def get(self, request_id: str) -> Optional[QueryActivity]:
        return self._store.get(request_id)


query_progress = QueryProgress()


# The request currently being answered in THIS worker thread. Set by the chat
# orchestrator before route_and_execute runs; deep router/agent code reads it
# via report_step. Per-thread, so concurrent requests don't cross streams.
query_request_var: ContextVar[str] = ContextVar("query_request", default="")


def report_step(kind: str, label: str, detail: str = "") -> None:
    """Publish one activity step for the current request (best-effort).

    No-op outside a chat request (e.g. bulk scripts, tests) — `kind` is a short
    machine tag (thinking/searching/reading/related/analysing/tool/answer) and
    `label` is the user-facing line shown in the live feed."""
    try:
        rid = query_request_var.get()
        if rid:
            query_progress.add(rid, kind, label, detail)
            try:
                from src.run_store import get_run_store
                get_run_store().add_step(rid, kind, label, detail)
            except Exception:
                pass
    except Exception:
        pass
