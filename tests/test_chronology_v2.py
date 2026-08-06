from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.tasks.report_jobs import ReportJobStore
from src import llm_client
from src.chronology_v2 import (
    PIPELINE_VERSION, ExtractionModel, PreparedChronologyQuery, _claims_are_source_valid,
    _prune_source_invalid_claims, _prune_source_invalid_events, coverage_matrix,
    evidence_batches, evidence_markdown, extract_batches,
    prepare_chronology_query, source_preview,
)
from src.chronology_prompts import load_chronology_prompts
from src.evidence_model import EvidenceItem
from src.model_profiles import MODEL_CAPABILITIES, TASK_PROFILES


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, expire=None):
        self.values[key] = value

    def delete(self, key):
        return self.values.pop(key, None) is not None

    def iterkeys(self):
        return iter(self.values)


def _provider_response(reason="STOP"):
    return SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=reason))],
        raw=True,
    )


def test_task_profiles_fit_gemini_hard_limits():
    hard = MODEL_CAPABILITIES["gemini-3.6-flash"]
    assert hard.input_tokens == 1_048_576
    assert hard.output_tokens == 65_536
    assert TASK_PROFILES["chronology_synthesis"].max_output_tokens == 32_768
    for profile in TASK_PROFILES.values():
        assert profile.max_input_tokens <= hard.input_tokens
        assert profile.max_output_tokens <= hard.output_tokens
        assert profile.provider_retries == 3


def test_invalid_structured_output_is_not_cached(monkeypatch):
    cache = MemoryCache(); monkeypatch.setattr(llm_client, "_cache", cache)
    monkeypatch.setattr(llm_client.time, "sleep", lambda _: None)
    answers = iter(("{\"entries\":[", '{"entries":[]}'))

    def native(**kwargs):
        return next(answers), 10, 5, 0, 0, _provider_response()

    monkeypatch.setattr(llm_client, "_gemini_generate_native", native)
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"entries": {"type": "array", "items": {"type": "object"}}},
        "required": ["entries"],
    }
    response = llm_client.generate_response_json(
        "prompt", system="system", schema=schema, schema_name="x",
        task_type="chronology_extract", cache_key="chronology-extract",
    )
    assert response.raw == {"entries": []}
    assert len(cache.values) == 1
    assert next(iter(cache.values.values())) == '{"entries":[]}'


def test_max_tokens_is_never_cached(monkeypatch):
    cache = MemoryCache(); monkeypatch.setattr(llm_client, "_cache", cache)
    monkeypatch.setattr(llm_client, "_gemini_generate_native", lambda **kwargs: (
        '{"entries":[', 10, 5, 3, 0, _provider_response("MAX_TOKENS")
    ))
    with pytest.raises(llm_client.LLMIncompleteResponseError):
        llm_client.generate_text(
            "prompt", system="system", model="gemini-3.6-flash",
            provider="gemini", task_type="chronology_extract",
        )
    assert cache.values == {}


def test_visible_output_and_thinking_tokens_are_recorded_separately(monkeypatch):
    monkeypatch.setattr(llm_client, "_cache", MemoryCache())
    monkeypatch.setattr(llm_client, "_gemini_generate_native", lambda **kwargs: (
        "complete", 10, 5, 3, 2, _provider_response()
    ))
    response = llm_client.generate_text(
        "prompt", system="system", task_type="chronology_synthesis", ttl_s=0,
    )
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 5
    assert response.usage.reasoning_tokens == 3
    assert response.usage.cached_tokens == 2
    assert response.usage.total_tokens == 18


def test_prompt_change_changes_cache_key(monkeypatch):
    cache = MemoryCache(); monkeypatch.setattr(llm_client, "_cache", cache)
    calls = []

    def native(**kwargs):
        calls.append(kwargs["prompt"])
        return '{"ok":true}', 4, 2, 0, 0, _provider_response()

    monkeypatch.setattr(llm_client, "_gemini_generate_native", native)
    for version in ("v1", "v2", "v2"):
        llm_client.generate_json(
            "same", system="system", model="gemini-3.6-flash",
            task_type="generation", cache_key="chron-plan", prompt_version=version,
        )
    assert calls == ["same", "same"]
    assert len(cache.values) == 2


