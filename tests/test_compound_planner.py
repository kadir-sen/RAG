"""Sprint C — compound-analysis planner.

Locks in the decomposition → validation → DAG-execution pipeline:
  * the flagship Turkish multi-step prompt becomes a compound plan spanning
    document + programme + data + report, forensic, analyst-review required;
  * a simple prompt stays single_skill (falls through to the fast route);
  * the validator rejects any invented skill and any broken DAG;
  * the executor threads structured outputs between steps and assembles blocks;
  * high complexity earns the large thinking budget.
"""

import pytest

from src.planning import (AdvancedPlan, SubTask, OutputSpec, SkillContext,
                          SkillResult, decompose, execute_plan, is_compound,
                          is_multi_ask, validate_plan, get_skill,
                          budget_for, tier_for_complexity)
from src.planning.intent_graph import PlanGraphError, topo_order


# The product is English-only (files, inputs, outputs). This is the English
# equivalent of the illustrative multi-step prompt from the task spec.
E2E = ("First check whether there is a delay. Find the start date of the "
       "delayed project. Then check whether there is another project in that "
       "period. Investigate whether incomplete reporting was prepared for that "
       "project. Finally show this comparatively as manpower, cost and days in "
       "tables.")


class TestTrigger:
    def test_simple_prompt_is_not_compound(self):
        assert is_compound("How many workers on block B?") is False
        assert is_compound("Show the crane log") is False

    def test_e2e_prompt_is_compound(self):
        assert is_compound(E2E) is True

    def test_single_record_metric_not_compound(self):
        # one record type, no multi-step chain → fast route
        assert is_compound("manpower by trade as a table") is False


class TestDecomposeE2E:
    def test_plan_shape(self):
        p = decompose(E2E)
        assert p.plan_type in ("compound_analysis", "report_generation")
        assert p.complexity == "high"
        assert p.thinking_budget == "large"
        assert p.risk_level == "forensic"

    def test_spans_document_and_data(self):
        p = decompose(E2E)
        records = {s.record for s in p.subtasks}
        assert "document" in records and "data" in records

    def test_uses_rerank_for_document_steps(self):
        p = decompose(E2E)
        doc_steps = [s for s in p.subtasks if s.record == "document"]
        assert doc_steps and all(s.requires_rerank for s in doc_steps)

    def test_ends_with_report_output(self):
        p = decompose(E2E)
        assert p.subtasks[-1].skill.startswith("report.")

    def test_validates_clean_and_flags_analyst(self):
        p, errs = validate_plan(decompose(E2E))
        assert errs == []
        assert p.analyst_review_required is True
        assert "trust_guard" in p.guards

    def test_simple_prompt_returns_single_skill(self):
        p = decompose("How many workers on block B?")
        assert p.plan_type == "single_skill" and not p.subtasks


class TestValidator:
    def test_rejects_invented_skill(self):
        p = AdvancedPlan(subtasks=[SubTask(id="t1", skill="rag.hack_the_db")])
        _, errs = validate_plan(p)
        assert any("unknown skill" in e for e in errs)

    def test_rejects_dangling_dependency(self):
        p = AdvancedPlan(subtasks=[
            SubTask(id="t1", skill="programme.inventory", inputs={"query": "x"}),
            SubTask(id="t2", skill="report.markdown_answer",
                    inputs={"markdown": "x"}, depends_on=["ghost"])])
        _, errs = validate_plan(p)
        assert any("unknown 'ghost'" in e for e in errs)

    def test_flags_unobtainable_input(self):
        # compare_metrics needs 'tables' which nothing upstream produces
        p = AdvancedPlan(subtasks=[SubTask(
            id="t1", skill="data.compare_metrics", inputs={"query": "x"})])
        _, errs = validate_plan(p)
        assert any("needs input 'tables'" in e for e in errs)

    def test_forensic_skill_forces_analyst_review(self):
        p = AdvancedPlan(subtasks=[SubTask(
            id="t1", skill="rag.extract_delay_mentions", inputs={"query": "x"})])
        p, errs = validate_plan(p)
        assert errs == [] and p.analyst_review_required is True
        assert p.risk_level == "forensic"


class TestGraph:
    def test_topo_order_respects_dependencies(self):
        subs = [
            SubTask(id="c", skill="report.table_pack", depends_on=["b"]),
            SubTask(id="a", skill="data.resolve_tables"),
            SubTask(id="b", skill="data.compare_metrics", depends_on=["a"]),
        ]
        order = [s.id for s in topo_order(subs)]
        assert order.index("a") < order.index("b") < order.index("c")

    def test_cycle_detected(self):
        subs = [
            SubTask(id="a", skill="x", depends_on=["b"]),
            SubTask(id="b", skill="y", depends_on=["a"]),
        ]
        with pytest.raises(PlanGraphError):
            topo_order(subs)


