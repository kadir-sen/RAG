"""Chat-native response blocks — the structured pieces a single assistant
message may be composed of (markdown, tables, charts, sanitized HTML report
sections, caveats, validation badges, clarifications, artifact links).

Blocks are ADDITIVE to ChatResponse: legacy answers carry no blocks and render
exactly as before. Every block is validated here before it reaches the
frontend (response-contract guard): invalid blocks are dropped with a reason,
never a 500.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, field_validator

BLOCK_TYPES = (
    "markdown_text", "data_table", "chart", "html_report_section",
    "artifact_link", "caveats", "validation_status", "clarification",
)

# Serialized-size ceiling for a whole block list (bytes, defensive).
MAX_BLOCKS_BYTES = 2_000_000


class MarkdownTextBlock(BaseModel):
    type: Literal["markdown_text"]
    block_id: str = ""
    text: str

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("empty markdown text")
        return v


class DataTableBlock(BaseModel):
    type: Literal["data_table"]
    block_id: str = ""
    title: str = ""
    columns: List[str]
    rows: List[List[Any]]
    caption: str = ""

    @field_validator("rows")
    @classmethod
    def _row_width(cls, v, info):
        cols = info.data.get("columns") or []
        for r in v:
            if len(r) != len(cols):
                raise ValueError("row width does not match columns")
        return v


class ChartSeries(BaseModel):
    name: str
    points: List[Dict[str, Any]]  # {x, y, marker?}


class ChartBlock(BaseModel):
    type: Literal["chart"]
    block_id: str = ""
    chart_type: Literal["line", "bar"]
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    # line charts:
    series: Optional[List[ChartSeries]] = None
    # bar charts:
    categories: Optional[List[str]] = None
    values: Optional[List[float]] = None

    @field_validator("values")
    @classmethod
    def _bar_shape(cls, v, info):
        cats = info.data.get("categories")
        if v is not None and cats is not None and len(v) != len(cats):
            raise ValueError("values/categories length mismatch")
        return v


class HtmlReportSectionBlock(BaseModel):
    type: Literal["html_report_section"]
    block_id: str = ""
    title: str = ""
    html: str
    fallback_markdown: str
    sanitized: Literal[True]  # unsanitized HTML is not a valid block

    @field_validator("fallback_markdown")
    @classmethod
    def _fallback_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("html block requires a markdown fallback")
        return v


class ArtifactLinkBlock(BaseModel):
    type: Literal["artifact_link"]
    block_id: str = ""
    url: str
    filename: str
    kind: str = "file"

    @field_validator("url")
    @classmethod
    def _artifact_url_only(cls, v: str) -> str:
        if not v.startswith("/api/artifacts/"):
            raise ValueError("artifact url must be under /api/artifacts/")
        return v


class CaveatsBlock(BaseModel):
    type: Literal["caveats"]
    block_id: str = ""
    caveats: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ValidationStatusBlock(BaseModel):
    type: Literal["validation_status"]
    block_id: str = ""
    guards: Dict[str, str] = Field(default_factory=dict)
    # values: passed | failed | fallback | skipped
    requires_analyst_review: bool = False
    fallbacks_used: List[str] = Field(default_factory=list)


class ClarificationBlock(BaseModel):
    type: Literal["clarification"]
    block_id: str = ""
    question: str
    options: List[Dict[str, str]] = Field(default_factory=list)  # {label, value}


_MODELS = {
    "markdown_text": MarkdownTextBlock,
    "data_table": DataTableBlock,
    "chart": ChartBlock,
    "html_report_section": HtmlReportSectionBlock,
    "artifact_link": ArtifactLinkBlock,
    "caveats": CaveatsBlock,
    "validation_status": ValidationStatusBlock,
    "clarification": ClarificationBlock,
}


def validate_blocks(raw_blocks: Any) -> Tuple[List[dict], List[str]]:
    """Response-contract guard: validate/normalize a raw block list.

    Returns (valid_block_dicts, dropped_reasons). Rules:
      * unknown/invalid blocks are dropped with a reason (never raised);
      * a clarification block is exclusive — if present, only the first
        clarification survives;
      * whole-list serialized size is capped.
    """
    import json

    valid: List[dict] = []
    dropped: List[str] = []
    if not isinstance(raw_blocks, list):
        return [], (["blocks payload was not a list"] if raw_blocks else [])

    for i, raw in enumerate(raw_blocks):
        if not isinstance(raw, dict):
            dropped.append(f"block[{i}]: not an object")
            continue
        btype = raw.get("type")
        model = _MODELS.get(btype)
        if model is None:
            dropped.append(f"block[{i}]: unknown type '{btype}'")
            continue
        try:
            blk = model(**raw)
        except ValidationError as e:
            first = e.errors()[0]
            dropped.append(f"block[{i}] ({btype}): {first.get('msg', 'invalid')}")
            continue
        d = blk.model_dump()
        if not d.get("block_id"):
            d["block_id"] = f"b{i + 1}"
        valid.append(d)

    # Clarification exclusivity: it replaces everything else.
    clarifications = [b for b in valid if b["type"] == "clarification"]
    if clarifications:
        if len(valid) > 1:
            dropped.append("clarification block is exclusive; other blocks dropped")
        valid = clarifications[:1]

    try:
        if len(json.dumps(valid, ensure_ascii=False)) > MAX_BLOCKS_BYTES:
            dropped.append("blocks payload exceeded size cap; truncated")
            while valid and len(json.dumps(valid, ensure_ascii=False)) > MAX_BLOCKS_BYTES:
                removed = valid.pop()
                dropped.append(f"dropped oversized tail block '{removed.get('block_id')}'")
    except (TypeError, ValueError) as e:
        return [], [f"blocks not serializable: {e}"]

    return valid, dropped