def test_semantically_invalid_structured_output_is_not_cached(monkeypatch):
    cache = MemoryCache(); monkeypatch.setattr(llm_client, "_cache", cache)
    monkeypatch.setattr(llm_client.time, "sleep", lambda _: None)
    answers = iter(('{"value":"invented"}', '{"value":"supported"}'))
    monkeypatch.setattr(llm_client, "_gemini_generate_native", lambda **kwargs: (
        next(answers), 4, 2, 0, 0, _provider_response()
    ))
    schema = {
        "type": "object", "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    response = llm_client.generate_response_json(
        "prompt", system="system", schema=schema, schema_name="semantic",
        task_type="chronology_verify", cache_key="chronology-verification",
        semantic_validator=lambda value: value["value"] == "supported",
    )
    assert response.raw == {"value": "supported"}
    assert list(cache.values.values()) == ['{"value":"supported"}']


def test_chronology_has_no_artificial_call_cap_and_never_degrades(monkeypatch):
    cache = MemoryCache(); monkeypatch.setattr(llm_client, "_cache", cache)
    models = []
    monkeypatch.setattr(llm_client, "_gemini_generate_native", lambda **kwargs: (
        models.append(kwargs["model"]) or '{"ok":true}', 4, 2, 0, 0, _provider_response()
    ))
    llm_client.begin_chronology_call_budget(2)
    try:
        for index in range(3):
            llm_client.generate_json(
                f"prompt {index}", system="system", task_type="chronology_extract",
                cache_key="chronology-extract", ttl_s=0,
            )
    finally:
        llm_client.end_chronology_call_budget()
    assert models == ["gemini-3.6-flash"] * 3


def test_claim_semantics_reject_unknown_sources_numbers_and_quotes():
    evidence = [EvidenceItem(
        "s1", "d1", "notice.pdf", page=4,
        excerpt='On 12 March 2025 the Contractor stated "access was unavailable".',
    )]
    valid = {"entries": [{"claims": [{
        "text": 'On 12 March 2025 the Contractor stated "access was unavailable".',
        "source_ids": ["s1"],
    }]}]}
    assert _claims_are_source_valid(valid, evidence)
    invalid_number = json.loads(json.dumps(valid).replace("2025", "2026"))
    invalid_source = json.loads(json.dumps(valid)); invalid_source["entries"][0]["claims"][0]["source_ids"] = ["missing"]
    assert not _claims_are_source_valid(invalid_number, evidence)
    assert not _claims_are_source_valid(invalid_source, evidence)


def test_prompt_contract_guards_construction_chronology_risks():
    prompts = load_chronology_prompts()
    system = prompts["system"].casefold()
    verifier = prompts["verifier"].casefold()
    assert "untrusted" in system
    assert "document's date from an event date" in system
    assert "critical-path" in system
    assert "professional english" in system
    assert "unattributed party positions" in verifier


def test_prepare_query_falls_back_and_expands_jargon(monkeypatch):
    monkeypatch.setattr(
        llm_client, "generate_response_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()),
    )
    prepared = prepare_chronology_query("MUDFA delay", project_id="p")
    assert prepared.original_query == "MUDFA delay"
    assert len(prepared.research_queries) >= 8
    assert any(term == "MUDFA" for term, _ in prepared.jargon_matches)


def test_markdown_batches_preserve_source_boundaries():
    evidence = [EvidenceItem(
        source_id=f"src{i}", doc_id="doc", file_name="contract.pdf", page=i,
        excerpt=("source text " * 800),
    ) for i in range(1, 4)]
    batches = evidence_batches(evidence, max_chars=12_000)
    assert len(batches) == 3
    markdown = evidence_markdown(evidence)
    assert "# Document: contract.pdf" in markdown
    assert "## Page 2" in markdown
    assert "[source_id=src3]" in markdown


