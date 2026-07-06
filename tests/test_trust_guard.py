"""Trust Guard unit tests — no network, no LLM.

Covers:
  * assess_risk keyword/proper-noun tiers + confidence bump
  * entity candidate extraction (proper nouns, quoted names, filenames)
  * fuzzy 'did you mean' recovery from evidence snippets
  * deterministic substitution override (the Morrison→Mott QA failure)
  * composer output per final_action (caveat block, refusal template)
  * run_trust_guard orchestration with a mocked verifier (result mutation,
    verify_verdict mapping, fail-open, route skip via router integration gate)
  * response_builder mapping of raw["trust_guard"] → ChatResponse.trust_guard

The 3 QA failure patterns (false premise, fake entity, ghost attribution) are
exercised as EVAL_CASES against the deterministic layers.
"""

from unittest.mock import patch

import pytest

from src import trust_guard as tg
from src.trust_guard import (
    TrustVerdict,
    apply_substitution_override,
    assess_risk,
    build_reretrieval_query,
    compose_final_answer,
    extract_entity_candidates,
    run_trust_guard,
    verdict_to_verify_token,
    _fuzzy_similar_from_chunks,
    _sufficiency_label,
)
from backend.services.response_builder import build_chat_response


# ── assess_risk ──────────────────────────────────────────────
class TestAssessRisk:
    @pytest.mark.parametrize("q", [
        "who is responsible for the tram delay?",
        "is the contractor liable for the blockwork delay?",
        "does the employer owe an extension of time?",
        "was the EOT claim time-barred?",
        "kim sorumlu bu gecikmeden?",
        "what compensation is due for the disruption?",
    ])
    def test_high_risk(self, q):
        assert assess_risk(q) == "high"

    @pytest.mark.parametrize("q", [
        "what caused the delay to the on-street works?",
        "show the chronology of design changes",
        "when did the council issue the notice?",
        "what did Morrison MacDonald's report conclude?",  # proper noun only
        'summarise the "Interim Review" letter',            # quoted name
        "what does audit_report.pdf say about utilities?",  # filename
    ])
    def test_medium_risk(self, q):
        assert assess_risk(q) == "medium"

    @pytest.mark.parametrize("q", [
        "hello",
        "list the drawings",
        "what is a tram?",
        "",
    ])
    def test_low_risk(self, q):
        assert assess_risk(q) == "low"

    def test_low_confidence_bumps_medium_to_high(self):
        q = "what caused the delay to the on-street works?"
        assert assess_risk(q, routing_confidence=0.5) == "high"
        assert assess_risk(q, routing_confidence=0.9) == "medium"

    def test_low_confidence_does_not_bump_low(self):
        assert assess_risk("hello", routing_confidence=0.3) == "low"


# ── entity extraction ────────────────────────────────────────
class TestEntityExtraction:
    def test_proper_noun_bigram(self):
        cands = extract_entity_candidates("What did Morrison MacDonald conclude?")
        assert {"name": "Morrison MacDonald", "kind": "name"} in cands

    def test_quoted_name(self):
        cands = extract_entity_candidates('summarise the "Interim Review Report"')
        assert any(c["name"] == "Interim Review Report" for c in cands)

    def test_filename(self):
        cands = extract_entity_candidates("what does audit_report.pdf say?")
        assert {"name": "audit_report.pdf", "kind": "document"} in cands

    def test_question_lead_words_not_entities(self):
        # "What Did" must not be extracted as an entity
        cands = extract_entity_candidates("What Did the council decide?")
        assert not any(c["name"].lower().startswith("what") for c in cands)

    def test_cap(self):
        q = " ".join(f"Alpha Bravo{i}" for i in range(10))
        assert len(extract_entity_candidates(q)) <= 5

    def test_fuzzy_recovery_morrison_to_mott(self):
        chunks = [{"text": "The report by Mott MacDonald reviewed the utilities diversion."}]
        similar = _fuzzy_similar_from_chunks("Morrison MacDonald", chunks)
        assert "Mott MacDonald" in similar


