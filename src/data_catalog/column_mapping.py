"""Concept dictionary + column→concept mapper for the flexible Excel catalog.

The *concept* layer is broader than the three canonical schemas: it maps a raw
(English, possibly abbreviated/synonymous) spreadsheet header to a construction
*concept* (equipment_name, hours, trade, workers, block, date, amount, ...).
Concepts feed the SQL catalog, the SQL planner, the DATA existence-gate and the
canonical-view builder.

Reuses ``schema_profiler.normalize`` and rapidfuzz so there is ONE normalization
+ scoring behaviour across the codebase. Headers are English in production;
a light diacritic fold (already in ``normalize``) keeps loan-term variants
working without being the focus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..schema_profiler import normalize

# Bind a concept to its physical canonical column name (used when a canonical
# VIEW is built in slice 2) and to the table "kind" it implies.
CANONICAL_COLUMN: Dict[str, str] = {
    "equipment_name": "equipment_name",
    "hours": "hours",
    "trade": "trade",
    "workers": "workers",
    "activity": "activity",
    "activity_code": "activity_code",
    "block": "block",
    "floor": "floor",
    "date": "date",
    "unit": "unit",
    "quantity": "quantity",
    "amount": "amount",
    "cumulative_pct": "cumulative_pct",
    "boq_qty": "boq_qty",
    "unit_rate": "unit_rate",
}

# concept → the table kind it signals (for detected_table_kind + compatibility)
CONCEPT_KIND: Dict[str, str] = {
    "equipment_name": "equipment", "hours": "equipment",
    "trade": "manpower", "workers": "manpower",
    "amount": "ipc", "cumulative_pct": "ipc", "boq_qty": "ipc",
    "unit_rate": "ipc", "activity_code": "ipc",
    # shared / neutral concepts carry no strong kind signal
    "block": "", "floor": "", "date": "", "unit": "",
    "quantity": "", "activity": "",
}

# concept → English alias/abbreviation phrases (normalized at match time).
# Exact/alias hit scores 100; fuzzy handles spelling/spacing variants.
CONCEPT_ALIASES: Dict[str, List[str]] = {
    "equipment_name": ["equipment", "equipment name", "equipment type",
                       "plant", "plant name", "asset", "asset name",
                       "machine", "machine name", "machinery", "machinery name"],
    "hours": ["hours", "operating hours", "working hours", "run hours",
              "machine hours", "machinery hours", "estimated machinery hours",
              "estimated hours", "plant hours", "usage hours",
              "utilisation hours", "utilization hours", "utilization",
              "utilisation", "duration", "hrs", "hr", "op hours"],
    "trade": ["trade", "discipline", "craft", "job", "job description",
              "worker type", "labour type", "labor type", "role"],
    "workers": ["workers", "worker count", "manpower", "manpower count",
                "headcount", "head count", "no of men", "number of men",
                "no of workers", "number of workers", "labour", "labor",
                "crew size", "men", "labour count"],
    "activity": ["activity", "activity description", "task", "work description",
                 "operation", "activity desc", "work item description"],
    "activity_code": ["activity code", "code", "item code", "wbs", "boq code",
                      "activity id", "line id", "item no"],
    "block": ["block", "zone", "area", "location", "building", "sector"],
    "floor": ["floor", "level", "storey", "story", "elevation"],
    "date": ["date", "work date", "log date", "day", "record date"],
    "unit": ["unit", "uom", "unit of measure", "measure"],
    "quantity": ["quantity", "qty", "output", "production", "produced qty",
                 "produced quantity", "quantification"],
    "amount": ["amount", "ipc amount", "certified amount", "boq amount",
               "total amount", "contract amount", "total boq amount", "value"],
    "cumulative_pct": ["cumulative", "cumulative percent", "cum percent",
                       "cumulative progress", "total progress", "progress",
                       "cumulative pct", "cum progress"],
    "boq_qty": ["boq qty", "boq quantity", "contract qty", "contract quantity",
                "tender qty", "bill qty"],
    "unit_rate": ["unit rate", "rate", "unit price", "price"],
}

# A raw header binds to a concept only at/above this fuzzy score (0-100).
CONCEPT_MATCH_THRESHOLD = 88.0


@dataclass
class ColumnMapping:
    table_id: str
    raw_column: str
    normalized_column: str
    canonical_concept: Optional[str] = None
    canonical_column: Optional[str] = None
    inferred_type: Optional[str] = None
    confidence: float = 0.0
    source: str = "fuzzy"          # exact | alias | fuzzy | semantic | user_confirmed | admin_confirmed
    requires_confirmation: bool = False

    def to_dict(self) -> Dict:
        return {
            "raw_column": self.raw_column,
            "normalized_column": self.normalized_column,
            "canonical_concept": self.canonical_concept,
            "canonical_column": self.canonical_column,
            "inferred_type": self.inferred_type,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "requires_confirmation": self.requires_confirmation,
        }

    @classmethod
    def from_dict(cls, table_id: str, d: Dict) -> "ColumnMapping":
        return cls(
            table_id=table_id,
            raw_column=d.get("raw_column", ""),
            normalized_column=d.get("normalized_column", ""),
            canonical_concept=d.get("canonical_concept"),
            canonical_column=d.get("canonical_column"),
            inferred_type=d.get("inferred_type"),
            confidence=d.get("confidence", 0.0),
            source=d.get("source", "fuzzy"),
            requires_confirmation=d.get("requires_confirmation", False),
        )


# precomputed normalized alias → concept for O(1) exact hits
_NORM_ALIAS_TO_CONCEPT: Dict[str, str] = {}
for _concept, _aliases in CONCEPT_ALIASES.items():
    for _a in [_concept] + _aliases:
        _NORM_ALIAS_TO_CONCEPT.setdefault(normalize(_a), _concept)


def _score(norm_raw: str, aliases: List[str]) -> float:
    """Best fuzzy score of a normalized header against a concept's aliases.

    Mirrors schema_profiler scoring: exact → 100; token_set damped by
    token-count ratio in both directions (kills 1-2 char subset false 100s);
    multi-word phrase containment for headers ≥4 chars.
    """
    from rapidfuzz import fuzz
    best = 0.0
    raw_tokens = norm_raw.split()
    for cand in aliases:
        c = normalize(cand)
        if not c:
            continue
        if norm_raw == c:
            return 100.0
        ct = c.split()
        ts = fuzz.token_set_ratio(norm_raw, c)
        mn, mx = min(len(ct), len(raw_tokens)), max(len(ct), len(raw_tokens))
        if mx > mn > 0:
            ts *= mn / mx
        s = max(fuzz.ratio(norm_raw, c), ts)
        if len(ct) >= 2 and len(norm_raw) >= 4 and c in norm_raw:
            s = max(s, 95.0)
        best = max(best, s)
    return best


def map_columns_to_concepts(
    table_id: str,
    raw_columns: List[str],
    inferred_types: Optional[Dict[str, str]] = None,
) -> List[ColumnMapping]:
    """Map each raw header to its best concept (>= threshold), else raw-only.

    Conflicts (two headers → same concept) keep the higher score; the loser is
    emitted unmapped (canonical_concept=None) so the raw column is never lost.
    """
    inferred_types = inferred_types or {}
    scored: List[tuple] = []  # (raw, concept, score, source)
    for raw in raw_columns:
        if not str(raw).strip() or raw == "_sheet_name":
            continue
        nr = normalize(raw)
        if not nr:
            continue
        exact = _NORM_ALIAS_TO_CONCEPT.get(nr)
        if exact:
            scored.append((raw, exact, 100.0, "exact"))
            continue
        best_concept, best_score = None, 0.0
        for concept, aliases in CONCEPT_ALIASES.items():
            sc = _score(nr, aliases)
            if sc > best_score:
                best_score, best_concept = sc, concept
        if best_concept and best_score >= CONCEPT_MATCH_THRESHOLD:
            scored.append((raw, best_concept, best_score, "alias"
                           if best_score >= 95 else "fuzzy"))
        else:
            scored.append((raw, None, best_score, "fuzzy"))

    # resolve concept conflicts: highest score wins the concept
    winner: Dict[str, tuple] = {}
    for raw, concept, score, src in scored:
        if concept is None:
            continue
        if concept not in winner or score > winner[concept][2]:
            winner[concept] = (raw, concept, score, src)
    kept = {v[0] for v in winner.values()}

    mappings: List[ColumnMapping] = []
    for raw, concept, score, src in scored:
        eff_concept = concept if (concept and raw in kept) else None
        mappings.append(ColumnMapping(
            table_id=table_id,
            raw_column=raw,
            normalized_column=normalize(raw),
            canonical_concept=eff_concept,
            canonical_column=CANONICAL_COLUMN.get(eff_concept) if eff_concept else None,
            inferred_type=inferred_types.get(raw),
            confidence=round(score / 100.0, 3),
            source=src if eff_concept else "fuzzy",
            requires_confirmation=bool(eff_concept) and score < 95.0,
        ))
    return mappings


def detect_table_kind(mappings: List[ColumnMapping]) -> str:
    """Aggregate mapped concepts into a table kind."""
    from collections import Counter
    kinds = Counter()
    for m in mappings:
        if m.canonical_concept:
            k = CONCEPT_KIND.get(m.canonical_concept, "")
            if k:
                kinds[k] += 1
    if not kinds:
        return "generic"
    return kinds.most_common(1)[0][0]