def test_source_preview_aggregates_documents_and_reports_coverage():
    prepared = PreparedChronologyQuery(
        "delay", "delay", (), (), (), (), (), ("q",),
    )
    evidence = [
        EvidenceItem("s1", "d1", "a.pdf", page=1,
                     excerpt="contract programme notice delay dispute", score=.9),
        EvidenceItem("s2", "d1", "a.pdf", page=2,
                     excerpt="design access change mediation", score=.8),
        EvidenceItem("s3", "d2", "b.pdf", page=1,
                     excerpt="party asserted inconsistent missing record", score=.4),
    ]
    result = source_preview("p", prepared, lambda project, questions: evidence)
    assert result["documents"][0]["doc_id"] == "d1"
    assert result["documents"][0]["source_count"] == 2
    assert set(result["coverage"]) == set(coverage_matrix(evidence))


def test_extraction_checkpoint_is_reused(monkeypatch):
    evidence = [EvidenceItem("s1", "d", "a.pdf", page=1, excerpt="event")]
    prepared = PreparedChronologyQuery("q", "q", (), (), (), (), (), ("q",))
    saved = {}

    def load(key, input_hash):
        return saved.get((key, input_hash))

    def save(key, input_hash, status, output, error):
        saved[(key, input_hash)] = {"status": status, "output": output}

    calls = []
    monkeypatch.setattr("src.chronology_v2.extract_batch", lambda **kwargs: (
        calls.append(1) or [{"event_date": "2025-01-01", "claims": []}]
    ))
    assert extract_batches(evidence, prepared, load_step=load, save_step=save)
    assert extract_batches(evidence, prepared, load_step=load, save_step=save)
    assert len(calls) == 1


def test_broken_extraction_batch_is_recursively_split(monkeypatch):
    evidence = [EvidenceItem(f"s{i}", "d", "a.pdf", page=i, excerpt="event") for i in range(4)]
    prepared = PreparedChronologyQuery("q", "q", (), (), (), (), (), ("q",))

    def extract(**kwargs):
        batch = kwargs["batch"]
        if len(batch) > 1:
            raise llm_client.LLMInvalidStructuredOutputError("model_output_invalid")
        return [{"event_date": f"2025-01-0{batch[0].page}", "claims": []}]

    monkeypatch.setattr("src.chronology_v2.extract_batch", extract)
    assert len(extract_batches(evidence, prepared)) == 4


def test_provider_configuration_error_does_not_trigger_batch_split(monkeypatch):
    evidence = [
        EvidenceItem(f"s{i}", "d", "a.pdf", page=i, excerpt="event")
        for i in range(4)
    ]
    prepared = PreparedChronologyQuery("q", "q", (), (), (), (), (), ("q",))
    calls = []

    def extract(**_kwargs):
        calls.append(1)
        raise RuntimeError("400 INVALID_ARGUMENT")

    monkeypatch.setattr("src.chronology_v2.extract_batch", extract)
    with pytest.raises(RuntimeError, match="INVALID_ARGUMENT"):
        extract_batches(evidence, prepared)
    assert len(calls) == 1


def test_nested_array_bounds_are_removed_only_from_provider_schema():
    schema = ExtractionModel.model_json_schema()
    provider_schema = llm_client._gemini_compatible_response_schema(schema)

    encoded_provider = json.dumps(provider_schema)
    encoded_validation = json.dumps(schema)
    assert "minItems" not in encoded_provider
    assert "maxItems" not in encoded_provider
    assert "minItems" in encoded_validation
    assert "maxItems" in encoded_validation


def test_synthesis_prunes_only_invalid_claims_before_independent_verification():
    evidence = [EvidenceItem(
        "s1", "d1", "notice.pdf", page=1,
        excerpt="On 14 March 2025 the Engineer issued Notice 17.",
    )]
    value = {
        "overview_claims": [{
            "text": "The Engineer issued Notice 17.", "source_ids": ["s1"],
        }],
        "entries": [{
            "event_date": "2025-03-14", "date_precision": "exact",
            "claims": [
                {"text": "The Engineer issued Notice 17.", "source_ids": ["s1"]},
                {"text": "The notice imposed a 99-day delay.", "source_ids": ["s1"]},
            ],
        }],
    }

    pruned = _prune_source_invalid_claims(value, evidence)

    assert len(pruned["overview_claims"]) == 1
    assert [claim["text"] for claim in pruned["entries"][0]["claims"]] == [
        "The Engineer issued Notice 17."
    ]