# ── substitution override (fake-entity QA failure) ───────────
class TestSubstitutionOverride:
    def _verdict(self, action="approve", score=0.9):
        return {"claims": [], "evidence_sufficiency_score": score,
                "final_action": action, "safe_answer_instructions": "", "caveats": []}

    def test_silent_substitution_forces_caveat(self):
        entity_report = {"known": [], "unknown": [
            {"name": "Morrison MacDonald", "kind": "name", "similar": ["Mott MacDonald"]},
        ]}
        answer = "Mott MacDonald's report concluded the diversion works were late."
        out = apply_substitution_override(self._verdict(), entity_report, answer)
        assert out["final_action"] == "approve_with_caveats"
        assert any("Morrison MacDonald" in c and "Mott MacDonald" in c for c in out["caveats"])
        assert out["evidence_sufficiency_score"] <= 0.69

    def test_no_unknowns_is_passthrough(self):
        v = self._verdict()
        assert apply_substitution_override(v, {"known": ["Siemens"], "unknown": []}, "x") is v

    def test_acknowledged_missing_entity_not_forced(self):
        entity_report = {"known": [], "unknown": [
            {"name": "Dr Alan Prentice", "kind": "name", "similar": []},
        ]}
        answer = "Dr Alan Prentice was not found in the documents; no audit by that name exists."
        out = apply_substitution_override(self._verdict(), entity_report, answer)
        assert out["final_action"] == "approve"  # unchanged

    def test_ghost_entity_without_similar(self):
        entity_report = {"known": [], "unknown": [
            {"name": "Dr Alan Prentice", "kind": "name", "similar": []},
        ]}
        answer = "The audit found significant procurement failures."  # ghost attribution
        out = apply_substitution_override(self._verdict(), entity_report, answer)
        assert out["final_action"] == "approve_with_caveats"
        assert any("Dr Alan Prentice" in c for c in out["caveats"])

    def test_rewrite_action_not_downgraded(self):
        entity_report = {"known": [], "unknown": [
            {"name": "Morrison MacDonald", "kind": "name", "similar": ["Mott MacDonald"]},
        ]}
        out = apply_substitution_override(
            self._verdict("rewrite_required"), entity_report, "Mott MacDonald said...")
        assert out["final_action"] == "rewrite_required"  # stricter action kept


# ── composer ─────────────────────────────────────────────────
class TestComposer:
    def test_approve_passthrough(self):
        v = {"final_action": "approve", "caveats": [], "claims": []}
        out, used_llm = compose_final_answer("q", "the answer", v, {"unknown": []})
        assert out == "the answer"
        assert used_llm is False

    def test_caveats_appended_deterministically(self):
        v = {"final_action": "approve_with_caveats",
             "caveats": ["No notice document was found for June 2008."], "claims": []}
        out, used_llm = compose_final_answer("q", "the answer", v, {"unknown": []})
        assert out.startswith("the answer")
        assert "Verification notes" in out
        assert "No notice document was found for June 2008." in out
        assert used_llm is False

    def test_refuse_with_unknown_entity_uses_template(self):
        v = {"final_action": "refuse", "caveats": [], "claims": []}
        er = {"unknown": [{"name": "Morrison MacDonald", "kind": "name",
                           "similar": ["Mott MacDonald"]}]}
        out, used_llm = compose_final_answer("q", "draft", v, er)
        assert "Morrison MacDonald" in out and "Mott MacDonald" in out
        assert "Did you mean" in out
        assert used_llm is False

    def test_exhausted_reretrieval_gets_default_caveat(self):
        v = {"final_action": "re_retrieval_required", "caveats": [], "claims": []}
        out, used_llm = compose_final_answer("q", "the answer", v, {"unknown": []})
        assert "Verification notes" in out
        assert used_llm is False

    def test_sufficiency_labels(self):
        assert _sufficiency_label(0.9, "approve") == "verified"
        assert _sufficiency_label(0.6, "approve_with_caveats") == "partially_supported"
        assert _sufficiency_label(0.3, "rewrite") == "insufficient"
        assert _sufficiency_label(0.9, "refuse") == "insufficient"


# ── verdict mapping ──────────────────────────────────────────
class TestVerdictMapping:
    def test_tokens(self):
        assert verdict_to_verify_token(TrustVerdict(action="approve")) == "OK"
        assert verdict_to_verify_token(TrustVerdict(action="refuse")) == "OFFTOPIC"
        assert verdict_to_verify_token(TrustVerdict(action="approve_with_caveats")) == "WEAK"
        assert verdict_to_verify_token(TrustVerdict(action="rewrite")) == "WEAK"


# ── run_trust_guard orchestration (mocked verifier) ──────────
SOURCES = [
    {"file_name": "audit.pdf", "page_number": 3, "text": "The utilities diversion was delayed.",
     "score": 0.8, "doc_id": "d1"},
]