class TestExecution:
    def _handlers(self, log):
        def delay(st, store, ctx):
            log.append(st.id)
            return SkillResult(outputs={"delay_start_date": "2024-03-01",
                                        "candidate_events": ["E1"]},
                               sources=[{"file_name": "L1.pdf", "page_number": 1}],
                               guards={"trust_guard": "passed"})

        def inventory(st, store, ctx):
            log.append(st.id)
            # reads an upstream output → proves threading
            assert "delay_start_date" in store
            return SkillResult(outputs={"projects": ["P1", "P2"]})

        def missing(st, store, ctx):
            log.append(st.id)
            return SkillResult(outputs={"missing_reporting": True},
                               caveats=["screening only, not a legal finding"])

        def resolve(st, store, ctx):
            log.append(st.id)
            return SkillResult(outputs={"tables": ["manpower_t", "cost_t"]})

        def compare(st, store, ctx):
            log.append(st.id)
            assert store.get("tables")   # threaded from resolve
            return SkillResult(outputs={"comparison_table": {"cols": ["proj"]}},
                               guards={"sql_guard": "passed"})

        def report(st, store, ctx):
            log.append(st.id)
            assert store.get("comparison_table")
            return SkillResult(blocks=[{"type": "data_table",
                                        "columns": ["proj"], "rows": [["P1"]]}])
        return {
            "rag.extract_delay_mentions": delay,
            "programme.inventory": inventory,
            "rag.extract_missing_reporting_mentions": missing,
            "data.resolve_tables": resolve,
            "data.compare_metrics": compare,
            "report.table_pack": report,
        }

    def test_e2e_execution_threads_outputs_and_assembles_blocks(self):
        log = []
        plan = decompose(E2E)
        res = execute_plan(plan, self._handlers(log), SkillContext())
        assert res.get("plan_refused") is not True
        # every step ran, in dependency order (delay before inventory/missing)
        assert set(log) == {"t_delay", "t_inventory", "t_missing",
                            "t_tables", "t_metric", "t_report"}
        assert log.index("t_delay") < log.index("t_inventory")
        assert log.index("t_tables") < log.index("t_metric") < log.index("t_report")
        # output table + validation-status + caveats blocks present
        types = {b["type"] for b in res["blocks"]}
        assert "data_table" in types
        assert "validation_status" in types
        # analyst review + unioned guards surfaced
        vs = next(b for b in res["blocks"] if b["type"] == "validation_status")
        assert vs["requires_analyst_review"] is True
        assert vs["guards"].get("trust_guard") == "passed"
        assert res["sources"]

    def test_missing_handler_is_caveat_not_crash(self):
        plan = AdvancedPlan(subtasks=[SubTask(
            id="t1", skill="programme.inventory", inputs={"query": "x"})])
        res = execute_plan(plan, {}, SkillContext())  # no handlers
        assert res.get("plan_refused") is not True
        assert any(b["type"] == "caveats" for b in res["blocks"])

    def test_invalid_plan_refused(self):
        plan = AdvancedPlan(subtasks=[SubTask(id="t1", skill="nope.invalid")])
        res = execute_plan(plan, {}, SkillContext())
        assert res.get("plan_refused") is True


class TestRouterIntegration:
    """The flag gate: off → fall through (None); on + compound → planner owns it;
    on + simple → fall through. Never disturbs the fast route."""

    def _bare_router(self):
        from src.router import QueryRouter
        r = QueryRouter.__new__(QueryRouter)  # skip heavy __init__

        def _doc(query, doc_ids=None):
            return {"answer": f"doc: {query[:20]}", "sources":
                    [{"file_name": "L1.pdf", "page_number": 1}]}

        def _data(query, doc_ids=None):
            return {"answer": "data", "sql": "SELECT 1",
                    "result_columns": ["proj", "manpower"],
                    "result_data": [["P1", 10], ["P2", 7]]}

        def _prog(query, doc_ids=None):
            return {"answer": "inventory", "projects": ["P1", "P2"]}

        r._handle_document_query = _doc
        r._handle_data_query = _data
        r._handle_programme_query = _prog
        return r

    def test_flag_off_falls_through(self, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "ENABLE_COMPOUND_PLANNER", False)
        r = self._bare_router()
        assert r._try_compound_planner(E2E, None, None) is None

    def test_simple_prompt_falls_through(self, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "ENABLE_COMPOUND_PLANNER", True)
        r = self._bare_router()
        assert r._try_compound_planner("how many workers?", None, None) is None

    def test_compound_prompt_owned_by_planner(self, monkeypatch):
        import src.config as cfg
        monkeypatch.setattr(cfg, "ENABLE_COMPOUND_PLANNER", True)
        r = self._bare_router()
        res = r._try_compound_planner(E2E, None, None)
        assert res is not None
        assert res["plan_type"] in ("compound_analysis", "report_generation")
        assert res["requires_analyst_review"] is True
        types = {b["type"] for b in res["blocks"]}
        assert "data_table" in types and "validation_status" in types
        assert res["sources"]