def test_extraction_prunes_invalid_claim_without_retrying_the_batch():
    evidence = [EvidenceItem(
        "s1", "d1", "notice.pdf", page=1,
        excerpt="On 14 March 2025 the Engineer issued Notice 17.",
    )]
    value = {"entries": [{
        "event_date": "2025-03-14", "date_precision": "exact",
        "claims": [
            {"text": "The Engineer issued Notice 17.", "source_ids": ["s1"]},
            {"text": "The notice imposed a 99-day delay.", "source_ids": ["s1"]},
        ],
    }]}

    entries = _prune_source_invalid_events(value, evidence)

    assert len(entries) == 1
    assert [claim["text"] for claim in entries[0]["claims"]] == [
        "The Engineer issued Notice 17."
    ]


def test_network_errors_receive_three_jittered_retries(monkeypatch):
    monkeypatch.setattr(llm_client, "_cache", MemoryCache())
    sleeps = []; calls = []
    monkeypatch.setattr(llm_client.time, "sleep", sleeps.append)

    def native(**kwargs):
        calls.append(1)
        if len(calls) <= 3:
            raise ConnectionError("network unavailable")
        return '{"ok":true}', 4, 2, 0, 0, _provider_response()

    monkeypatch.setattr(llm_client, "_gemini_generate_native", native)
    response = llm_client.generate_json(
        "retry", system="system", task_type="research_plan", ttl_s=0,
    )
    assert response.raw == {"ok": True}
    assert len(calls) == 4
    assert len(sleeps) == 3


def test_report_job_retry_preparation_and_steps(tmp_path: Path):
    store = ReportJobStore(tmp_path / "jobs.db")
    prep = store.create_preparation(
        project_id="p", username="u", request={"topic": "delay"},
        result={"documents": [], "prepared": {}},
    )
    assert store.get_preparation(prep["preparation_id"], "p", "u")
    assert store.get_preparation(prep["preparation_id"], "p", "other") is None
    job = store.enqueue(
        project_id="p", username="u", module="chronology", title="delay",
        request={"topic": "delay"},
    )
    store.save_step(job["job_id"], "extract:1", "hash", "ready", {"entries": []})
    store.fail(job["job_id"], "model_output_incomplete")
    retried = store.retry(job["job_id"], "p")
    assert retried and retried["job_id"] == job["job_id"]
    assert retried["sequence_number"] == job["sequence_number"]
    assert store.load_step(job["job_id"], "extract:1", "hash")["status"] == "ready"
    assert retried["pipeline_version"] == PIPELINE_VERSION


def test_auth_and_schema_provider_failures_are_not_retryable(tmp_path: Path):
    store = ReportJobStore(tmp_path / "jobs.db")
    for title, error in (
        ("auth", "Authentication failed: invalid API key"),
        ("schema", "invalid response schema"),
    ):
        job = store.enqueue(
            project_id="p", username="u", module="chronology", title=title,
            request={"topic": title},
        )
        store.fail(job["job_id"], error)
        failed = store.get(job["job_id"], "p")
        assert failed and failed["retryable"] is False
        assert store.retry(job["job_id"], "p") is None


def test_a_failing_half_does_not_discard_the_other_half(monkeypatch):
    """The split must try both halves.

    Production step tables never contained a key ending in "b": the first half's
    exception left the frame before the second half was attempted, so half the
    evidence was dropped without a trace whenever a batch had to be split.
    """
    evidence = [EvidenceItem(f"s{i}", "d", "a.pdf", page=i, excerpt="event") for i in range(4)]
    prepared = PreparedChronologyQuery("q", "q", (), (), (), (), (), ("q",))
    seen = []

    def extract(**kwargs):
        batch = kwargs["batch"]
        if len(batch) > 1:
            raise llm_client.LLMInvalidStructuredOutputError("model_output_invalid")
        seen.append(batch[0].page)
        if batch[0].page < 2:                      # the whole "a" side fails
            raise llm_client.LLMIncompleteResponseError("model_output_incomplete")
        return [{"event_date": f"2025-01-0{batch[0].page}", "claims": []}]

    monkeypatch.setattr("src.chronology_v2.extract_batch", extract)
    stats = {}
    entries = extract_batches(evidence, prepared, stats=stats)

    assert sorted(seen) == [0, 1, 2, 3], "the 'b' half was never attempted"
    assert len(entries) == 2, "surviving half must still be returned"
    assert stats["batches_failed"] == 2
    assert stats["passages_dropped"] == 2