def _result(answer="The delay was caused by utility diversions.", qt="document"):
    return {"answer": answer, "sources": list(SOURCES), "query_type": qt,
            "routing": {"confidence": 0.9}}


class TestRunTrustGuard:
    def test_low_risk_skips(self):
        verdict = run_trust_guard(None, "hello there", _result())
        assert verdict.skipped is True
        assert verdict.skipped_reason == "risk_below_threshold"

    def test_approve_flow(self):
        canned = {"claims": [{"text": "delay caused by utilities", "status": "supported",
                              "evidence": "E1"}],
                  "evidence_sufficiency_score": 0.92, "final_action": "approve",
                  "safe_answer_instructions": "", "caveats": []}
        result = _result()
        with patch.object(tg, "verify_claims", return_value=dict(canned)), \
             patch.object(tg, "check_entities", return_value={"known": [], "unknown": []}):
            verdict = run_trust_guard(None, "what caused the delay to the tram works?", result)
        assert verdict.skipped is False
        assert verdict.action == "approve"
        assert verdict.sufficiency_label == "verified"
        assert verdict.analyst_review_required is False
        assert result["answer"] == "The delay was caused by utility diversions."
        assert verdict_to_verify_token(verdict) == "OK"
        assert verdict.llm_calls == 1  # one verifier call, no composer LLM

    def test_caveat_flow_mutates_answer(self):
        canned = {"claims": [], "evidence_sufficiency_score": 0.6,
                  "final_action": "approve_with_caveats",
                  "safe_answer_instructions": "", "caveats": ["Evidence is partial."]}
        result = _result()
        with patch.object(tg, "verify_claims", return_value=dict(canned)), \
             patch.object(tg, "check_entities", return_value={"known": [], "unknown": []}):
            verdict = run_trust_guard(None, "what caused the delay to the tram works?", result)
        assert verdict.action == "approve_with_caveats"
        assert "Verification notes" in result["answer"]
        assert verdict.analyst_review_required is True  # score < 0.7

    def test_refuse_ghost_entity_drops_sources(self):
        canned = {"claims": [], "evidence_sufficiency_score": 0.1, "final_action": "refuse",
                  "safe_answer_instructions": "", "caveats": []}
        result = _result(answer="The audit by Dr Alan Prentice found failures.")
        er = {"known": [], "unknown": [{"name": "Dr Alan Prentice", "kind": "name",
                                        "similar": []}]}
        with patch.object(tg, "verify_claims", return_value=dict(canned)), \
             patch.object(tg, "check_entities", return_value=er):
            verdict = run_trust_guard(
                None, "Summarise Dr Alan Prentice's audit findings", result)
        assert verdict.action == "refuse"
        assert result["sources"] == []
        assert "Dr Alan Prentice" in result["answer"]
        assert "could not find" in result["answer"].lower()

    def test_fail_open_on_verifier_error(self):
        result = _result()
        with patch.object(tg, "verify_claims", side_effect=RuntimeError("boom")), \
             patch.object(tg, "check_entities", return_value={"known": [], "unknown": []}):
            verdict = run_trust_guard(None, "what caused the delay to the tram works?", result)
        assert verdict.skipped is True
        assert verdict.skipped_reason == "error"
        assert verdict.sufficiency_label == "unverified"
        assert result["answer"] == "The delay was caused by utility diversions."

    def test_empty_answer_skips(self):
        verdict = run_trust_guard(None, "who is liable for the delay?", _result(answer=""))
        assert verdict.skipped is True
        assert verdict.skipped_reason == "empty_answer"

    def test_empty_response_placeholder_skips(self):
        # LlamaIndex's literal "Empty Response" placeholder must not be verified.
        verdict = run_trust_guard(None, "who is liable for the delay?",
                                  _result(answer="Empty Response"))
        assert verdict.skipped is True
        assert verdict.skipped_reason == "empty_answer"

    def test_reretrieval_query_includes_similar_entities(self):
        er = {"known": ["Siemens"], "unknown": [
            {"name": "Morrison MacDonald", "kind": "name", "similar": ["Mott MacDonald"]},
        ]}
        q = build_reretrieval_query("what did the report conclude?", er)
        assert '"Siemens"' in q and '"Mott MacDonald"' in q