class TestSmartPlannerV2:
    """LLM-first planning, multi-ask precedence, the real delay skill, and
    output-format binding."""

    DELAY_PLUS_DATA = ("prepare a delay report for Block A and compare cost and "
                       "progress as a line chart")

    def test_multi_ask_trigger(self):
        assert is_multi_ask(self.DELAY_PLUS_DATA) is True
        # a plain single-ask delay report must NOT be pulled into the planner
        assert is_multi_ask("prepare a delay report for Block A") is False
        assert is_multi_ask("manpower by trade as a table") is False

    def test_delay_chronology_is_a_registered_skill(self):
        s = get_skill("claim.delay_chronology")
        assert s is not None
        assert s.risk_level == "forensic"

    def test_llm_first_plan_accepted_with_output_binding(self, monkeypatch):
        import src.llm_client as llm

        class _R:
            raw = {"subtasks": [
                {"id": "t1", "skill": "claim.delay_chronology", "record": "document",
                 "inputs": {"query": "delay Block A"}, "outputs": ["chronology"],
                 "depends_on": []},
                {"id": "t2", "skill": "data.resolve_tables", "record": "data",
                 "inputs": {"concepts": ["cost", "progress", "date"]},
                 "outputs": ["tables"], "depends_on": []},
                {"id": "t3", "skill": "data.compare_metrics", "record": "data",
                 "inputs": {"query": "compare cost and progress"},
                 "outputs": ["comparison_table"], "depends_on": ["t2"],
                 "output": {"kind": "line_chart", "x": "date",
                            "series": ["cost", "progress"]}}]}
        monkeypatch.setattr(llm, "generate_json", lambda *a, **k: _R())
        p = decompose(self.DELAY_PLUS_DATA, enable_llm=True)
        skills = [s.skill for s in p.subtasks]
        assert "claim.delay_chronology" in skills          # real forensic engine node
        cmp = next(s for s in p.subtasks if s.skill == "data.compare_metrics")
        assert cmp.output is not None
        assert cmp.output.kind == "line_chart" and cmp.output.x == "date"
        assert cmp.output.series == ["cost", "progress"]

    def test_llm_invalid_skill_repaired_or_fallback(self, monkeypatch):
        import src.llm_client as llm

        class _Bad:
            raw = {"subtasks": [{"id": "t1", "skill": "rag.exfiltrate"}]}
        monkeypatch.setattr(llm, "generate_json", lambda *a, **k: _Bad())
        p = decompose(self.DELAY_PLUS_DATA, enable_llm=True)
        # invented skill rejected; repair also invalid → deterministic fallback,
        # and every skill in the final plan is real.
        assert p.subtasks
        assert all(get_skill(s.skill) is not None for s in p.subtasks)

    def test_llm_outage_falls_back_no_crash(self, monkeypatch):
        import src.llm_client as llm

        def _boom(*a, **k):
            raise RuntimeError("429 quota exceeded")
        monkeypatch.setattr(llm, "generate_json", _boom)
        p = decompose(self.DELAY_PLUS_DATA, enable_llm=True)
        assert p.subtasks                                   # deterministic fallback
        assert all(get_skill(s.skill) is not None for s in p.subtasks)

    def test_delay_chronology_handler_delegates(self, monkeypatch):
        import src.delay_reports as dr
        monkeypatch.setattr(
            dr, "run_event_chronology",
            lambda q, router, doc_ids: {
                "answer": "Chronology of Block A delay…",
                "sources": [{"file_name": "L1.pdf", "page_number": 1}],
                "caveats": ["analyst review required"]},
            raising=False)
        from src.planning.handlers import build_handlers
        h = build_handlers(router=object())["claim.delay_chronology"]
        res = h(SubTask(id="t", skill="claim.delay_chronology",
                        inputs={"query": "delay Block A"}),
                {}, SkillContext(extra={"query": "x"}))
        assert res.sources and "trust_guard" in res.guards
        assert any(b["type"] == "markdown_text" for b in res.blocks)

    def test_router_precedence_delay_plus_data(self, monkeypatch):
        # The router must try the compound planner for a multi-ask prompt even
        # though _classify_delay_report would match "delay report".
        import src.config as cfg
        monkeypatch.setattr(cfg, "ENABLE_COMPOUND_PLANNER", True)
        from src.router import QueryRouter
        r = QueryRouter.__new__(QueryRouter)
        assert r._wants_compound(self.DELAY_PLUS_DATA) is True
        assert r._wants_compound("prepare a delay report for Block A") is False


class TestBudget:
    def test_high_complexity_large_budget(self):
        assert tier_for_complexity("high") == "large"
        b = budget_for("large")
        assert b.max_subtasks >= 4 and b.allow_rerank

    def test_small_budget_is_direct(self):
        b = budget_for("small")
        assert b.max_subtasks == 1 and b.allow_rerank is False