def test_failed_batches_record_the_real_exception_not_a_constant(monkeypatch):
    """Three different failures used to be flattened to one label."""
    evidence = [EvidenceItem("s0", "d", "a.pdf", page=1, excerpt="event")]
    prepared = PreparedChronologyQuery("q", "q", (), (), (), (), (), ("q",))
    saved = {}

    def save(key, input_hash, status, output, error):
        saved[key] = (status, error)

    monkeypatch.setattr("src.chronology_v2.extract_batch", lambda **_k: (_ for _ in ()).throw(
        llm_client.LLMInvalidStructuredOutputError("entries: too many items")))
    stats = {}
    extract_batches(evidence, prepared, save_step=save, stats=stats)

    status, error = saved["extract:1"]
    assert status == "failed"
    assert "LLMInvalidStructuredOutputError" in error
    assert "too many items" in error
    assert error != "model_output_incomplete"


def test_systemic_errors_still_abort_and_are_not_counted_as_batch_failures(monkeypatch):
    evidence = [EvidenceItem(f"s{i}", "d", "a.pdf", page=i, excerpt="e") for i in range(4)]
    prepared = PreparedChronologyQuery("q", "q", (), (), (), (), (), ("q",))
    monkeypatch.setattr("src.chronology_v2.extract_batch", lambda **_k: (_ for _ in ()).throw(
        RuntimeError("403 PERMISSION_DENIED")))
    stats = {}
    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        extract_batches(evidence, prepared, stats=stats)
    assert stats["batches_failed"] == 0


def test_preview_groups_by_document_not_by_fragment():
    """A doc_id is a fragment: one file carries ~14 of them in production.

    Keying preview rows on doc_id showed the analyst fragments and called them
    documents, and let one file occupy every row.
    """
    prepared = PreparedChronologyQuery("delay", "delay", (), (), (), (), (), ("q",))
    evidence = [
        EvidenceItem(f"s{i}", f"fragment-{i}", "one-file.pdf", page=i,
                     excerpt="contract delay notice", score=0.9 - i / 100)
        for i in range(14)
    ] + [
        EvidenceItem("other", "d-other", "second-file.pdf", page=1,
                     excerpt="programme baseline milestone", score=0.5),
    ]
    result = source_preview("p", prepared, lambda project, questions: evidence)

    names = [row["file_name"] for row in result["documents"]]
    assert names == ["one-file.pdf", "second-file.pdf"]
    assert result["documents"][0]["source_count"] == 14
    assert len(result["documents"][0]["doc_ids"]) == 14


def test_preview_ranks_by_best_passage_not_by_how_much_matched():
    """Summing passage scores ranked documents by length, not by relevance."""
    prepared = PreparedChronologyQuery("delay", "delay", (), (), (), (), (), ("q",))
    verbose = [
        EvidenceItem(f"v{i}", f"dv{i}", "long-report.pdf", page=i,
                     excerpt="delay mentioned in passing", score=0.20)
        for i in range(30)                      # sum 6.0, best 0.20
    ]
    decisive = [
        EvidenceItem("k1", "dk1", "key-letter.pdf", page=1,
                     excerpt="notice of delay issued", score=0.98),
    ]
    result = source_preview("p", prepared, lambda project, questions: verbose + decisive)

    assert result["documents"][0]["file_name"] == "key-letter.pdf"


def test_preview_coverage_describes_the_pack_that_would_be_read():
    """Coverage used to be measured before selection, so it always said complete."""
    prepared = PreparedChronologyQuery("delay", "delay", (), (), (), (), (), ("q",))
    evidence = [
        EvidenceItem("s1", "d1", "a.pdf", page=1, excerpt="contract clause scope",
                     score=1.0),
    ]
    result = source_preview("p", prepared, lambda project, questions: evidence)

    assert result["coverage_status"] == "partial"
    assert result["selection"]["selected_passages"] == len(evidence)
