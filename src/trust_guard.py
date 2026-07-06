"""Trust Guard — risk-gated post-answer verification layer.

Runs AFTER a draft answer exists, only for medium/high-risk queries, and only
on document-ish routes. Pipeline:

    assess_risk → check_entities (corpus existence, no LLM)
                → verify_claims (one lite-model JSON call)
                → optional re-retrieval (max TRUST_GUARD_MAX_RERETRIEVALS)
                → compose (caveats appended deterministically; rewrite/refuse
                  spend one more lite call at most)

Targets the QA failure patterns: false premise acceptance, fake-entity silent
substitution (Morrison MacDonald → Mott MacDonald), ghost attribution.

Fails open everywhere: any exception returns the draft unmodified with
skipped=True so a verifier outage can never block an answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .config import (
    GEMINI_MODEL_LITE,
    TRUST_GUARD_MIN_RISK,
    TRUST_GUARD_MAX_RERETRIEVALS,
)

logger = logging.getLogger(__name__)

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

# Query types the guard applies to. DATA (SQL) answers are deterministic table
# reads — claim verification doesn't fit them; FILE_LIST is a catalog listing.
GUARDED_QUERY_TYPES = {"document", "hybrid", "timeline", "thread"}

# ── Risk keyword tiers (English product; Turkish aliases kept because the
#    existing verifier tokens are Turkish and operators sometimes test in TR) ──
_HIGH_RISK_RE = re.compile(
    r"\b(claims?|liab\w*|responsib\w*|entitle\w*|EOT|extension of time|"
    r"time[- ]bar\w*|breach\w*|disput\w*|compensat\w*|damages|LDs|penalt\w*|"
    r"who (?:caused|is responsible|was responsible)|at fault|blame\w*|"
    r"cost overrun|kim sorumlu|hak talebi|s[uü]re uzat[ıi]m[ıi]|tazminat)\b",
    re.IGNORECASE,
)
_MEDIUM_RISK_RE = re.compile(
    r"\b(delay\w*|notices?|notif\w*|caus\w*|costs?|chronolog\w*|timeline|"
    r"why did|when did|evidence|according to|concluded?|testif\w*|admit\w*|"
    r"report\w* by|audit\w*|gecikme|neden|maliyet)\b",
    re.IGNORECASE,
)
# Capitalized multi-word proper noun ("Morrison MacDonald", "Mott MacDonald")
# or a quoted name — a named-entity question is at least medium risk even
# without risk keywords, because silent substitution is the #1 QA failure.
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+(?:Mac|Mc|O')?[A-Z][a-zA-Z]+)+\b")
_QUOTED_RE = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{3,60})[\"'“”‘’]")
_FILENAME_TOKEN_RE = re.compile(r"\b[\w-]+\.(?:pdf|docx?|xlsx?|csv|msg|eml|xer)\b", re.IGNORECASE)

# Leading words that start a sentence and look like proper-noun bigram parts.
_ENTITY_STOPWORDS = {
    "the", "what", "who", "why", "when", "where", "which", "how", "did", "does",
    "summarise", "summarize", "list", "show", "give", "tell", "explain", "compare",
    "edinburgh", "tram", "trams", "project", "council", "report", "letter", "dr",
    "mr", "mrs", "ms", "extension", "time",
}


@dataclass
class TrustVerdict:
    risk: str = "low"                    # low | medium | high
    action: str = "approve"              # approve | approve_with_caveats | rewrite | refuse
    sufficiency: float = 1.0             # evidence_sufficiency_score 0..1
    sufficiency_label: str = "verified"  # verified | partially_supported | insufficient | unverified
    caveats: List[str] = field(default_factory=list)
    analyst_review_required: bool = False
    unknown_entities: List[Dict[str, Any]] = field(default_factory=list)
    re_retrieved: bool = False
    skipped: bool = False                # guard didn't run (low risk / flag off / error)
    # Why the guard skipped: disabled | risk_below_threshold | route_excluded |
    # selected_context | greeting | empty_answer | error. Empty when not skipped.
    skipped_reason: str = ""
    # LLM calls the guard itself spent (verifier calls + composer rewrite).
    # Re-retrieval synthesis inside _handle_document_query is NOT counted.
    llm_calls: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _report(kind: str, label: str, detail: str = "") -> None:
    """Best-effort progress step (no-op outside a chat request)."""
    try:
        from backend.tasks.query_progress import report_step
        report_step(kind, label, detail)
    except Exception:
        pass


# ── 1. Risk classifier ───────────────────────────────────────

def assess_risk(question: str, routing_confidence: Optional[float] = None) -> str:
    """Deterministic risk tier for the CURRENT question (no LLM).

    high   — liability / entitlement / responsibility / claim language
    medium — delay / notice / causation / chronology language, OR a named
             multi-word proper noun / quoted name / filename in the question
    low    — everything else
    Low routing confidence (<0.7) bumps medium → high.
    """
    q = (question or "").strip()
    if not q:
        return "low"
    if _HIGH_RISK_RE.search(q):
        return "high"
    medium = bool(
        _MEDIUM_RISK_RE.search(q)
        or _QUOTED_RE.search(q)
        or _FILENAME_TOKEN_RE.search(q)
        or _extract_proper_nouns(q)
    )
    if not medium:
        return "low"
    if routing_confidence is not None and routing_confidence < 0.7:
        return "high"
    return "medium"


def _risk_at_least(risk: str, minimum: str) -> bool:
    return _RISK_ORDER.get(risk, 0) >= _RISK_ORDER.get(minimum, 1)


# ── 2. Entity / premise pre-check (no LLM) ───────────────────

def _extract_proper_nouns(question: str) -> List[str]:
    """Multi-word capitalized names, filtered against question-lead stopwords."""
    out: List[str] = []
    for m in _PROPER_NOUN_RE.finditer(question or ""):
        cand = m.group(0).strip()
        words = cand.split()
        # Drop leading stopword tokens ("What Siemens" → "Siemens" is 1 word → skip)
        while words and words[0].lower() in _ENTITY_STOPWORDS:
            words = words[1:]
        if len(words) >= 2:
            out.append(" ".join(words))
    return out


def extract_entity_candidates(question: str, cap: int = 5) -> List[Dict[str, str]]:
    """Over-inclusive deterministic extraction of checkable named entities.

    Returns [{"name", "kind"}] where kind is "document" (filename-looking) or
    "name" (person/company/report title). Capped to keep the check cheap.
    """
    q = question or ""
    seen: set[str] = set()
    out: List[Dict[str, str]] = []

    def _add(name: str, kind: str) -> None:
        key = name.lower().strip()
        if key and key not in seen and len(out) < cap:
            seen.add(key)
            out.append({"name": name.strip(), "kind": kind})

    for m in _FILENAME_TOKEN_RE.finditer(q):
        _add(m.group(0), "document")
    for m in _QUOTED_RE.finditer(q):
        _add(m.group(1), "name")
    for cand in _extract_proper_nouns(q):
        _add(cand, "name")
    return out


def _capitalized_ngrams(text: str) -> List[str]:
    """Capitalized multi-word sequences found in evidence text (for fuzzy recovery)."""
    return [m.group(0) for m in _PROPER_NOUN_RE.finditer(text or "")]


def _fuzzy_similar_from_chunks(candidate: str, chunks: List[Dict], cutoff: int = 75) -> List[str]:
    """Recover 'did you mean X' names: rank capitalized n-grams appearing in FTS
    hit snippets against the unknown candidate (Morrison MacDonald → chunks
    containing 'MacDonald' → 'Mott MacDonald' at ratio ≥ cutoff)."""
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return []
    scores: Dict[str, int] = {}
    for ch in chunks:
        for ngram in _capitalized_ngrams(ch.get("text") or ""):
            if ngram.lower() == candidate.lower():
                continue
            s = int(fuzz.token_set_ratio(candidate.lower(), ngram.lower()))
            if s >= cutoff:
                scores[ngram] = max(scores.get(ngram, 0), s)
    return [n for n, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:3]]


def check_entities(question: str, router: Any = None) -> Dict[str, Any]:
    """Existence check for named entities in the question, cheapest-first.

    documents → router._resolve_filename_hints (registry substring + fuzzy)
    names     → Entity Registry first (deterministic, ingest/backfill-built,
                corpus-scoped); falls back to LexicalIndex exact-phrase FTS +
                fuzzy snippet recovery only when the registry has no entities
                for the user's corpus (e.g. before the backfill has run).
    Returns {"known": [names], "unknown": [{"name","kind","similar":[...]}]}.
    """
    known: List[str] = []
    unknown: List[Dict[str, Any]] = []
    candidates = extract_entity_candidates(question)
    if not candidates:
        return {"known": known, "unknown": unknown}

    # Entity Registry (preferred): fast lookups, no FTS rebuild cost.
    registry = None
    corpus = "demo"
    try:
        from .document_rag import _current_user_corpus
        corpus = (_current_user_corpus() or "demo").lower()
    except Exception:
        pass
    try:
        from .entity_registry import get_entity_registry
        reg = get_entity_registry()
        if reg.count(corpus) > 0:
            registry = reg
    except Exception as e:
        logger.debug(f"[TrustGuard] entity registry unavailable: {e}")

    lex = None
    if registry is None:
        try:
            from .lexical_index import get_lexical_index
            lex = get_lexical_index()
        except Exception as e:
            logger.debug(f"[TrustGuard] lexical index unavailable: {e}")

    for cand in candidates:
        name, kind = cand["name"], cand["kind"]
        try:
            if kind == "document" and router is not None:
                hints = router._resolve_filename_hints(name)
                exact = [h for h in hints if name.lower() in h.lower()]
                if exact:
                    known.append(name)
                else:
                    unknown.append({"name": name, "kind": kind, "similar": hints[:3]})
                continue

            _report("verifying", f"Checking whether '{name}' appears in the corpus...")
            if registry is not None:
                if registry.find(name, corpus):
                    known.append(name)
                else:
                    similar = registry.similar(name, corpus, cutoff=75)
                    unknown.append({"name": name, "kind": kind, "similar": similar})
                continue

            if lex is None:
                continue  # can't check — don't claim unknown without evidence
            hits = lex.search_chunks(f'"{name}"', top_k=3)
            phrase_found = any(name.lower() in (h.get("text") or "").lower() for h in hits)
            if phrase_found:
                known.append(name)
                continue
            # Token-level search for fuzzy recovery of the intended entity.
            token_hits = lex.search_chunks(name, top_k=8)
            similar = _fuzzy_similar_from_chunks(name, token_hits)
            unknown.append({"name": name, "kind": kind, "similar": similar})
        except Exception as e:
            logger.debug(f"[TrustGuard] entity check failed for '{name}': {e}")

    if unknown:
        logger.info(
            "[TrustGuard] unknown entities: "
            + ", ".join(f"{u['name']}→{u['similar'] or 'no match'}" for u in unknown)
        )
    return {"known": known, "unknown": unknown}


# ── 3. Claim-level verifier (one lite-model JSON call) ───────

_VERIFIER_SYSTEM = (
    "You are a strict evidence verifier for a construction-project document "
    "assistant. You do NOT answer the question. You judge whether a draft "
    "answer is supported by the supplied evidence chunks. Reward grounding, "
    "not fluency. Output JSON only."
)

_ACTIONS = {"approve", "approve_with_caveats", "rewrite_required",
            "re_retrieval_required", "refuse"}


def _format_evidence(sources: List[Dict], max_chunks: int = 8, max_chars: int = 700) -> str:
    lines = []
    for i, s in enumerate(sources or []):
        if s.get("type") == "structured_data":
            continue
        if len(lines) >= max_chunks:
            break
        fn = s.get("file_name") or "unknown"
        page = s.get("page_number")
        loc = f"{fn}" + (f" p.{page}" if page else "")
        text = (s.get("text") or "")[:max_chars]
        lines.append(f"[E{len(lines) + 1}] ({loc}) {text}")
    return "\n\n".join(lines) if lines else "(no evidence chunks retrieved)"


def verify_claims(
    question: str,
    answer: str,
    sources: List[Dict],
    entity_report: Dict[str, Any],
    high_risk: bool = False,
) -> Dict[str, Any]:
    """One lite-model JSON call judging the draft against the evidence.

    Returns the trimmed verifier contract:
    {claims: [{text, status, evidence}], evidence_sufficiency_score,
     final_action, safe_answer_instructions, caveats}
    Raises on LLM/JSON failure — caller fails open.
    """
    from . import llm_client
    from .prompt_security import build_system_prompt

    unknown = entity_report.get("unknown") or []
    entity_note = ""
    if unknown:
        entity_note = (
            "\nENTITY PRE-CHECK (deterministic corpus search — treat as ground truth):\n"
            + "\n".join(
                f"- '{u['name']}' was NOT found in the corpus."
                + (f" Closest names in the corpus: {', '.join(u['similar'])}." if u.get("similar") else "")
                for u in unknown
            )
            + "\nIf the draft attributes anything to a not-found entity, or silently "
            "answers about a similar entity instead, the draft is NOT approvable as-is.\n"
        )

    contradiction_note = (
        "\nAlso flag any claim that CONTRADICTS the evidence, not just unsupported ones.\n"
        if high_risk else ""
    )

    prompt = (
        "Judge the DRAFT ANSWER against the EVIDENCE.\n\n"
        f"QUESTION:\n{question[:1000]}\n\n"
        f"DRAFT ANSWER:\n{(answer or '')[:3000]}\n\n"
        f"EVIDENCE:\n{_format_evidence(sources)}\n"
        f"{entity_note}{contradiction_note}\n"
        "Steps:\n"
        "1. Extract factual assertions embedded in the QUESTION (presuppositions "
        "like 'X admitted liability', 'the project came under budget'). If the "
        "evidence does not support a presupposition, the draft must challenge it "
        "— if it doesn't, that is an unsupported claim.\n"
        "2. Break the DRAFT ANSWER into its main factual claims (max 8).\n"
        "3. For each claim decide: supported | unsupported | contradicted, and "
        "name the evidence chunk (e.g. 'E2') or leave empty.\n"
        "4. Score overall evidence sufficiency 0.0-1.0.\n"
        "5. Pick final_action: approve | approve_with_caveats | rewrite_required "
        "| re_retrieval_required | refuse.\n"
        "   - approve: everything material is supported.\n"
        "   - approve_with_caveats: minor gaps; answer is usable with notes.\n"
        "   - rewrite_required: important unsupported/contradicted claims.\n"
        "   - re_retrieval_required: evidence is topically relevant but misses "
        "what the question actually asks (better retrieval could fix it).\n"
        "   - refuse: the question rests on an entity/premise absent from the "
        "corpus, or the evidence cannot support any useful answer.\n"
        "6. Write short user-facing caveat sentences (English) for every gap.\n\n"
        "Return JSON only:\n"
        '{"claims": [{"text": "...", "status": "supported|unsupported|contradicted", '
        '"evidence": "E1 or empty"}], "evidence_sufficiency_score": 0.0, '
        '"final_action": "approve|approve_with_caveats|rewrite_required|'
        're_retrieval_required|refuse", "safe_answer_instructions": "", "caveats": []}'
    )

    resp = llm_client.generate_json(
        prompt,
        system=build_system_prompt(_VERIFIER_SYSTEM),
        model=GEMINI_MODEL_LITE,
    )
    try:
        from .telemetry import get_current_trace
        tr = get_current_trace()
        if tr:
            tr.record_llm_call(resp.usage)
    except Exception:
        pass

    data = resp.raw if isinstance(resp.raw, dict) else {}
    # Normalize the contract defensively — lite models drift.
    action = str(data.get("final_action") or "").strip()
    if action not in _ACTIONS:
        action = "approve_with_caveats"
    claims = [c for c in (data.get("claims") or []) if isinstance(c, dict)][:10]
    try:
        score = max(0.0, min(1.0, float(data.get("evidence_sufficiency_score", 0.5))))
    except (TypeError, ValueError):
        score = 0.5
    caveats = [str(c).strip() for c in (data.get("caveats") or []) if str(c).strip()][:5]
    return {
        "claims": claims,
        "evidence_sufficiency_score": score,
        "final_action": action,
        "safe_answer_instructions": str(data.get("safe_answer_instructions") or ""),
        "caveats": caveats,
    }


def apply_substitution_override(
    verdict_json: Dict[str, Any],
    entity_report: Dict[str, Any],
    answer: str,
) -> Dict[str, Any]:
    """Deterministic guard against silent entity substitution.

    If the question named an entity that is NOT in the corpus and the draft
    talks about a similar entity instead (or the entity has no match at all),
    force at least approve_with_caveats and inject an explicit caveat. Never
    rely on the lite model to catch this.
    """
    unknown = entity_report.get("unknown") or []
    if not unknown:
        return verdict_json
    a_low = (answer or "").lower()
    forced: List[str] = []
    for u in unknown:
        name = u["name"]
        similar = u.get("similar") or []
        # A similar entity the draft actually talks about is the strongest
        # signal of what the user meant — surface it first so the
        # "did you mean X" caveat names the substituted entity, not merely
        # the fuzzy-closest one.
        mentioned = [s for s in similar if s.lower() in a_low]
        if mentioned:
            similar = mentioned + [s for s in similar if s not in mentioned]
            u["similar"] = similar
        substituted = bool(mentioned)
        # Draft acknowledges the entity is missing? Then no forced caveat needed.
        acknowledges = name.lower() in a_low and any(
            phrase in a_low for phrase in ("not found", "no record", "could not find",
                                           "couldn't find", "does not appear", "no mention")
        )
        if acknowledges and not substituted:
            continue
        if similar:
            forced.append(
                f"'{name}' was not found in the corpus; the closest match is "
                f"'{similar[0]}'. Please confirm which entity you mean."
            )
        else:
            forced.append(f"'{name}' was not found in the indexed documents.")
    if not forced:
        return verdict_json
    existing = verdict_json.get("caveats") or []
    verdict_json["caveats"] = forced + [c for c in existing if c not in forced]
    if verdict_json.get("final_action") in ("approve", "approve_with_caveats"):
        verdict_json["final_action"] = "approve_with_caveats"
    verdict_json["evidence_sufficiency_score"] = min(
        float(verdict_json.get("evidence_sufficiency_score", 0.5)), 0.69
    )
    return verdict_json


# ── 4. Re-retrieval query ────────────────────────────────────

def build_reretrieval_query(question: str, entity_report: Dict[str, Any]) -> str:
    """Deterministic improved query: original question + exact known-entity
    names + best 'similar' names for unknowns (entity-first retrieval)."""
    parts = [question.strip()]
    for name in entity_report.get("known") or []:
        if name.lower() not in question.lower():
            parts.append(f'"{name}"')
    for u in entity_report.get("unknown") or []:
        for s in (u.get("similar") or [])[:1]:
            parts.append(f'"{s}"')
    return " ".join(parts)


# ── 5. Composer ──────────────────────────────────────────────

def _sufficiency_label(score: float, action: str) -> str:
    if action == "refuse":
        return "insufficient"
    if action == "approve" and score >= 0.7:
        return "verified"
    if score >= 0.5:
        return "partially_supported"
    return "insufficient"


def _caveat_block(caveats: List[str]) -> str:
    lines = "\n".join(f"- {c}" for c in caveats)
    return f"\n\n---\n**Verification notes:**\n{lines}"


def compose_final_answer(
    question: str,
    answer: str,
    verdict_json: Dict[str, Any],
    entity_report: Dict[str, Any],
) -> tuple[str, bool]:
    """Produce the user-facing answer per the verifier's final_action.

    approve → passthrough; approve_with_caveats → deterministic caveat block;
    refuse with unknown entities → deterministic template; rewrite/other refuse
    → one lite-model rewrite constrained to supported claims.
    Returns (answer, llm_used) so the caller can count guard LLM spend.
    """
    action = verdict_json.get("final_action")
    caveats = verdict_json.get("caveats") or []

    if action == "approve":
        return answer, False
    if action in ("approve_with_caveats", "re_retrieval_required"):
        # re_retrieval lands here only after the retry budget is exhausted.
        return answer + _caveat_block(caveats or
                                      ["Some statements could not be fully verified against the documents."]), False

    unknown = entity_report.get("unknown") or []
    if action == "refuse" and unknown:
        parts = []
        for u in unknown:
            if u.get("similar"):
                parts.append(
                    f"I could not find **{u['name']}** in the indexed documents. "
                    f"Did you mean **{u['similar'][0]}**?"
                )
            else:
                parts.append(f"I could not find **{u['name']}** in the indexed documents.")
        parts.append("Please confirm the name and I'll search again.")
        return "\n\n".join(parts), False

    # rewrite_required (or refuse with partial content): one lite call.
    from . import llm_client
    from .prompt_security import build_system_prompt

    supported = [c.get("text", "") for c in (verdict_json.get("claims") or [])
                 if c.get("status") == "supported"]
    problems = [f"{c.get('status')}: {c.get('text', '')}"
                for c in (verdict_json.get("claims") or [])
                if c.get("status") in ("unsupported", "contradicted")]
    prompt = (
        "Rewrite the draft answer so it contains ONLY claims supported by the "
        "evidence. Remove or explicitly caveat everything else. Keep citations "
        "(document names/pages) that the draft already used for supported "
        "claims. Do not add new facts. English.\n\n"
        f"QUESTION:\n{question[:1000]}\n\n"
        f"DRAFT:\n{(answer or '')[:3000]}\n\n"
        f"SUPPORTED CLAIMS:\n" + ("\n".join(f"- {s}" for s in supported) or "- (none)") + "\n\n"
        f"PROBLEM CLAIMS (remove or caveat):\n" + ("\n".join(f"- {p}" for p in problems) or "- (none)") + "\n\n"
        f"INSTRUCTIONS FROM THE VERIFIER:\n{verdict_json.get('safe_answer_instructions') or '(none)'}"
    )
    resp = llm_client.generate_text(
        prompt,
        system=build_system_prompt(
            "You revise answers to match the verified evidence. Concise, factual, English."
        ),
        model=GEMINI_MODEL_LITE,
        max_tokens=1500,
    )
    rewritten = (resp.text or "").strip() or answer
    if caveats:
        rewritten += _caveat_block(caveats)
    return rewritten, True


# ── 6. Orchestration ─────────────────────────────────────────

def verdict_to_verify_token(verdict: TrustVerdict) -> str:
    """Map a TrustVerdict onto the legacy verify_verdict tokens consumed by the
    learning loop (OK | WEAK | OFFTOPIC)."""
    if verdict.action == "approve":
        return "OK"
    if verdict.action == "refuse":
        return "OFFTOPIC"
    return "WEAK"


def run_trust_guard(
    router: Any,
    query: str,
    result: Dict[str, Any],
    doc_ids: Optional[List[str]] = None,
) -> TrustVerdict:
    """Entry point called from QueryRouter.route_and_execute.

    Mutates result["answer"] / result["sources"] when the composer changes the
    answer or a re-retrieval produced better sources. Fails open.
    """
    try:
        question = router._current_question(query) if router is not None else (query or "")
    except Exception:
        question = query or ""

    routing_conf = None
    try:
        routing_conf = (result.get("routing") or {}).get("confidence")
    except Exception:
        pass

    risk = assess_risk(question, routing_confidence=routing_conf)
    if not _risk_at_least(risk, TRUST_GUARD_MIN_RISK):
        return TrustVerdict(risk=risk, skipped=True, sufficiency_label="unverified",
                            skipped_reason="risk_below_threshold")

    answer = (result.get("answer") or "").strip()
    # LlamaIndex's unsynthesized placeholder is not a verifiable answer — the
    # response builder blanks it downstream, so verifying it wastes calls.
    if not answer or answer.lower() in ("empty response", "none"):
        return TrustVerdict(risk=risk, skipped=True, sufficiency_label="unverified",
                            skipped_reason="empty_answer")

    llm_calls = 0
    try:
        _report("draft", "Here's my initial answer — verifying it now...", answer)
        entity_report = check_entities(question, router)

        _report("verifying", "Cross-checking the answer against the cited documents...")
        verdict_json = verify_claims(
            question, answer, result.get("sources") or [], entity_report,
            high_risk=(risk == "high"),
        )
        llm_calls += 1
        verdict_json = apply_substitution_override(verdict_json, entity_report, answer)

        # ── Re-retrieval (bounded) ──
        re_retrieved = False
        retries = 0
        while (
            verdict_json.get("final_action") == "re_retrieval_required"
            and retries < TRUST_GUARD_MAX_RERETRIEVALS
            and router is not None
        ):
            retries += 1
            _report("re_retrieval",
                    "Found a gap — let me check a few more documents to strengthen this answer...")
            try:
                improved = build_reretrieval_query(question, entity_report)
                new_result = router._handle_document_query(improved, doc_ids)
                new_answer = (new_result.get("answer") or "").strip()
                if new_answer and new_result.get("sources"):
                    answer = new_answer
                    result["answer"] = new_answer
                    result["sources"] = new_result["sources"]
                    re_retrieved = True
                    _report("verifying", "Re-checking the strengthened answer against the documents...")
                    verdict_json = verify_claims(
                        question, answer, result["sources"], entity_report,
                        high_risk=(risk == "high"),
                    )
                    llm_calls += 1
                    verdict_json = apply_substitution_override(verdict_json, entity_report, answer)
                else:
                    break
            except Exception as e:
                logger.warning(f"[TrustGuard] re-retrieval failed: {e}")
                break
        if verdict_json.get("final_action") == "re_retrieval_required":
            # Retry budget exhausted — demote to caveats (composer handles it).
            verdict_json.setdefault("caveats", [])
            if not verdict_json["caveats"]:
                verdict_json["caveats"] = [
                    "The available documents only partially cover this question."
                ]

        # ── Compose ──
        action = verdict_json.get("final_action", "approve_with_caveats")
        if action in ("rewrite_required", "refuse"):
            _report("rewriting", "Found a discrepancy — revising the answer to match the evidence...")
        final_answer, compose_used_llm = compose_final_answer(
            question, answer, verdict_json, entity_report)
        if compose_used_llm:
            llm_calls += 1
        result["answer"] = final_answer
        if action == "refuse" and (entity_report.get("unknown") or []):
            # A refusal built on "entity not found" must not carry citations
            # that suggest the ghost entity was sourced from real documents.
            result["sources"] = []

        score = float(verdict_json.get("evidence_sufficiency_score", 0.5))
        action_out = {"rewrite_required": "rewrite", "re_retrieval_required": "approve_with_caveats"}.get(action, action)
        verdict = TrustVerdict(
            risk=risk,
            action=action_out,
            sufficiency=score,
            sufficiency_label=_sufficiency_label(score, action_out),
            caveats=verdict_json.get("caveats") or [],
            analyst_review_required=(score < 0.7 or action_out in ("rewrite", "refuse")),
            unknown_entities=entity_report.get("unknown") or [],
            re_retrieved=re_retrieved,
            llm_calls=llm_calls,
        )
        if verdict.action == "approve":
            _report("verified", "Good — everything checks out. Here's the verified answer.")
        else:
            _report("verified", "Done — I've added notes where the evidence is thin.")
        logger.info(
            f"[TrustGuard] risk={risk} action={verdict.action} "
            f"sufficiency={score:.2f} re_retrieved={re_retrieved}"
        )
        return verdict
    except Exception as e:
        logger.warning(f"[TrustGuard] failed open: {e}")
        return TrustVerdict(risk=risk, skipped=True, sufficiency_label="unverified",
                            sufficiency=0.0, skipped_reason="error",
                            llm_calls=llm_calls)


# ── 7. Result-level wrapper (single choke point for ALL answer paths) ──

def run_trust_guard_on_result(
    router: Any,
    query: str,
    raw_result: Dict[str, Any],
    doc_ids: Optional[List[str]] = None,
    email_ids: Optional[List[str]] = None,
) -> TrustVerdict:
    """Guard entry point called from the chat orchestrator AFTER routing.

    Every answer-producing path (document, agent, hybrid, timeline, dual,
    greeting, selected-context) flows through here; the guard itself decides
    to skip and says why (skipped_reason). Handles both the single-result
    shape (top-level answer/sources) and the dual shape ({"answers": {...}})
    by verifying the primary provider only. Fails open on any error.
    """
    def _skip(reason: str, risk: str = "low") -> TrustVerdict:
        return TrustVerdict(risk=risk, skipped=True, skipped_reason=reason,
                            sufficiency_label="unverified")

    try:
        from .config import ENABLE_TRUST_GUARD
        if not ENABLE_TRUST_GUARD:
            return _skip("disabled")
        if not isinstance(raw_result, dict):
            return _skip("empty_answer")
        if email_ids:
            # User pinned the exact evidence; substitution risk is minimal and
            # drafting latency matters.
            return _skip("selected_context")
        if raw_result.get("is_greeting"):
            return _skip("greeting")

        # Dual shape: verify the primary provider's answer only (dual is off in
        # production; a per-provider verify would double guard cost).
        target = raw_result
        if "answers" in raw_result and isinstance(raw_result.get("answers"), dict):
            answers = raw_result["answers"]
            primary = None
            try:
                from .config import LLM_PROVIDERS
                for p in LLM_PROVIDERS:
                    if isinstance(answers.get(p), dict):
                        primary = answers[p]
                        break
            except Exception:
                pass
            if primary is None:
                primary = next((v for v in answers.values() if isinstance(v, dict)), None)
            if primary is None:
                return _skip("empty_answer")
            # Give the guard a view that carries routing/query_type context.
            target = primary
            target.setdefault("query_type", raw_result.get("query_type"))
            target.setdefault("routing", raw_result.get("routing") or {})

        if target.get("query_type") not in GUARDED_QUERY_TYPES:
            return _skip("route_excluded")
        if not (target.get("answer") or "").strip():
            return _skip("empty_answer")

        verdict = run_trust_guard(router, query, target, doc_ids)
        if not verdict.skipped:
            # Surface at the top level for the response builder / interaction
            # log regardless of shape (dual mutations land on the provider
            # sub-dict; the verdict itself is shape-independent).
            raw_result["trust_guard"] = verdict.to_dict()
            raw_result["verify_verdict"] = verdict_to_verify_token(verdict)
        return verdict
    except Exception as e:
        logger.warning(f"[TrustGuard] wrapper failed open: {e}")
        return _skip("error")
