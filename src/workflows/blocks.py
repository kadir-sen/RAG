"""Block-finalization shared by workflow adapters.

Mirrors orchestration.runners._finish so adapter output matches composite
output exactly: content blocks, then a single caveats block, then a
validation_status block.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.orchestration.helpers import caveats_block, validation_block


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
