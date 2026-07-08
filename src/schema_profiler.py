"""Excel Schema Profiler + Column Mapper.

Maps arbitrary (English, possibly non-canonical) spreadsheet headers onto the
canonical target schemas (equipment_log, manpower_production, ipc_sample) so a
file whose headers don't match verbatim still becomes a first-class SQL table
(canonical column names + ``target_schema`` → deterministic SQL shortcuts and
schema hints activate). Deterministic; **no LLM**.

Pipeline per sheet:
  normalize headers → score each raw header against every canonical field's
  {name + schema aliases + built-in synonyms} (fuzzy + exact) → assign each raw
  header to its best canonical field above a threshold → score each schema by
  required-field coverage → decide confident / clarify / no-match.

Learned/confirmed mappings persist to ``storage/schema_mappings.json`` keyed by
a normalized header signature, so repeat uploads (and manual corrections)
resolve instantly and identically.

Synonyms are English-first (production files are English); a light Unicode
diacritic fold is applied during normalization so accented variants of the same
English/loan term still line up.
"""

from __future__ import annotations

import json
import logging
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import SCHEMAS_DIR

logger = logging.getLogger(__name__)

# Persisted, confirmed header→schema mappings (signature → {schema_id, column_map}).
_MAPPINGS_FILE = Path(SCHEMAS_DIR).parent / "schema_mappings.json"

# A raw header is bound to a canonical field only at/above this fuzzy score
# (0-100). An exact synonym/alias hit scores 100; this mainly admits spelling
# and spacing variants ("no. of workers", "manpwr").
COLUMN_MATCH_THRESHOLD = 88.0
# Schema-level required-field coverage bands.
CONFIDENT_COVERAGE = 0.7    # ≥ → assign the schema outright
CLARIFY_FLOOR = 0.4         # [floor, confident) → ambiguous, ask the user
# below CLARIFY_FLOOR → no match (raw table, no target_schema)

# Built-in English synonyms beyond each schema's own JSON aliases. Keyed by the
# canonical column name exactly as it appears in storage/schemas/*.json. A few
# common non-English construction loan-terms are included so the documented
# mismatch cases resolve, but the emphasis is English variants.
_SYNONYMS: Dict[str, List[str]] = {
    # equipment_log
    "Date": ["work date", "day", "log date", "tarih"],
    "Block": ["building", "zone", "blok"],
    "Floor": ["level", "storey", "story", "elevation", "kat"],
    "Machinery Name": ["machine", "machine name", "equipment", "equipment name",
                       "plant", "plant name", "asset", "machinery",
                       "makine", "makine adi", "makina"],
    "Estimated Machinery Hours": ["hours", "operating hours", "working hours",
                                  "machine hours", "run hours", "usage hours",
                                  "utilisation hours", "utilization hours",
                                  "plant hours", "calisma saati", "saat"],
    # manpower_production
    "Activity Description": ["activity", "task", "work description", "work item",
                             "operation", "activity desc"],
    "Job Description": ["trade", "job", "craft", "worker type", "role",
                        "discipline", "labour type", "labor type", "meslek"],
    "Number of Workers": ["workers", "worker count", "manpower", "manpower count",
                          "headcount", "labour", "labor", "no of workers",
                          "number of labour", "crew size", "isci", "isci sayisi",
                          "personel"],
    "Quantification": ["quantity", "qty", "output", "production", "produced qty",
                       "produced quantity", "miktar"],
    "Unit of Measure": ["unit", "uom", "measure", "birim"],
    # ipc_sample
    "Activity Code": ["code", "item code", "wbs", "activity id", "boq code"],
    "Activity Name": ["activity", "item name", "work item", "description",
                      "boq description"],
    "Unit": ["uom", "unit of measure", "measure"],
    "BOQ Qty": ["boq quantity", "contract qty", "contract quantity",
                "tender qty"],
    "Unit Rate": ["rate", "unit price", "price"],
    "Total BOQ Amount": ["amount", "boq amount", "total amount",
                         "contract amount", "ipc amount", "certified amount"],
    "Previous %": ["previous percent", "prev %", "previous progress"],
    "Current %": ["current percent", "curr %", "current progress"],
    "Cumulative %": ["cumulative", "cumulative percent", "cum %",
                     "total progress", "cumulative progress", "progress"],
    "Cumulative Amount": ["cumulative amount", "cum amount", "total certified"],
}


