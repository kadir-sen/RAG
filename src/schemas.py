"""
Pydantic models for validating LLM-generated structured outputs.
Used to enforce schemas on SQL generation, plan steps, etc.
"""
from typing import List, Optional
from pydantic import BaseModel, field_validator
import re


# ── SQL Generation Output ────────────────────────────────────

class SQLGenerationResult(BaseModel):
    """Schema for LLM-generated SQL output."""
    sql: str
    tables: List[str]
    columns: List[str]
    confidence: float  # 0.0 – 1.0
    notes: str = ""

    @field_validator("sql")
    @classmethod
    def sql_must_be_select(cls, v: str) -> str:
        cleaned = v.strip().rstrip(";").strip()
        if not cleaned.upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed")
        dangerous = [
            r'\bDROP\b', r'\bDELETE\b', r'\bINSERT\b', r'\bUPDATE\b',
            r'\bCREATE\b', r'\bALTER\b', r'\bTRUNCATE\b', r'\bGRANT\b',
            r'\bREVOKE\b', r'\bEXEC\b', r'\bEXECUTE\b', r'\bCALL\b',
            r'\bATTACH\b', r'\bDETACH\b', r'\bCOPY\b', r'\bEXPORT\b',
        ]
        for pattern in dangerous:
            if re.search(pattern, cleaned, re.IGNORECASE):
                raise ValueError(f"Dangerous SQL pattern detected: {pattern}")
        if ";" in cleaned:
            raise ValueError("Multiple SQL statements not allowed")
        return cleaned

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    def validate_tables(self, allowed_tables: List[str]) -> bool:
        """Check that referenced tables exist."""
        allowed_lower = {t.lower() for t in allowed_tables}
        for t in self.tables:
            if t.lower() not in allowed_lower:
                return False
        return True


# ── Plan Step Output ─────────────────────────────────────────

class PlanStepSchema(BaseModel):
    """Schema for a single plan step from LLM."""
    type: str  # sql | document | timeline | combine
    description: str
    instruction: str
    depends_on: List[int] = []

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        allowed = {"sql", "document", "timeline", "combine", "filter"}
        if v.lower() not in allowed:
            raise ValueError(f"Invalid step type: {v}. Must be one of {allowed}")
        return v.lower()


class QueryPlanSchema(BaseModel):
    """Schema for LLM-generated query plan."""
    is_simple: bool
    rationale: str = ""
    steps: List[PlanStepSchema]


# ── LLM Classification Output ───────────────────────────────

class ClassificationResult(BaseModel):
    """Schema for LLM query classification (used only as fallback)."""
    query_type: str
    confidence: float = 0.8
    reason: str = ""

    @field_validator("query_type")
    @classmethod
    def valid_query_type(cls, v: str) -> str:
        allowed = {"DOCUMENT", "DATA", "TIMELINE", "HYBRID"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"Invalid query type: {v}")
        return upper
