"""
SchemaContextBuilder - centralized schema + jargon context for LLM prompts.

Produces a structured context block that any prompt can inject (router
classification, document RAG, hybrid synthesis, project Q&A, SQL).
Three rendering modes:
  - "router"  : ~300 token, table+column inventory only
  - "compact" : ~600 token, query-relevant columns + jargon hits
  - "full"    : ~1500 token, samples + concept groups (synthesis)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from .catalog import TableCatalog, TableMetadata, get_catalog
from .jargon_manager import JargonManager, get_jargon_manager
from .logger import logger
from .config import BASE_DIR


PromptMode = Literal["router", "compact", "full"]


@dataclass
class TableSummary:
    table_name: str
    table_id: str
    columns: List[str] = field(default_factory=list)
    column_dtypes: Dict[str, str] = field(default_factory=dict)
    column_jargon: Dict[str, str] = field(default_factory=dict)
    row_count: int = 0
    description: str = ""
    semantic_tags: List[str] = field(default_factory=list)


@dataclass
class ColumnHit:
    table_name: str
    column: str
    expanded: Optional[str] = None
    score: float = 0.0


@dataclass
class SchemaContext:
    table_inventory: List[TableSummary] = field(default_factory=list)
    relevant_columns: List[ColumnHit] = field(default_factory=list)
    jargon_glossary: Dict[str, str] = field(default_factory=dict)
    concept_groups: List[str] = field(default_factory=list)
    sample_values: Dict[str, List[str]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.table_inventory and not self.jargon_glossary

    def to_prompt_block(self, mode: PromptMode = "compact") -> str:
        """Render context into a string suitable for prompt injection."""
        if self.is_empty():
            return ""

        parts: List[str] = []

        if mode == "router":
            parts.append(self._render_router())
        elif mode == "compact":
            parts.append(self._render_compact())
        else:
            parts.append(self._render_full())

        return "\n".join(p for p in parts if p).strip()

    def _render_router(self) -> str:
        if not self.table_inventory:
            return ""
        lines = ["KNOWN TABLES (for routing decisions):"]
        for t in self.table_inventory:
            cols = ", ".join(t.columns[:12])
            if len(t.columns) > 12:
                cols += f" (+{len(t.columns) - 12} more)"
            lines.append(f"  - {t.table_name} [{t.row_count} rows]: {cols}")
        if self.jargon_glossary:
            lines.append("")
            lines.append("Jargon hits in query:")
            for abbr, full in list(self.jargon_glossary.items())[:8]:
                lines.append(f"  - {abbr} = {full}")
        return "\n".join(lines)

    def _render_compact(self) -> str:
        lines: List[str] = []

        if self.relevant_columns:
            lines.append("RELEVANT TABLE COLUMNS (matched to query):")
            for hit in self.relevant_columns[:15]:
                tail = f" — {hit.expanded}" if hit.expanded else ""
                lines.append(f"  - {hit.table_name}.{hit.column}{tail}")

        if self.jargon_glossary:
            if lines:
                lines.append("")
            lines.append("Jargon glossary:")
            for abbr, full in list(self.jargon_glossary.items())[:12]:
                lines.append(f"  - {abbr} = {full}")

        if self.concept_groups:
            if lines:
                lines.append("")
            lines.append(f"Concept groups triggered: {', '.join(self.concept_groups)}")

        if not lines and self.table_inventory:
            lines.append(self._render_router())

        return "\n".join(lines)

    def _render_full(self) -> str:
        lines: List[str] = []

        if self.table_inventory:
            lines.append("TABLE INVENTORY:")
            for t in self.table_inventory:
                lines.append(f"  • {t.table_name} [{t.row_count} rows] — {t.description or '(no description)'}")
                col_lines = []
                for col in t.columns:
                    dtype = t.column_dtypes.get(col, "")
                    jargon = t.column_jargon.get(col, "")
                    suffix = []
                    if dtype:
                        suffix.append(dtype)
                    if jargon:
                        suffix.append(f"= {jargon}")
                    suffix_str = f" ({'; '.join(suffix)})" if suffix else ""
                    col_lines.append(f"      - {col}{suffix_str}")
                lines.extend(col_lines)
                if t.semantic_tags:
                    lines.append(f"      tags: {', '.join(t.semantic_tags)}")

        if self.sample_values:
            lines.append("")
            lines.append("SAMPLE VALUES:")
            for key, samples in list(self.sample_values.items())[:10]:
                preview = ", ".join(str(s) for s in samples[:3])
                lines.append(f"  - {key}: {preview}")

        if self.jargon_glossary:
            lines.append("")
            lines.append("JARGON GLOSSARY:")
            for abbr, full in self.jargon_glossary.items():
                lines.append(f"  - {abbr} = {full}")

        if self.concept_groups:
            lines.append("")
            lines.append(f"CONCEPT GROUPS: {', '.join(self.concept_groups)}")

        return "\n".join(lines)


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


_GENERIC_SCHEMA_TOKENS = {
    "date", "work", "item", "name", "code", "type", "description",
    "reference", "period", "current", "previous", "total", "number",
    "value", "status", "project", "construction",
}

_DATA_ACTION_TERMS = {
    "average", "avg", "breakdown", "calculate", "count", "distribution",
    "filter", "group", "how many", "list", "maximum", "minimum", "max",
    "min", "per", "percentage", "rank", "show", "sort", "sum", "total",
    "trend", "utilization", "compare", "by",
}

_SCHEMA_INTERPRETATIONS = {
    "equipment_log": {
        "meaning": (
            "Equipment Log means structured daily machinery deployment and "
            "operating-hour data by date, block, floor, and machinery type."
        ),
        "terms": [
            "equipment", "machinery", "machine", "crane", "excavator",
            "operating hours", "machinery hours", "equipment hours",
            "utilization", "deployment",
        ],
    },
    "ipc_sample": {
        "meaning": (
            "IPC means structured progress certificate data: activities, BOQ "
            "quantities, unit rates, contract amounts, previous/current/"
            "cumulative progress, certified quantities, and certified amounts."
        ),
        "terms": [
            "ipc", "interim progress certificate", "progress", "boq",
            "bill of quantities", "activity", "activity code", "activity name",
            "unit rate", "contract amount", "certified amount",
            "cumulative progress", "current progress", "previous progress",
            "cumulative quantity", "current quantity", "boq quantity",
        ],
    },
    "manpower_production": {
        "meaning": (
            "Manpower Production Log means structured workforce deployment and "
            "production-output data by date, block, floor, activity, trade, "
            "worker count, quantity, and unit of measure."
        ),
        "terms": [
            "manpower", "workforce", "workers", "worker count", "headcount",
            "trade", "craft", "job", "job description", "activity",
            "production", "output", "quantity", "quantification",
            "productivity", "labor", "labour",
        ],
    },
}


@dataclass
class SchemaIntentResult:
    """Semantic decision signal for DATA vs RAG routing."""

    is_data_intent: bool = False
    confidence: float = 0.0
    score: float = 0.0
    matched_schemas: List[str] = field(default_factory=list)
    matched_columns: List[str] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


def _phrase_in_query(phrase: str, query_lower: str) -> bool:
    phrase = phrase.strip().lower().replace("_", " ")
    if not phrase:
        return False
    if " " in phrase:
        return phrase in query_lower
    return re.search(rf"\b{re.escape(phrase)}\b", query_lower) is not None


def _load_schema_definitions() -> List[dict]:
    import json

    schema_dir = BASE_DIR / "storage" / "schemas"
    definitions: List[dict] = []
    for path in sorted(schema_dir.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                definitions.append(json.load(f))
        except Exception as e:
            logger.debug(f"[SchemaIntent] could not load {path}: {e}")
    return definitions


def _schema_terms(schema_def: dict) -> Dict[str, float]:
    """Build weighted schema concepts from schema JSON + local interpretation."""
    schema_id = schema_def.get("schema_id", "")
    terms: Dict[str, float] = {}

    def add(term: str, weight: float) -> None:
        clean = (term or "").strip().lower().replace("_", " ")
        if not clean:
            return
        terms[clean] = max(terms.get(clean, 0.0), weight)

    add(schema_id, 2.5)
    add(schema_def.get("name", ""), 2.0)
    for token in _tokenize(schema_def.get("description", "")):
        if token not in _GENERIC_SCHEMA_TOKENS:
            add(token, 0.6)

    interpretation = _SCHEMA_INTERPRETATIONS.get(schema_id, {})
    for term in interpretation.get("terms", []):
        add(term, 2.0 if " " in term else 1.4)
    for token in _tokenize(interpretation.get("meaning", "")):
        if token not in _GENERIC_SCHEMA_TOKENS:
            add(token, 0.5)

    for col in schema_def.get("columns", []):
        add(col.get("name", ""), 2.2)
        for alias in col.get("aliases", []):
            add(alias, 2.0 if " " in alias.replace("_", " ") else 1.3)
        for token in _tokenize(col.get("description", "")):
            if token not in _GENERIC_SCHEMA_TOKENS:
                add(token, 0.5)

    return terms


def analyze_schema_intent(query: str, jargon: Optional[JargonManager] = None) -> SchemaIntentResult:
    """
    Decide whether a query belongs to structured Excel/SQL data.

    This is a conservative semantic gate: DATA requires meaningful overlap with
    schema concepts (columns, aliases, descriptions, and schema interpretations).
    If a query does not strongly map to the schema layer, RAG remains the safer
    destination.
    """
    if not query:
        return SchemaIntentResult()

    jargon = jargon or get_jargon_manager()
    semantic_query = jargon.replace_query_terms_with_meanings(query)
    query_lower = semantic_query.lower().replace("_", " ")
    query_tokens = set(_tokenize(semantic_query))
    has_data_action = any(_phrase_in_query(term, query_lower) for term in _DATA_ACTION_TERMS)

    schema_scores: Dict[str, float] = {}
    matched_columns: List[str] = []
    matched_terms: List[str] = []

    for schema_def in _load_schema_definitions():
        schema_id = schema_def.get("schema_id", "")
        score = 0.0
        terms = _schema_terms(schema_def)

        for term, weight in terms.items():
            if _phrase_in_query(term, query_lower):
                score += weight
                if term not in matched_terms:
                    matched_terms.append(term)
            elif " " not in term and term in query_tokens and term not in _GENERIC_SCHEMA_TOKENS:
                score += min(weight, 0.8)
                if term not in matched_terms:
                    matched_terms.append(term)

        for col in schema_def.get("columns", []):
            col_name = col.get("name", "")
            phrases = [col_name, *col.get("aliases", [])]
            if any(_phrase_in_query(p, query_lower) for p in phrases):
                matched_columns.append(f"{schema_id}.{col_name}")

        if score > 0:
            schema_scores[schema_id] = score

    if not schema_scores:
        return SchemaIntentResult(reasons=["No schema concepts matched"])

    ranked = sorted(schema_scores.items(), key=lambda kv: kv[1], reverse=True)
    top_schema, top_score = ranked[0]
    matched_schemas = [schema for schema, score in ranked if score >= 1.0]

    # Data intent needs both schema semantics and either an analytical/listing
    # action or a strong exact schema-column/entity phrase.
    strong_schema_match = top_score >= 3.0
    very_strong_schema_match = top_score >= 5.0
    is_data = strong_schema_match and (has_data_action or very_strong_schema_match)
    confidence = min(0.94, 0.45 + (top_score * 0.08) + (0.12 if has_data_action else 0.0))

    reasons = [
        f"schema={top_schema} score={top_score:.2f}",
        f"data_action={has_data_action}",
    ]
    if matched_terms:
        reasons.append("terms=" + ", ".join(matched_terms[:8]))
    if matched_columns:
        reasons.append("columns=" + ", ".join(matched_columns[:6]))

    return SchemaIntentResult(
        is_data_intent=is_data,
        confidence=confidence if is_data else min(confidence, 0.65),
        score=top_score,
        matched_schemas=matched_schemas,
        matched_columns=matched_columns,
        matched_terms=matched_terms[:12],
        reasons=reasons,
    )


class SchemaContextBuilder:
    """Build a SchemaContext for a given user query."""

    def __init__(
        self,
        catalog: Optional[TableCatalog] = None,
        jargon: Optional[JargonManager] = None,
    ):
        self._catalog = catalog
        self._jargon = jargon

    @property
    def catalog(self) -> TableCatalog:
        if self._catalog is None:
            self._catalog = get_catalog()
        return self._catalog

    @property
    def jargon(self) -> JargonManager:
        if self._jargon is None:
            self._jargon = get_jargon_manager()
        return self._jargon

    def build(
        self,
        query: str,
        project_id: Optional[str] = None,
        max_tables: int = 8,
        include_samples: bool = False,
        max_relevant_columns: int = 20,
    ) -> SchemaContext:
        all_tables = self.catalog.get_all_tables()
        if not all_tables:
            return SchemaContext()

        tokens = set(_tokenize(query))

        relevant_hits = self._match_columns(query, tokens, all_tables, max_relevant_columns)
        relevant_table_names = {h.table_name for h in relevant_hits}

        ranked = self._rank_tables(query, tokens, all_tables, relevant_table_names)
        chosen = ranked[:max_tables]

        inventory = [self._build_summary(t) for t in chosen]

        glossary = self._trigger_jargon(query)
        concepts = self._trigger_concept_groups(query)

        samples: Dict[str, List[str]] = {}
        if include_samples:
            samples = self._load_samples(chosen, relevant_hits)

        return SchemaContext(
            table_inventory=inventory,
            relevant_columns=relevant_hits,
            jargon_glossary=glossary,
            concept_groups=concepts,
            sample_values=samples,
        )

    def _match_columns(
        self,
        query: str,
        tokens: set,
        tables: List[TableMetadata],
        limit: int,
    ) -> List[ColumnHit]:
        if not tokens:
            return []

        query_lower = query.lower()
        hits: List[ColumnHit] = []

        for table in tables:
            for col in table.columns:
                col_lower = col.lower()
                col_tokens = set(_tokenize(col))
                score = 0.0

                if col_lower in query_lower:
                    score += 3.0
                overlap = tokens & col_tokens
                if overlap:
                    score += 1.0 * len(overlap)

                if score <= 0:
                    continue

                expanded = table.column_jargon.get(col)
                if not expanded:
                    _, exp = self.jargon.normalize_column_name(col)
                    expanded = exp

                hits.append(
                    ColumnHit(
                        table_name=table.table_name,
                        column=col,
                        expanded=expanded,
                        score=score,
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def _rank_tables(
        self,
        query: str,
        tokens: set,
        tables: List[TableMetadata],
        relevant_table_names: set,
    ) -> List[TableMetadata]:
        scored: List[Tuple[float, TableMetadata]] = []
        query_lower = query.lower()

        for t in tables:
            score = 0.0
            if t.table_name in relevant_table_names:
                score += 5.0
            for tag in t.semantic_tags:
                if tag.lower() in query_lower:
                    score += 1.5
            for token in tokens:
                if t.description and token in t.description.lower():
                    score += 0.5
            scored.append((score, t))

        scored.sort(key=lambda pair: (pair[0], pair[1].row_count), reverse=True)
        return [t for _, t in scored]

    def _build_summary(self, table: TableMetadata) -> TableSummary:
        column_jargon = dict(table.column_jargon)
        if not column_jargon:
            for col in table.columns:
                _, expanded = self.jargon.normalize_column_name(col)
                if expanded:
                    column_jargon[col] = expanded

        return TableSummary(
            table_name=table.table_name,
            table_id=table.table_id,
            columns=list(table.columns),
            column_jargon=column_jargon,
            row_count=table.row_count,
            description=table.description or table.summary or "",
            semantic_tags=list(table.semantic_tags),
        )

    def _trigger_jargon(self, query: str) -> Dict[str, str]:
        glossary: Dict[str, str] = {}
        for hit in self.jargon.find_related_terms(query):
            glossary[hit["abbreviation"]] = hit["meaning"]
        return glossary

    def _trigger_concept_groups(self, query: str) -> List[str]:
        query_lower = query.lower()
        triggered: List[str] = []
        for concept in self.jargon.DOMAIN_CONCEPT_GROUPS.keys():
            if concept in query_lower:
                triggered.append(concept)
        return triggered

    def _load_samples(
        self,
        tables: List[TableMetadata],
        hits: List[ColumnHit],
    ) -> Dict[str, List[str]]:
        cols_by_table: Dict[str, List[str]] = {}
        for h in hits:
            cols_by_table.setdefault(h.table_name, []).append(h.column)

        samples: Dict[str, List[str]] = {}
        for t in tables:
            if t.table_name not in cols_by_table:
                continue
            cols = cols_by_table[t.table_name][:3]
            try:
                import pandas as pd

                if not Path(t.parquet_path).exists():
                    continue
                df = pd.read_parquet(t.parquet_path, columns=cols)
                df = df.head(50)
                for c in cols:
                    if c not in df.columns:
                        continue
                    vals = (
                        df[c]
                        .dropna()
                        .astype(str)
                        .unique()
                        .tolist()[:3]
                    )
                    if vals:
                        samples[f"{t.table_name}.{c}"] = vals
            except Exception as e:
                logger.debug(f"[SchemaContext] sample load failed for {t.table_name}: {e}")
        return samples


@dataclass
class ColumnValidationResult:
    resolved: Dict[str, str] = field(default_factory=dict)   # requested -> actual
    unresolved: List[str] = field(default_factory=list)
    confidence: float = 1.0
    strategy_per_column: Dict[str, str] = field(default_factory=dict)


def validate_columns_against_schema(
    requested_columns: List[str],
    table: TableMetadata,
    registry=None,
) -> ColumnValidationResult:
    """
    Resolve requested column names against a table's actual columns.

    Strategies (in order): exact -> case-insensitive -> registry alias -> token Jaccard.
    Used to catch LLM hallucinated column names before SQL execution.
    """
    actual = list(table.columns)
    actual_lower = {c.lower(): c for c in actual}

    result = ColumnValidationResult()
    if not requested_columns:
        return result

    confidences: List[float] = []

    for req in requested_columns:
        req_clean = (req or "").strip().strip('"').strip("'")
        if not req_clean:
            continue

        if req_clean in actual:
            result.resolved[req_clean] = req_clean
            result.strategy_per_column[req_clean] = "exact"
            confidences.append(1.0)
            continue

        low = req_clean.lower()
        if low in actual_lower:
            result.resolved[req_clean] = actual_lower[low]
            result.strategy_per_column[req_clean] = "case_insensitive"
            confidences.append(0.95)
            continue

        registry_hit = None
        if registry is not None:
            try:
                resolver = getattr(registry, "resolve_alias", None)
                if callable(resolver):
                    registry_hit = resolver(req_clean, table.table_name)
                else:
                    schemas = getattr(registry, "_schemas", {}) or {}
                    for schema in schemas.values():
                        for col in getattr(schema, "columns", []):
                            aliases = getattr(col, "aliases", []) or []
                            if req_clean in aliases or low in [a.lower() for a in aliases]:
                                target_name = getattr(col, "name", None)
                                if target_name and target_name in actual:
                                    registry_hit = target_name
                                    break
                        if registry_hit:
                            break
            except Exception:
                registry_hit = None

        if registry_hit and registry_hit in actual:
            result.resolved[req_clean] = registry_hit
            result.strategy_per_column[req_clean] = "registry_alias"
            confidences.append(0.85)
            continue

        req_tokens = set(_tokenize(req_clean))
        best_col, best_score = None, 0.0
        for col in actual:
            col_tokens = set(_tokenize(col))
            if not col_tokens or not req_tokens:
                continue
            jacc = len(req_tokens & col_tokens) / len(req_tokens | col_tokens)
            if jacc > best_score:
                best_score = jacc
                best_col = col
        if best_col and best_score >= 0.5:
            result.resolved[req_clean] = best_col
            result.strategy_per_column[req_clean] = f"jaccard_{best_score:.2f}"
            confidences.append(best_score)
            continue

        result.unresolved.append(req_clean)
        confidences.append(0.0)

    if confidences:
        result.confidence = sum(confidences) / len(confidences)
    return result


_builder: Optional[SchemaContextBuilder] = None


def get_schema_context_builder() -> SchemaContextBuilder:
    global _builder
    if _builder is None:
        _builder = SchemaContextBuilder()
    return _builder


@lru_cache(maxsize=128)
def _cached_block(catalog_version: int, query: str, mode: PromptMode, max_tables: int, samples: bool) -> str:
    ctx = get_schema_context_builder().build(
        query, max_tables=max_tables, include_samples=samples
    )
    return ctx.to_prompt_block(mode)


def get_schema_prompt_block(
    query: str,
    mode: PromptMode = "compact",
    max_tables: int = 6,
    include_samples: bool = False,
) -> str:
    """Cached convenience helper. Cache key includes catalog size as a coarse version."""
    try:
        version = sum(len(e.tables) for e in get_catalog().entries.values())
    except Exception:
        version = 0
    return _cached_block(version, query.strip().lower(), mode, max_tables, include_samples)
