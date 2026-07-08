"""COAir programme-analysis tools — deterministic engines behind a controlled
tool registry. The LLM never computes schedule metrics: it may only select a
registered tool_id, ask for missing inputs, and narrate a validated ToolResult.
"""

from .executor import known_tool_ids, run_tool
from .registry import REGISTRY, WORKFLOW_ID, match_query
from .schemas import ToolResult

__all__ = ["run_tool", "known_tool_ids", "REGISTRY", "WORKFLOW_ID",
           "match_query", "ToolResult"]
