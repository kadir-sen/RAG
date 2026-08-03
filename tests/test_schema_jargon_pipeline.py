"""
Tests for the schema-aware + jargon-aware LLM pipeline:
  - SchemaContextBuilder
  - JargonManager bidirectional + concept group + custom term lifecycle
  - validate_columns_against_schema
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.catalog import CatalogEntry, TableCatalog, TableMetadata
from src.jargon_manager import JARGON_TERMS_FILE, JargonManager
from src.schema_context import (
    SchemaContextBuilder,
    analyze_schema_intent,
    get_schema_prompt_block,
    validate_columns_against_schema,
)


def _make_catalog(tables):
    cat = TableCatalog.__new__(TableCatalog)
    cat.entries = {}
    cat.catalog_path = None
    cat.parquet_dir = None
    entry = CatalogEntry(source_file="x.xlsx", source_type="excel", file_hash="hh")
    entry.tables = tables
    cat.entries["k"] = entry
    return cat


# ── SchemaContextBuilder ────────────────────────────────────────────


class TestSchemaContextBuilder:
    def test_returns_relevant_columns_for_known_query(self):
        cat = _make_catalog([
            TableMetadata(
                table_id="t1", source_file="x.xlsx", source_type="excel",
                table_name="manpower_production", parquet_path="",
                columns=["Block", "Floor", "Number of Workers", "EOT Status", "Date"],
                row_count=120, description="Daily manpower",
                semantic_tags=["manpower", "workers"],
            )
        ])
        builder = SchemaContextBuilder(catalog=cat, jargon=JargonManager())
        ctx = builder.build("Hangi bloklarda EOT onaylandı?")

        assert any(h.column == "EOT Status" for h in ctx.relevant_columns)
        assert "EOT" in ctx.jargon_glossary
        assert ctx.jargon_glossary["EOT"] == "Extension of Time"

    def test_router_mode_lists_tables(self):
        cat = _make_catalog([
            TableMetadata(
                table_id="t1", source_file="x.xlsx", source_type="excel",
                table_name="ipc_sample", parquet_path="",
                columns=["BOQ Qty", "Cumulative", "Block"], row_count=42,
            )
        ])
        builder = SchemaContextBuilder(catalog=cat, jargon=JargonManager())
        block = builder.build("BOQ comparison").to_prompt_block("router")

        assert "ipc_sample" in block
        assert "BOQ Qty" in block

    def test_empty_catalog_yields_empty_context(self):
        cat = _make_catalog([])
        builder = SchemaContextBuilder(catalog=cat, jargon=JargonManager())
        ctx = builder.build("anything")
        assert ctx.is_empty()
        assert ctx.to_prompt_block("compact") == ""


# ── Schema semantic intent ─────────────────────────────────────────


class TestSchemaSemanticIntent:
    @pytest.mark.parametrize("query, expected_schema", [
        ("Show equipment operating hours by floor", "equipment_log"),
        ("What is the cumulative progress percentage by activity?", "ipc_sample"),
        ("Total certified amount by activity code", "ipc_sample"),
        ("Average workers per block", "manpower_production"),
        ("Breakdown of manpower production by trade", "manpower_production"),
    ])
    def test_schema_data_queries_are_detected(self, query, expected_schema):
        signal = analyze_schema_intent(query, jargon=JargonManager())
        assert signal.is_data_intent, signal.reasons
        assert expected_schema in signal.matched_schemas

    @pytest.mark.parametrize("query", [
        "Which documents are related to FASTA?",
        "Summarize the letter about fire alarm approval",
        "What does the contract say about payment penalties?",
    ])
    def test_non_schema_content_queries_are_not_data(self, query):
        signal = analyze_schema_intent(query, jargon=JargonManager())
        assert not signal.is_data_intent, signal.reasons


# ── JargonManager bidirectional + concept ───────────────────────────


class TestJargonBidirectional:
    def test_builtin_terms_are_loaded_from_term_description_json(self):
        stored_terms = json.loads(JARGON_TERMS_FILE.read_text(encoding="utf-8"))

        assert stored_terms == JargonManager.BUILTIN_JARGON
        assert len(stored_terms) == 2703

    def test_case_collisions_merge_without_losing_meanings(self):
        jm = JargonManager()
        for upper, mixed in (("CALENDAR", "Calendar"), ("LAG", "Lag"),
                             ("NOD", "NoD"), ("PROJECT", "Project"),
                             ("SOC", "SoC")):
            merged = jm.expand(upper)
            assert JargonManager.BUILTIN_JARGON[upper] in merged
            assert JargonManager.BUILTIN_JARGON[mixed] in merged

    def test_prepared_query_preserves_original_and_is_bounded(self):
        jm = JargonManager()
        query = "Review the EOT, Bill of Quantities, and NOD positions."
        prepared = jm.prepare_query(query, max_terms=2, max_context_chars=500)
        assert prepared.original == query
        assert len(prepared.matches) == 2
        assert len(prepared.context) <= 500
        assert prepared.retrieval_queries[0] == query
        assert any("Extension of Time" in variant for variant in prepared.retrieval_queries)

    def test_compress_full_term_to_abbr(self):
        jm = JargonManager()
        out = jm.compress_query("Extension of Time approved")
        assert "EOT" in out
        assert "Extension of Time" not in out

    def test_compress_skips_when_abbr_already_present(self):
        jm = JargonManager()
        out = jm.compress_query("EOT and Extension of Time mixed")
        assert "Extension of Time" in out  # not collapsed because EOT already there
        assert out.count("EOT") == 1

    def test_normalize_query_bidirectional(self):
        jm = JargonManager()
        out = jm.normalize_query_bidirectional("Bill of Quantities review")
        assert "BOQ" in out

    def test_replace_query_terms_with_meanings_for_rag(self):
        jm = JargonManager()
        jm._add_term("FASTA", "Fire Alarm System Testing and Approval")

        out = jm.replace_query_terms_with_meanings(
            "Which documents are related to FASTA?"
        )

        assert "Fire Alarm System Testing and Approval" in out
        assert "FASTA" not in out

    def test_fasta_is_builtin_for_rag(self):
        jm = JargonManager()
        out = jm.replace_query_terms_with_meanings(
            "Which documents are related to FASTA?"
        )

        assert "Fire Alarm System Testing and Approval" in out
        assert "FASTA" not in out

    def test_replace_query_terms_is_case_insensitive(self):
        jm = JargonManager()
        jm._add_term("FASTA", "Fire Alarm System Testing and Approval")

        out = jm.replace_query_terms_with_meanings("documents related to fasta")

        assert out == "documents related to Fire Alarm System Testing and Approval"

    def test_lookup_concept_group(self):
        jm = JargonManager()
        delay_terms = jm.lookup_concept_group("delay")
        assert delay_terms is not None
        assert "EOT" in delay_terms
        assert jm.lookup_concept_group("foobar_unknown_xyz") is None


# ── Custom term lifecycle ───────────────────────────────────────────


class TestCustomTermLifecycle:
    def test_add_persist_remove(self, tmp_path):
        jm = JargonManager()
        jm._custom_store_path = tmp_path / "custom.json"

        rec = jm.add_custom_term("ZZQ", "Zone Z Quality", concept_group="quality")
        assert rec["abbreviation"] == "ZZQ"
        assert jm.expand("ZZQ") == "Zone Z Quality"

        # Persisted
        assert (tmp_path / "custom.json").exists()

        # Reload into a fresh manager
        jm2 = JargonManager()
        jm2._custom_store_path = tmp_path / "custom.json"
        loaded = jm2.load_from_disk()
        assert loaded == 1
        assert jm2.expand("ZZQ") == "Zone Z Quality"

        # Concept group augmented
        assert "ZZQ" in jm2.DOMAIN_CONCEPT_GROUPS["quality"]

        # Builtin protection
        with pytest.raises(ValueError):
            jm2.add_custom_term("EOT", "override")
        with pytest.raises(ValueError):
            jm2.remove_custom_term("EOT")

        assert jm2.remove_custom_term("ZZQ") is True
        assert jm2.expand("ZZQ") is None


# ── validate_columns_against_schema ─────────────────────────────────


class TestSchemaIntegrityGuard:
    def _table(self):
        return TableMetadata(
            table_id="t", source_file="", source_type="excel",
            table_name="manpower", parquet_path="",
            columns=["Block", "Floor", "Number of Workers", "Date"],
        )

    def test_exact_and_case_insensitive(self):
        r = validate_columns_against_schema(["Block", "block", "Floor"], self._table())
        assert r.resolved["Block"] == "Block"
        assert r.resolved["block"] == "Block"
        assert r.resolved["Floor"] == "Floor"
        assert not r.unresolved

    def test_jaccard_resolves_underscored_alias(self):
        r = validate_columns_against_schema(["number_of_workers"], self._table())
        assert r.resolved["number_of_workers"] == "Number of Workers"

    def test_unresolved_marked(self):
        r = validate_columns_against_schema(["delay_days"], self._table())
        assert "delay_days" in r.unresolved
        assert r.confidence < 1.0


# ── Router heuristic classification ─────────────────────────────────


class _StubDataAnalyzer:
    """Minimal data_analyzer stub for router heuristic tests."""

    def __init__(self, tables=None, columns_by_table=None):
        self._tables = list(tables or [])
        self._columns = columns_by_table or {}

    def list_tables(self):
        return list(self._tables)

    def get_table_summary(self, tname):
        if tname not in self._tables:
            return None
        return {
            "columns": self._columns.get(tname, []),
            "dtypes": {c: "VARCHAR" for c in self._columns.get(tname, [])},
            "header_metadata": {},
        }

    def get_tables_for_doc_ids(self, doc_ids):
        return list(self._tables)


def _make_router(tables=None, columns_by_table=None):
    from src.router import QueryRouter

    router = QueryRouter.__new__(QueryRouter)
    router.document_rag = None  # not used by classify_query
    router.data_analyzer = _StubDataAnalyzer(tables=tables, columns_by_table=columns_by_table)
    router._jargon = None
    router._hybrid_executor = None
    router._schema_alias_cache = {}
    return router


class TestRouterDocumentVsData:
    """Document-style queries must not be routed to SQL even when tables are loaded.

    Regression for: 'When I ask something directly related to documents the LLM
    answers with duckdb database even if there is no relation.'
    """

    def _tables_loaded(self):
        # Simulate a project with manpower + equipment tables loaded.
        return _make_router(
            tables=["manpower", "equipment"],
            columns_by_table={
                "manpower": ["Block", "Floor", "Workers", "Date", "Trade"],
                "equipment": ["Block", "Crane Hours", "Date"],
            },
        )

    @pytest.mark.parametrize("query", [
        "What is this project about?",
        "Describe the contract scope",
        "Summarize the payment terms",
        "What does clause 5 say?",
        "Explain the liability obligations",
        "According to the contract, what are the conditions?",
    ])
    def test_document_intent_routes_to_document(self, query):
        from src.router import QueryType
        router = self._tables_loaded()
        decision = router.classify_query(query)
        assert decision.query_type == QueryType.DOCUMENT, (
            f"{query!r} routed to {decision.query_type} — reasons: {decision.reasons}"
        )

    @pytest.mark.parametrize("query", [
        "How many steel fixers on Block A?",
        "Total crane hours in January",
        "Average workers per floor",
        "Sum of equipment hours by block",
    ])
    def test_data_queries_still_route_to_data(self, query):
        from src.router import QueryType
        router = self._tables_loaded()
        decision = router.classify_query(query)
        assert decision.query_type == QueryType.DATA, (
            f"{query!r} routed to {decision.query_type} — reasons: {decision.reasons}"
        )

    def test_doc_intent_overrides_column_name_overlap(self):
        """A doc-intent query that mentions a word also present in a column name
        ('block', 'workers') should still go to DOCUMENT.
        """
        from src.router import QueryType
        router = self._tables_loaded()
        decision = router.classify_query("Describe the scope of work for Block A")
        assert decision.query_type == QueryType.DOCUMENT, decision.reasons

    def test_generic_word_alone_does_not_force_data(self):
        """'value' / 'data' / 'list' alone shouldn't flip a doc query to DATA."""
        from src.router import QueryType
        router = self._tables_loaded()
        decision = router.classify_query("What is the value of the contract penalty clause?")
        assert decision.query_type == QueryType.DOCUMENT, decision.reasons

    def test_related_documents_query_routes_to_rag_not_sql(self):
        """Document relationship searches must retrieve RAG chunks, not run SQL."""
        from src.router import QueryType
        router = self._tables_loaded()
        decision = router.classify_query(
            "Which documents are related to FASTA?",
            mode="document_analysis",
        )
        assert decision.query_type == QueryType.FILE_LIST, decision.reasons

    def test_dual_document_dispatch_uses_metadata_aware_path(self):
        from src.router import QueryType
        router = self._tables_loaded()
        calls = []

        def fake_dual(query, doc_ids=None):
            calls.append((query, doc_ids))
            return {"openai": {"answer": "ok", "sources": []}}

        router._handle_document_query_dual = fake_dual
        result = router._dispatch_query_dual(
            QueryType.DOCUMENT,
            "Which documents are related to FASTA?",
            "Which documents are related to FASTA?",
            doc_ids=["doc-1"],
        )

        assert calls == [("Which documents are related to FASTA?", ["doc-1"])]
        assert result["openai"]["answer"] == "ok"

    def test_document_search_topic_extracts_only_subject(self):
        router = self._tables_loaded()
        topic = router._extract_document_search_topic(
            "Which documents are related to FASTA?"
        )
        assert topic == "FASTA"

    def test_document_search_topic_uses_current_question(self):
        router = self._tables_loaded()
        topic = router._extract_document_search_topic(
            "<CONVERSATION_HISTORY>User: old</CONVERSATION_HISTORY>\n\n"
            "Current question: Which documents are related to FASTA?"
        )
        assert topic == "FASTA"

    @pytest.mark.parametrize("query", [
        "What is the cumulative progress percentage by activity?",
        "Show equipment operating hours by floor",
        "Average workers per block",
    ])
    def test_schema_semantic_queries_route_to_data(self, query):
        from src.router import QueryType
        router = self._tables_loaded()
        decision = router.classify_query(query)
        assert decision.query_type == QueryType.DATA, decision.reasons

    def test_schema_term_inside_document_search_stays_rag(self):
        from src.router import QueryType
        router = self._tables_loaded()
        decision = router.classify_query("Which documents mention BOQ quantity?")
        assert decision.query_type == QueryType.FILE_LIST, decision.reasons