# ── the 3 QA failure patterns, end-to-end through the deterministic layers ──
class TestEvalCases:
    def test_false_premise_rewrite(self):
        # "Why did Siemens admit liability?" — evidence has no admission → the
        # (mocked) verifier says rewrite; composer calls the lite model, which
        # we stub to a corrected answer.
        canned = {"claims": [
                      {"text": "Siemens admitted liability", "status": "unsupported",
                       "evidence": ""}],
                  "evidence_sufficiency_score": 0.3, "final_action": "rewrite_required",
                  "safe_answer_instructions": "Challenge the premise.",
                  "caveats": ["No document records an admission of liability by Siemens."]}
        result = _result(answer="Siemens admitted liability in 2009 for the delay.")

        class FakeResp:
            text = ("The provided documents do not record any admission of "
                    "liability by Siemens.")
            usage = None

        with patch.object(tg, "verify_claims", return_value=dict(canned)), \
             patch.object(tg, "check_entities",
                          return_value={"known": ["Siemens"], "unknown": []}), \
             patch("src.llm_client.generate_text", return_value=FakeResp()):
            verdict = run_trust_guard(
                None, "Why did Siemens admit liability for the 2009 delay?", result)
        assert verdict.action == "rewrite"
        assert "do not record" in result["answer"]
        assert "No document records an admission" in result["answer"]
        assert verdict.analyst_review_required is True

    def test_fake_entity_zero_llm_override(self):
        # Verifier naively approves; the deterministic override still catches
        # the silent Morrison→Mott substitution.
        canned = {"claims": [], "evidence_sufficiency_score": 0.9,
                  "final_action": "approve", "safe_answer_instructions": "", "caveats": []}
        er = {"known": [], "unknown": [
            {"name": "Morrison MacDonald", "kind": "name", "similar": ["Mott MacDonald"]},
        ]}
        result = _result(answer="Mott MacDonald's report concluded the works were delayed.")
        with patch.object(tg, "verify_claims", return_value=dict(canned)), \
             patch.object(tg, "check_entities", return_value=er):
            verdict = run_trust_guard(
                None, "What did Morrison MacDonald's report conclude?", result)
        assert verdict.action == "approve_with_caveats"
        assert any("Morrison MacDonald" in c for c in verdict.caveats)
        assert "Morrison MacDonald" in result["answer"]  # caveat names the fake entity

    def test_ghost_attribution_refused(self):
        # covered by TestRunTrustGuard.test_refuse_ghost_entity_drops_sources;
        # here assert the response contract end-to-end.
        raw = _result(answer="I could not find Dr Alan Prentice in the indexed documents.")
        raw["trust_guard"] = TrustVerdict(
            risk="medium", action="refuse", sufficiency=0.1,
            sufficiency_label="insufficient",
            caveats=["'Dr Alan Prentice' was not found in the indexed documents."],
            analyst_review_required=True,
            unknown_entities=[{"name": "Dr Alan Prentice", "kind": "name", "similar": []}],
        ).to_dict()
        raw["sources"] = []
        resp = build_chat_response(raw)
        assert resp.trust_guard is not None
        assert resp.trust_guard.sufficiency_label == "insufficient"
        assert resp.trust_guard.analyst_review_required is True
        assert resp.citations == []


# ── response_builder mapping ─────────────────────────────────
class TestResponseBuilderMapping:
    def test_absent_trust_guard_is_none(self):
        resp = build_chat_response(_result())
        assert resp.trust_guard is None

    def test_skipped_trust_guard_is_none(self):
        raw = _result()
        raw["trust_guard"] = TrustVerdict(skipped=True).to_dict()
        assert build_chat_response(raw).trust_guard is None

    def test_verdict_mapped(self):
        raw = _result()
        raw["trust_guard"] = TrustVerdict(
            risk="high", action="approve_with_caveats", sufficiency=0.62,
            sufficiency_label="partially_supported",
            caveats=["Evidence is partial."], analyst_review_required=True,
        ).to_dict()
        resp = build_chat_response(raw)
        assert resp.trust_guard is not None
        assert resp.trust_guard.action == "approve_with_caveats"
        assert resp.trust_guard.sufficiency == pytest.approx(0.62)
        assert resp.trust_guard.caveats == ["Evidence is partial."]


