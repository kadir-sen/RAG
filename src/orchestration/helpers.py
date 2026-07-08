"""Shared block-building helpers for composite runners."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def md_block(text: str, block_id: str = "") -> dict:
    return {"type": "markdown_text", "block_id": block_id, "text": text}


def table_block(table: Dict[str, Any], block_id: str = "") -> dict:
    return {"type": "data_table", "block_id": block_id,
            "title": table.get("title", ""),
            "columns": table.get("columns", []),
            "rows": table.get("rows", []),
            "caption": table.get("caption", "")}


def caveats_block(caveats: List[str], warnings: List[str] | None = None,
                  block_id: str = "caveats") -> Optional[dict]:
    caveats = [c for c in (caveats or []) if c]
    warnings = [w for w in (warnings or []) if w]
    if not caveats and not warnings:
        return None
    return {"type": "caveats", "block_id": block_id,
            "caveats": caveats, "warnings": warnings}


def validation_block(guards: Dict[str, str], analyst: bool,
                     fallbacks: List[str], block_id: str = "validation") -> dict:
    return {"type": "validation_status", "block_id": block_id,
            "guards": guards, "requires_analyst_review": bool(analyst),
            "fallbacks_used": fallbacks}


def artifact_blocks(tool_result: Dict[str, Any]) -> List[dict]:
    out = []
    for a in tool_result.get("artifacts") or []:
        url = a.get("url") or ""
        if url.startswith("/api/artifacts/"):
            out.append({"type": "artifact_link", "block_id": a.get("artifact_id", ""),
                        "url": url, "filename": a.get("filename", "artifact"),
                        "kind": a.get("kind", "file")})
    return out


def clarification_result(intent_id: str, question: str,
                         options: List[Dict[str, str]] | None = None):
    from .schemas import CompositeResult
    return CompositeResult(
        intent_id=intent_id, status="needs_clarification",
        blocks=[{"type": "clarification", "block_id": "clarify",
                 "question": question, "options": options or []}],
        answer=question,
    )


def tool_result_guard_statuses(tool_result: Dict[str, Any]) -> Dict[str, str]:
    """Map a ToolResult.validation audit dict onto block guard statuses."""
    guards: Dict[str, str] = {}
    v = tool_result.get("validation") or {}
    comp = v.get("computation_guard") or {}
    if comp:
        guards["computation_guard"] = (
            "passed" if comp.get("pre") != "failed" and comp.get("post") == "passed"
            else "failed")
    narr = v.get("narrative_guard") or {}
    if narr:
        status = narr.get("status", "")
        guards["narrative_guard"] = (
            "passed" if status in ("approved", "rewritten_then_approved")
            else "fallback" if status in ("fallback_after_rejection",
                                          "llm_unavailable",
                                          "deterministic_only")
            else "failed")
    return guards