# ── Normalization ───────────────────────────────────────────

# Turkish dotless-i and friends that NFKD does not fold to ASCII.
_CHAR_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
})


def normalize(name: str) -> str:
    """Lowercase, fold accents/diacritics, drop punctuation, collapse spaces."""
    if name is None:
        return ""
    s = str(name).translate(_CHAR_FOLD)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else " ")
    return " ".join("".join(out).split())


# ── Result types ────────────────────────────────────────────

@dataclass
class ColumnMatch:
    raw: str
    canonical: str
    score: float


@dataclass
class ProfileResult:
    schema_id: Optional[str] = None          # confident assignment, else None
    confidence: float = 0.0                  # required-field coverage 0..1
    column_map: Dict[str, str] = field(default_factory=dict)  # raw → canonical
    matched_required: List[str] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    needs_clarification: bool = False
    candidates: List[Tuple[str, float]] = field(default_factory=list)  # (schema_id, coverage)
    source: str = "computed"                 # "computed" | "persisted"


# ── Profiler ────────────────────────────────────────────────

class SchemaProfiler:
    def __init__(self, schemas_registry=None):
        # Lazy import avoids a cycle with schema_converter at module load.
        if schemas_registry is None:
            from .schema_converter import get_target_schemas
            schemas_registry = get_target_schemas()
        self.schemas = schemas_registry
        self._persist_lock = threading.Lock()
        self._persisted = self._load_persisted()

    # -- candidate strings per canonical field ----------------
    def _field_candidates(self, col_def) -> List[str]:
        cands = [col_def.name]
        cands.extend(col_def.aliases or [])
        cands.extend(_SYNONYMS.get(col_def.name, []))
        # normalized, de-duplicated, non-empty
        seen, out = set(), []
        for c in cands:
            n = normalize(c)
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    def _score_raw_to_field(self, norm_raw: str, candidates: List[str]) -> float:
        from rapidfuzz import fuzz
        best = 0.0
        raw_tokens = norm_raw.split()
        for cand in candidates:
            if norm_raw == cand:
                return 100.0
            cand_tokens = cand.split()
            # ratio is length-sensitive; token_set tolerates word-order/extra
            # words but returns 100 whenever the smaller token set is a *subset*
            # of the larger ("machinery" ⊂ "estimated machinery hours", or "no" ⊂
            # "no of workers"), so damp it by the token-count ratio in EITHER
            # direction. Legit single-word synonyms still score 100 via exact hits.
            ts = fuzz.token_set_ratio(norm_raw, cand)
            mn = min(len(cand_tokens), len(raw_tokens))
            mx = max(len(cand_tokens), len(raw_tokens))
            if mx > mn > 0:
                ts *= mn / mx
            s = max(fuzz.ratio(norm_raw, cand), ts)
            # A full multi-word candidate phrase appearing verbatim in the header
            # is strong ("total manpower count on site" ⊇ "manpower count"). Only
            # this direction — the reverse (header ⊂ candidate) lets a 1-char
            # header like "m" falsely match "machine name" by substring.
            if len(cand_tokens) >= 2 and len(norm_raw) >= 4 and cand in norm_raw:
                s = max(s, 95.0)
            best = max(best, s)
        return best

    def _map_columns(self, columns: List[str], schema) -> Dict[str, ColumnMatch]:
        """Best canonical field per raw column for one schema (conflicts → higher score wins)."""
        field_cands = {c.name: self._field_candidates(c) for c in schema.columns}
        # assignment[canonical] = ColumnMatch (winner among competing raw cols)
        assignment: Dict[str, ColumnMatch] = {}
        for raw in columns:
            nr = normalize(raw)
            if not nr:
                continue
            best_field, best_score = None, 0.0
            for cdef in schema.columns:
                sc = self._score_raw_to_field(nr, field_cands[cdef.name])
                if sc > best_score:
                    best_score, best_field = sc, cdef.name
            if best_field is None or best_score < COLUMN_MATCH_THRESHOLD:
                continue
            prev = assignment.get(best_field)
            if prev is None or best_score > prev.score:
                assignment[best_field] = ColumnMatch(raw=raw, canonical=best_field,
                                                     score=best_score)
        return assignment

    def _profile_schema(self, columns: List[str], schema):
        assignment = self._map_columns(columns, schema)
        required = [c.name for c in schema.columns if c.required]
        matched_req = [r for r in required if r in assignment]
        coverage = (len(matched_req) / len(required)) if required else 0.0
        column_map = {m.raw: m.canonical for m in assignment.values()}
        return coverage, matched_req, required, column_map

    def profile(self, columns: List[str]) -> ProfileResult:
        """Profile a sheet's raw headers against all canonical schemas."""
        columns = [c for c in (columns or []) if str(c).strip()]
        if not columns:
            return ProfileResult()

        # Persisted, previously-confirmed mapping wins (stable + hand-correctable).
        persisted = self._match_persisted(columns)
        if persisted is not None:
            return persisted

        scored = []
        best = None
        for info in self.schemas.list_schemas():
            schema = self.schemas.get_schema(info["schema_id"])
            if not schema:
                continue
            coverage, matched_req, required, column_map = self._profile_schema(columns, schema)
            if coverage <= 0:
                continue
            scored.append((schema.schema_id, coverage))
            cand = ProfileResult(
                schema_id=schema.schema_id, confidence=round(coverage, 3),
                column_map=column_map, matched_required=matched_req,
                missing_required=[r for r in required if r not in matched_req],
            )
            if best is None or coverage > best.confidence:
                best = cand

        if best is None:
            return ProfileResult(candidates=[])

        best.candidates = sorted(scored, key=lambda x: -x[1])
        if best.confidence >= CONFIDENT_COVERAGE:
            best.needs_clarification = False
        elif best.confidence >= CLARIFY_FLOOR:
            best.needs_clarification = True
        else:
            # Too weak to assign a schema, but keep the column_map for visibility.
            best.needs_clarification = True
            best.schema_id = None
        return best

    # -- persistence ------------------------------------------
    @staticmethod
    def _signature(columns: List[str]) -> str:
        return "|".join(sorted(normalize(c) for c in columns if str(c).strip()))

    def _load_persisted(self) -> Dict[str, dict]:
        try:
            if _MAPPINGS_FILE.exists():
                return json.loads(_MAPPINGS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[SchemaProfiler] could not read mappings: {e}")
        return {}

    def _match_persisted(self, columns: List[str]) -> Optional[ProfileResult]:
        rec = self._persisted.get(self._signature(columns))
        if not rec:
            return None
        return ProfileResult(
            schema_id=rec.get("schema_id"),
            confidence=rec.get("confidence", 1.0),
            column_map=dict(rec.get("column_map", {})),
            matched_required=list(rec.get("matched_required", [])),
            missing_required=list(rec.get("missing_required", [])),
            needs_clarification=bool(rec.get("needs_clarification", False)),
            source="persisted",
        )

    def persist_mapping(self, columns: List[str], result: ProfileResult) -> None:
        """Remember a (confirmed) mapping so identical headers resolve identically."""
        sig = self._signature(columns)
        rec = {
            "schema_id": result.schema_id,
            "confidence": result.confidence,
            "column_map": result.column_map,
            "matched_required": result.matched_required,
            "missing_required": result.missing_required,
            "needs_clarification": result.needs_clarification,
        }
        with self._persist_lock:
            self._persisted[sig] = rec
            try:
                _MAPPINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
                _MAPPINGS_FILE.write_text(
                    json.dumps(self._persisted, indent=2, ensure_ascii=False),
                    encoding="utf-8")
            except Exception as e:
                logger.warning(f"[SchemaProfiler] could not persist mapping: {e}")


_PROFILER: Optional[SchemaProfiler] = None


def get_profiler() -> SchemaProfiler:
    global _PROFILER
    if _PROFILER is None:
        _PROFILER = SchemaProfiler()
    return _PROFILER