# ── run_trust_guard_on_result wrapper (orchestrator choke point) ────────────
class TestWrapper:
    APPROVE = {"claims": [], "evidence_sufficiency_score": 0.9,
               "final_action": "approve", "safe_answer_instructions": "", "caveats": []}

    def _patched(self):
        return (patch.object(tg, "verify_claims", return_value=dict(self.APPROVE)),
                patch.object(tg, "check_entities",
                             return_value={"known": [], "unknown": []}))

    def test_disabled_flag(self, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "ENABLE_TRUST_GUARD", False)
        v = tg.run_trust_guard_on_result(None, "who is liable?", _result())
        assert v.skipped and v.skipped_reason == "disabled"

    def test_selected_context_skips(self):
        v = tg.run_trust_guard_on_result(
            None, "who is liable?", _result(), email_ids=["e1"])
        assert v.skipped and v.skipped_reason == "selected_context"

    def test_greeting_skips(self):
        raw = {"answer": "Welcome to COAir...", "query_type": "document",
               "sources": [], "is_greeting": True}
        v = tg.run_trust_guard_on_result(None, "hello", raw)
        assert v.skipped and v.skipped_reason == "greeting"
        assert "trust_guard" not in raw

    def test_data_route_excluded(self):
        v = tg.run_trust_guard_on_result(None, "who is liable?", _result(qt="data"))
        assert v.skipped and v.skipped_reason == "route_excluded"

    def test_agent_hybrid_result_guarded(self):
        # ReAct agent results have query_type "hybrid" — previously bypassed.
        raw = _result(qt="hybrid")
        raw["routing"] = {"decision": "agent", "route": "AGENT", "confidence": 0.9}
        p1, p2 = self._patched()
        with p1, p2:
            v = tg.run_trust_guard_on_result(None, "who is responsible for the delay?", raw)
        assert not v.skipped
        assert raw["trust_guard"]["action"] == "approve"
        assert raw["verify_verdict"] == "OK"

    def test_dual_shape_primary_provider_only(self):
        raw = {
            "query_type": "document",
            "routing": {"confidence": 0.9},
            "answers": {
                "gemini": {"answer": "The delay was caused by utility diversions.",
                           "sources": list(SOURCES)},
                "openai": {"answer": "Different answer.", "sources": []},
            },
        }
        p1, p2 = self._patched()
        with p1, p2:
            v = tg.run_trust_guard_on_result(None, "who is responsible for the delay?", raw)
        assert not v.skipped
        assert raw["trust_guard"]["action"] == "approve"  # top-level surface
        assert raw["answers"]["openai"]["answer"] == "Different answer."  # untouched

    def test_empty_answer_skips(self):
        v = tg.run_trust_guard_on_result(None, "who is liable?", _result(answer=""))
        assert v.skipped and v.skipped_reason == "empty_answer"

    def test_wrapper_fails_open(self):
        with patch.object(tg, "run_trust_guard", side_effect=RuntimeError("boom")):
            v = tg.run_trust_guard_on_result(
                None, "who is responsible for the delay?", _result())
        assert v.skipped and v.skipped_reason == "error"


# ── entity registry ──────────────────────────────────────────
@pytest.fixture
def entity_registry(tmp_path, monkeypatch):
    import src.entity_registry as er
    monkeypatch.setattr(er, "ENTITIES_DIR", tmp_path)
    monkeypatch.setattr(er, "ENTITIES_DB", tmp_path / "entities.db")
    er.EntityRegistry._instance = None
    er._instance = None
    reg = er.get_entity_registry()
    yield reg
    er.EntityRegistry._instance = None
    er._instance = None


