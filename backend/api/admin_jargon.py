"""Admin endpoints for runtime jargon/glossary management.

GET    /api/admin/jargon         → list built-in + custom terms
POST   /api/admin/jargon         → add a custom term (or update its full_form)
DELETE /api/admin/jargon/{abbr}  → remove a custom term (built-ins protected)
POST   /api/admin/jargon/reload  → reload custom terms from disk

Custom terms persist to ``data/jargon/jargon_custom.json`` so they survive
process restarts.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.jargon_manager import get_jargon_manager


router = APIRouter()


class JargonTermPayload(BaseModel):
    abbreviation: str = Field(..., min_length=1, max_length=64)
    full_form: str = Field(..., min_length=1, max_length=512)
    concept_group: Optional[str] = Field(None, max_length=64)


class JargonTermOut(BaseModel):
    abbreviation: str
    full_form: str
    concept_group: Optional[str] = None


class JargonListResponse(BaseModel):
    builtin_count: int
    custom_count: int
    custom: List[JargonTermOut]
    builtin_sample: List[JargonTermOut]


@router.get("/admin/jargon", response_model=JargonListResponse)
async def list_jargon():
    jm = get_jargon_manager()
    custom_records = jm.list_custom_terms()
    custom_abbrs = {r["abbreviation"] for r in custom_records}

    builtin_sample = [
        JargonTermOut(abbreviation=abbr, full_form=meaning)
        for abbr, meaning in list(jm.BUILTIN_JARGON.items())[:25]
    ]
    custom = [
        JargonTermOut(
            abbreviation=r["abbreviation"],
            full_form=r["full_form"],
            concept_group=r.get("concept_group"),
        )
        for r in custom_records
    ]

    return JargonListResponse(
        builtin_count=len(jm.BUILTIN_JARGON),
        custom_count=len(custom_abbrs),
        custom=custom,
        builtin_sample=builtin_sample,
    )


@router.post("/admin/jargon", response_model=JargonTermOut)
async def add_jargon_term(payload: JargonTermPayload):
    jm = get_jargon_manager()
    try:
        record = jm.add_custom_term(
            abbreviation=payload.abbreviation,
            full_form=payload.full_form,
            concept_group=payload.concept_group,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JargonTermOut(
        abbreviation=record["abbreviation"],
        full_form=record["full_form"],
        concept_group=record.get("concept_group"),
    )


@router.delete("/admin/jargon/{abbreviation}")
async def delete_jargon_term(abbreviation: str):
    jm = get_jargon_manager()
    try:
        removed = jm.remove_custom_term(abbreviation)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not removed:
        raise HTTPException(status_code=404, detail=f"Custom term '{abbreviation}' not found")
    return {"removed": abbreviation.upper()}


@router.post("/admin/jargon/reload")
async def reload_jargon():
    jm = get_jargon_manager()
    count = jm.load_from_disk()
    return {"reloaded": count}
