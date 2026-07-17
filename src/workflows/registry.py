"""Registered workflow catalogue.

The planner may only select a WorkflowId present here; the executor delegates
`target` to an existing composite runner or a workflow adapter, or — for
planned/unavailable entries — returns a structured "not implemented yet /
here's a substitute" message. No LLM-named workflows, ever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .types import WorkflowId, WorkflowStatus, WorkflowStep


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: WorkflowId
    name: str
    status: WorkflowStatus
    trigger_examples: List[str]
    required_inputs: List[str]
    steps: List[WorkflowStep]
    risk: str = "medium"
    expected_blocks: List[str] = field(default_factory=list)
    # Available/partial: delegation target — "composite:<id>" or "adapter:<name>".
    target: Optional[str] = None
    analyst_review_required: bool = False
    # Planned/unavailable extras:
    substitute: Optional[WorkflowId] = None
    substitute_hint: str = ""
    runnable_now: List[str] = field(default_factory=list)


def _step(step_id, tool_id, desc, **kw) -> WorkflowStep:
    return WorkflowStep(step_id=step_id, tool_id=tool_id, description=desc, **kw)


WORKFLOWS: Dict[WorkflowId, WorkflowSpec] = {
    # ── AVAILABLE ────────────────────────────────────────────
    WorkflowId.PROGRAMME_INVENTORY: WorkflowSpec(
        workflow_id=WorkflowId.PROGRAMME_INVENTORY,
        name="Programme inventory",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["What programme files are available?",
                          "List XER files.", "Which programme is latest?"],
        required_inputs=["at least one .xer file"],
        steps=[_step("inventory", "programme.inventory",
                     "Catalogue XER revisions", expected_outputs=["data_table"])],
        expected_blocks=["data_table", "caveats", "validation_status"],
        target="adapter:programme_inventory",
    ),
    WorkflowId.PROJECT_DATA_INVENTORY: WorkflowSpec(
        workflow_id=WorkflowId.PROJECT_DATA_INVENTORY,
        name="Project data inventory",
        status=WorkflowStatus.PARTIAL,
        trigger_examples=["What data is available for this project?"],
        required_inputs=["uploaded programme/Excel files"],
        steps=[_step("inventory", "programme.inventory",
                     "Programme revisions (Excel-table listing is Sprint 2)",
                     expected_outputs=["data_table"])],
        expected_blocks=["data_table", "caveats", "validation_status"],
        target="adapter:programme_inventory",
    ),
    WorkflowId.DCMA_LATEST: WorkflowSpec(
        workflow_id=WorkflowId.DCMA_LATEST,
        name="DCMA on latest programme",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Run DCMA on latest programme.",
                          "Programme health check.", "DCMA 14-point check."],
        required_inputs=["latest .xer (auto-resolved)"],
        steps=[_step("resolve", "resolve.inputs", "Resolve latest XER"),
               _step("dcma", "programme.dcma_14_point", "14-point scorecard",
                     expected_outputs=["data_table", "artifact_link"])],
        expected_blocks=["markdown_text", "data_table", "artifact_link",
                         "caveats", "validation_status"],
        target="composite:composite.dcma_latest",
    ),
    WorkflowId.MILESTONE_SHIFT_CHART: WorkflowSpec(
        workflow_id=WorkflowId.MILESTONE_SHIFT_CHART,
        name="Milestone shift chart",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Show milestone movements as a chart.",
                          "Compare milestone shifts across XERs.",
                          "Milestone slippage graph."],
        required_inputs=["two or more dated .xer revisions"],
        steps=[_step("resolve", "resolve.inputs", "Require >=2 XERs"),
               _step("shift", "programme.milestone_shift", "Milestone drift",
                     expected_outputs=["chart", "data_table"])],
        expected_blocks=["markdown_text", "chart", "data_table",
                         "caveats", "validation_status"],
        target="composite:composite.milestone_shift_visual",
    ),
    WorkflowId.PROGRAMME_VARIANCE: WorkflowSpec(
        workflow_id=WorkflowId.PROGRAMME_VARIANCE,
        name="As-planned vs as-recorded variance",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["As-planned vs as-recorded variance.",
                          "Show slippage by activity code.",
                          "Compare planned against as-built by zone."],
        required_inputs=["a baseline and a later dated .xer revision"],
        steps=[_step("resolve", "resolve.inputs", "Baseline + recorded XER"),
               _step("variance", "programme.variance",
                     "Planned-vs-recorded bands by activity-code dimension",
                     expected_outputs=["data_table", "chart", "artifact_link"])],
        expected_blocks=["markdown_text", "data_table", "chart",
                         "artifact_link", "caveats", "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:programme_variance",
    ),
    WorkflowId.PRELIMINARY_PROGRAMME_PACK: WorkflowSpec(
        workflow_id=WorkflowId.PRELIMINARY_PROGRAMME_PACK,
        name="Preliminary programme analysis pack",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Generate a preliminary programme analysis pack.",
                          "Create programme report pack."],
        required_inputs=["one or more .xer files"],
        steps=[_step("inventory", "programme.inventory", "Inventory"),
               _step("dcma", "programme.dcma_14_point", "DCMA per revision"),
               _step("shift", "programme.milestone_shift",
                     "Milestone shift (if >=2 XERs)", required=False)],
        expected_blocks=["markdown_text", "caveats", "validation_status"],
        target="adapter:preliminary_pack",
    ),
    WorkflowId.DELAY_CHRONOLOGY_SECTION: WorkflowSpec(
        workflow_id=WorkflowId.DELAY_CHRONOLOGY_SECTION,
        name="Delay chronology (6.1 section)",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Prepare 6.1 chronology for Delayed Blockwork.",
                          "Delayed Blockwork's chronology in 6.1 format.",
                          "Create claim chronology section for delayed access."],
        required_inputs=["named delay event", "correspondence evidence"],
        steps=[_step("scope", "delay.chronology", "Resolve event scope"),
               _step("evidence", "delay.chronology", "Retrieve evidence"),
               _step("table", "delay.chronology", "Build chronology table"),
               _step("narrative", "narrative.guarded",
                     "Guarded narrative (if LLM available)", requires_llm=True,
                     required=False),
               _step("export", "export.section", "PDF/DOCX downloads",
                     required=False, expected_outputs=["artifact_link"])],
        expected_blocks=["markdown_text", "data_table", "html_report_section",
                         "artifact_link", "caveats", "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:delay_chronology",  # html mode overrides in executor
    ),
    WorkflowId.SQL_METRIC_CHART: WorkflowSpec(
        workflow_id=WorkflowId.SQL_METRIC_CHART,
        name="SQL metric chart",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Create manpower by trade chart.",
                          "Show equipment utilization by block.",
                          "Show IPC cumulative progress."],
        required_inputs=["a compatible Excel/data table"],
        steps=[_step("resolve", "resolve.inputs", "Resolve compatible table"),
               _step("metric", "sql.metric", "Deterministic metric",
                     expected_outputs=["data_table"]),
               _step("chart", "viz.bar_chart", "Chart from table",
                     required=False)],
        expected_blocks=["markdown_text", "chart", "data_table", "caveats",
                         "validation_status"],
        target="composite:composite.sql_metric_chart",
    ),
    WorkflowId.CONTEXT_TO_REPORT_SECTION: WorkflowSpec(
        workflow_id=WorkflowId.CONTEXT_TO_REPORT_SECTION,
        name="Context to report section",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Make this into a report section.",
                          "Turn the previous chart into a report block.",
                          "Create an HTML section from this."],
        required_inputs=["a previous analysis result in context"],
        steps=[_step("compose", "html.compose_section", "Sanitized HTML section",
                     expected_outputs=["html_report_section"])],
        expected_blocks=["html_report_section", "caveats", "validation_status"],
        target="composite:composite.context_to_section",
    ),

    WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER: WorkflowSpec(
        workflow_id=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER,
        name="Candidate delay event register",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Build a candidate delay event register.",
                          "Suggest delay events from the record.",
                          "Delay event register for the blockwork delay."],
        required_inputs=["correspondence evidence corpus"],
        steps=[_step("scope", "delay.chronology", "Resolve topic scope"),
               _step("evidence", "delay.chronology", "Retrieve evidence"),
               _step("extract", "narrative.guarded",
                     "Containment-guarded extraction", requires_llm=True),
               _step("persist", "resolve.inputs",
                     "Persist candidates for analyst review", human_gate=True)],
        expected_blocks=["markdown_text", "data_table", "caveats",
                         "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:candidate_register",
    ),

    WorkflowId.EVENT_EVIDENCE_TABLE: WorkflowSpec(
        workflow_id=WorkflowId.EVENT_EVIDENCE_TABLE,
        name="Event evidence table",
        status=WorkflowStatus.AVAILABLE,
        trigger_examples=["Show evidence table for confirmed delay events.",
                          "Show evidence for Event 01.",
                          "Which documents support Event 01?"],
        required_inputs=["confirmed delay events"],
        steps=[_step("read", "resolve.inputs", "Read confirmed events"),
               _step("table", "resolve.inputs", "Evidence table for the event",
                     expected_outputs=["data_table"])],
        expected_blocks=["markdown_text", "data_table", "caveats",
                         "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:event_evidence_table",
        substitute=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER,
    ),

    # ── PLANNED / UNAVAILABLE ────────────────────────────────
    WorkflowId.DELAY_BRIEFING: WorkflowSpec(
        workflow_id=WorkflowId.DELAY_BRIEFING,
        name="Delay briefing",
        status=WorkflowStatus.PARTIAL,   # MVP: composes what the data supports
        trigger_examples=[
            "Prepare a delay briefing.",
            "Generate a monthly progress and delay briefing for this project.",
        ],
        required_inputs=["a programme (.xer), confirmed delay events, or "
                         "progress data — any subset"],
        steps=[_step("programme", "programme.inventory", "Programme summary",
                     required=False),
               _step("milestone", "programme.milestone_shift",
                     "Milestone movement (needs >=2 XERs)", required=False,
                     expected_outputs=["chart"]),
               _step("events", "resolve.inputs", "Confirmed delay events",
                     required=False, expected_outputs=["data_table"]),
               _step("notice", "resolve.inputs", "Notice compliance",
                     required=False, expected_outputs=["data_table"]),
               _step("progress", "sql.metric", "Progress record",
                     required=False,
                     expected_outputs=["data_table", "chart"])],
        expected_blocks=["markdown_text", "data_table", "chart",
                         "artifact_link", "caveats", "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:delay_briefing",
        substitute=WorkflowId.DELAY_CHRONOLOGY_SECTION,
    ),
    WorkflowId.MONTHLY_PROGRESS_REPORT: WorkflowSpec(
        workflow_id=WorkflowId.MONTHLY_PROGRESS_REPORT,
        name="Monthly progress report",
        status=WorkflowStatus.PARTIAL,   # MVP: reports whatever data is loaded
        trigger_examples=["Generate the monthly progress report.",
                          "Monthly progress report for June 2025.",
                          "Monthly progress summary."],
        required_inputs=["manpower / equipment / IPC Excel data (any subset)"],
        steps=[_step("inventory", "resolve.inputs", "Loaded data inventory",
                     expected_outputs=["data_table"]),
               _step("manpower", "sql.metric", "Manpower by trade/block/month",
                     required=False, expected_outputs=["data_table", "chart"]),
               _step("equipment", "sql.metric", "Equipment hours by block/month",
                     required=False, expected_outputs=["data_table", "chart"]),
               _step("ipc", "sql.metric", "IPC certified amounts",
                     required=False, expected_outputs=["data_table", "chart"]),
               _step("production", "viz.line_chart",
                     "Cumulative production curve", required=False,
                     expected_outputs=["chart"])],
        expected_blocks=["markdown_text", "data_table", "chart", "caveats",
                         "validation_status"],
        target="adapter:monthly_progress_report",
        substitute=WorkflowId.PRELIMINARY_PROGRAMME_PACK,
    ),
    WorkflowId.PRELIMINARY_DELAY_CLAIM_PACK: WorkflowSpec(
        workflow_id=WorkflowId.PRELIMINARY_DELAY_CLAIM_PACK,
        name="Preliminary delay claim report pack",
        status=WorkflowStatus.PARTIAL,   # MVP: assembles available pieces
        trigger_examples=["Generate preliminary delay claim report pack.",
                          "Delay claim report pack."],
        required_inputs=["programme and/or confirmed delay events"],
        steps=[_step("inventory", "programme.inventory", "Programme inventory",
                     required=False),
               _step("events", "resolve.inputs", "Confirmed events",
                     required=False),
               _step("notice", "resolve.inputs", "Notice compliance",
                     required=False),
               _step("method", "resolve.inputs", "Method viability")],
        expected_blocks=["markdown_text", "data_table", "caveats",
                         "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:delay_claim_pack",
        substitute=WorkflowId.PRELIMINARY_PROGRAMME_PACK,
    ),
    WorkflowId.NOTICE_COMPLIANCE_MATRIX: WorkflowSpec(
        workflow_id=WorkflowId.NOTICE_COMPLIANCE_MATRIX,
        name="Notice compliance matrix",
        status=WorkflowStatus.PARTIAL,   # MVP: assumed periods, not clause-derived
        trigger_examples=["Create notice compliance matrix.",
                          "Notice compliance check."],
        required_inputs=["confirmed delay events", "issued notices/correspondence"],
        steps=[_step("confirmed", "resolve.inputs", "Read confirmed events"),
               _step("notices", "resolve.inputs", "Enumerate served notices"),
               _step("compare", "resolve.inputs",
                     "Served-vs-required (assumed periods)",
                     expected_outputs=["data_table"])],
        expected_blocks=["markdown_text", "data_table", "caveats",
                         "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:notice_matrix",
        substitute=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER,
    ),
    WorkflowId.CONTRACT_MECHANISM_SUMMARY: WorkflowSpec(
        workflow_id=WorkflowId.CONTRACT_MECHANISM_SUMMARY,
        name="Contract mechanism summary",
        status=WorkflowStatus.PARTIAL,   # MVP: deterministic extraction, verify
        trigger_examples=["Summarise the contract's EOT mechanism.",
                          "Contract mechanism extraction.",
                          "What are the notice periods in the contract?"],
        required_inputs=["the executed contract / conditions (doc_type=contract)"],
        steps=[_step("retrieve", "resolve.inputs", "Retrieve contract text"),
               _step("extract", "resolve.inputs",
                     "Extract notice/EOT periods (containment-guarded)",
                     expected_outputs=["data_table"])],
        expected_blocks=["markdown_text", "data_table", "caveats",
                         "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:contract_mechanism",
        substitute=WorkflowId.DELAY_EVENT_CANDIDATE_REGISTER,
    ),
    WorkflowId.METHOD_VIABILITY: WorkflowSpec(
        workflow_id=WorkflowId.METHOD_VIABILITY,
        name="Method viability",
        status=WorkflowStatus.PARTIAL,   # MVP: data-availability screen
        trigger_examples=["Assess delay-analysis method viability.",
                          "Which delay analysis method can we use?"],
        required_inputs=["programmes / confirmed events (screened)"],
        steps=[_step("gather", "resolve.inputs", "Gather input availability"),
               _step("screen", "resolve.inputs", "Method viability screen",
                     expected_outputs=["data_table"])],
        expected_blocks=["markdown_text", "data_table", "caveats",
                         "validation_status"],
        risk="high",
        analyst_review_required=True,
        target="adapter:method_viability",
        substitute=WorkflowId.PRELIMINARY_PROGRAMME_PACK,
    ),
    WorkflowId.INTERNAL_EOT_ROADMAP: WorkflowSpec(
        workflow_id=WorkflowId.INTERNAL_EOT_ROADMAP,
        name="Internal EOT roadmap",
        status=WorkflowStatus.PLANNED,
        trigger_examples=["Create internal EOT claim roadmap.",
                          "Internal EOT roadmap."],
        required_inputs=["delay events", "programme", "notices", "contract"],
        steps=[],
        substitute=WorkflowId.PRELIMINARY_PROGRAMME_PACK,
        substitute_hint="start with a preliminary programme pack + chronologies",
        runnable_now=["preliminary programme pack", "delay chronology section"],
    ),
}


# Composite intent id → WorkflowId (planner step 1 delegation map).
COMPOSITE_TO_WORKFLOW: Dict[str, WorkflowId] = {
    "composite.milestone_shift_visual": WorkflowId.MILESTONE_SHIFT_CHART,
    "composite.sql_metric_chart": WorkflowId.SQL_METRIC_CHART,
    "composite.chronology_html": WorkflowId.DELAY_CHRONOLOGY_SECTION,
    "composite.context_to_section": WorkflowId.CONTEXT_TO_REPORT_SECTION,
    "composite.dcma_latest": WorkflowId.DCMA_LATEST,
    # composite.programme_compare / composite.evidence_explain intentionally
    # NOT mapped — they keep their existing composite route (planner → None).
}


def get_spec(workflow_id: WorkflowId) -> Optional[WorkflowSpec]:
    return WORKFLOWS.get(workflow_id)


def is_available(workflow_id: WorkflowId) -> bool:
    spec = WORKFLOWS.get(workflow_id)
    return bool(spec and spec.status in (WorkflowStatus.AVAILABLE,
                                         WorkflowStatus.PARTIAL))