class TestEntityRegistry:
    def test_upsert_and_find(self, entity_registry):
        entity_registry.upsert("Mott MacDonald", "org", "edinburgh", "d1",
                               confidence=0.8, ts="2026-07-06")
        hit = entity_registry.find("mott macdonald", "edinburgh")
        assert hit and hit["canonical_name"] == "Mott MacDonald"
        assert hit["doc_count"] == 1

    def test_alias_match(self, entity_registry):
        entity_registry.upsert("Mott MacDonald", "org", "edinburgh", "d1",
                               aliases=["Mott Macdonald Ltd"], ts="t")
        hit = entity_registry.find("Mott Macdonald Ltd", "edinburgh")
        assert hit and hit["canonical_name"] == "Mott MacDonald"

    def test_similar_morrison_to_mott(self, entity_registry):
        entity_registry.upsert("Mott MacDonald", "org", "edinburgh", "d1", ts="t")
        assert "Mott MacDonald" in entity_registry.similar(
            "Morrison MacDonald", "edinburgh", cutoff=75)

    def test_corpus_isolation(self, entity_registry):
        entity_registry.upsert("Mott MacDonald", "org", "edinburgh", "d1", ts="t")
        assert entity_registry.find("Mott MacDonald", "demo") is None
        assert entity_registry.count("edinburgh") == 1
        assert entity_registry.count("demo") == 0

    def test_doc_count_merges(self, entity_registry):
        for d in ("d1", "d2", "d1"):
            entity_registry.upsert("Siemens plc", "org", "demo", d, ts="t")
        hit = entity_registry.find("Siemens plc", "demo")
        assert hit["doc_count"] == 2  # d1 counted once

    def test_ingest_from_notice(self, entity_registry):
        entity_registry.ingest_from_notice(
            "d9", "letter_042.pdf",
            {"sender": "Tie Limited", "recipient": "Bilfinger Berger",
             "cc_list": ["City of Edinburgh Council"],
             "subject": "Delayed Blockwork at Princes Street"},
            corpus="demo", ts="t")
        assert entity_registry.find("Tie Limited", "demo")
        assert entity_registry.find("Bilfinger Berger", "demo")
        assert entity_registry.find("letter_042.pdf", "demo")
        assert entity_registry.find("Princes Street", "demo")

    def test_check_entities_registry_first(self, entity_registry):
        # Registry has entities for the corpus → FTS is never touched.
        entity_registry.upsert("Mott MacDonald", "org", "demo", "d1", ts="t")
        with patch("src.lexical_index.get_lexical_index",
                   side_effect=AssertionError("FTS must not be called")):
            report = tg.check_entities("What did Morrison MacDonald conclude?", None)
        unk = report["unknown"]
        assert len(unk) == 1 and unk[0]["name"] == "Morrison MacDonald"
        assert "Mott MacDonald" in unk[0]["similar"]

    def test_check_entities_known_via_registry(self, entity_registry):
        entity_registry.upsert("Mott MacDonald", "org", "demo", "d1", ts="t")
        report = tg.check_entities("What did Mott MacDonald conclude?", None)
        assert "Mott MacDonald" in report["known"]


# ── trust guard telemetry (interaction_log) ──────────────────
@pytest.fixture
def ilog(tmp_path, monkeypatch):
    import src.interaction_log as il
    monkeypatch.setattr(il, "INTERACTIONS_DIR", tmp_path)
    monkeypatch.setattr(il, "INTERACTIONS_DB", tmp_path / "interactions.db")
    il.InteractionLog._instance = None
    il._instance = None
    log = il.get_interaction_log()
    yield log
    il.InteractionLog._instance = None
    il._instance = None


class TestTrustGuardTelemetry:
    def _log_run(self, log, i, skipped=False, action="approve", risk="medium",
                 unknown=0, re_retrieved=False, latency=1500.0):
        log.log_trust_guard_run(
            run_id=f"r{i}", username="u", query=f"q{i}", route="document",
            risk=risk, routing_confidence=0.9,
            action=action if not skipped else "",
            sufficiency=0.9, unknown_entities=unknown, re_retrieved=re_retrieved,
            llm_calls=1, latency_ms=latency, skipped=skipped,
            skipped_reason="risk_below_threshold" if skipped else "",
            ts="2099-01-01T00:00:00",
        )

    def test_stats_aggregation(self, ilog):
        self._log_run(ilog, 1, action="approve")
        self._log_run(ilog, 2, action="approve_with_caveats", unknown=1)
        self._log_run(ilog, 3, action="rewrite", re_retrieved=True)
        self._log_run(ilog, 4, skipped=True, latency=0.5)
        stats = ilog.trust_guard_stats(days=365 * 100)
        assert stats["total_runs"] == 4
        assert stats["guarded"] == 3
        assert stats["skipped"] == 1
        assert stats["coverage_pct"] == 75.0
        assert stats["actions"]["approve"] == 1
        assert stats["skip_reasons"]["risk_below_threshold"] == 1
        assert stats["catches"]["unknown_entity_runs"] == 1
        assert stats["catches"]["re_retrievals"] == 1
        assert stats["catches"]["rewrites_or_refusals"] == 1
        assert stats["avg_latency_ms"] == pytest.approx(1500.0)

    def test_recent_runs(self, ilog):
        self._log_run(ilog, 1)
        recent = ilog.trust_guard_recent(limit=10)
        assert len(recent) == 1
        assert recent[0]["query"] == "q1"
        assert recent[0]["skipped"] is False

    def test_duplicate_run_id_ignored(self, ilog):
        self._log_run(ilog, 1)
        self._log_run(ilog, 1)
        assert ilog.trust_guard_stats(days=365 * 100)["total_runs"] == 1

    def test_empty_stats(self, ilog):
        stats = ilog.trust_guard_stats()
        assert stats["total_runs"] == 0
        assert stats["coverage_pct"] == 0.0
