"""Block helpers shared by workflow adapters.

finalize_blocks mirrors orchestration.runners._finish so adapter output matches
composite output exactly: content blocks, then a single caveats block, then a
validation_status block. content_blocks/corpus_id are the pieces pack-style
adapters (delay_claim_pack, delay_briefing) need when aggregating sub-workflow
output.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.orchestration.helpers import caveats_block, validation_block

from .types import WorkflowResult

# Block types that carry a sub-workflow's actual content. A pack aggregates
# these and re-derives caveats/validation once for the whole pack.
CONTENT_TYPES = {"markdown_text", "data_table", "chart", "artifact_link",
                 "html_report_section"}


def content_blocks(wr: WorkflowResult) -> List[dict]:
    """Content blocks of a sub-result (drop its input-summary/caveats/
    validation — the pack aggregates those once)."""
    return [b for b in wr.blocks
            if b.get("type") in CONTENT_TYPES
            and b.get("block_id") != "input_resolution"]


def corpus_id() -> str:
    """Current user's corpus, or "demo" when unavailable."""
    try:
        from src.document_rag import _current_user_corpus
        return _current_user_corpus() or "demo"
    except Exception:
        return "demo"


def finalize_blocks(blocks: List[dict], guards: Dict[str, str],
                    analyst: bool, fallbacks: List[str],
                    caveats: List[str],
                    warnings: Optional[List[str]] = None) -> List[dict]:
    """Append caveats + validation_status blocks (single, at the end)."""
    out = list(blocks)
    cb = caveats_block(caveats, warnings)
    if cb:
        out.append(cb)
    out.append(validation_block(guards, analyst, fallbacks))
    return out
