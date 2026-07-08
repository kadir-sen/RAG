"""COAir delay-report tools — forensic delay-event chronology sections.

Claim-report-style output ("6.1.13 On 19 July 2023, JAMED raised concerns...")
built from correspondence evidence: LLM extracts, deterministic containment
guards validate, pure Python orders and numbers, a guarded narrative ships —
and the data always survives guard failures via the deterministic fallback.
"""

from .handler import run_event_chronology
from .registry import REGISTRY, match_query

__all__ = ["run_event_chronology", "REGISTRY", "match_query"]
