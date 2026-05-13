"""Usage / budget endpoints — exposes the global LLM cost counter."""

from fastapi import APIRouter

from src.usage_tracker import get_snapshot, reset_usage

router = APIRouter()


@router.get("/usage")
def read_usage() -> dict:
    """Return the application-wide usage snapshot."""
    snap = get_snapshot()
    return {
        "used_usd": snap.used_usd,
        "limit_usd": snap.limit_usd,
        "remaining_usd": snap.remaining_usd,
        "remaining_pct": snap.remaining_pct,
        "over_budget": snap.over_budget,
        "prompt_tokens": snap.prompt_tokens,
        "completion_tokens": snap.completion_tokens,
        "total_tokens": snap.total_tokens,
        "total_calls": snap.total_calls,
    }


@router.post("/usage/reset")
def reset_usage_counter() -> dict:
    """Reset the global usage counter. Admin operation."""
    snap = reset_usage()
    return {
        "used_usd": snap.used_usd,
        "limit_usd": snap.limit_usd,
        "remaining_usd": snap.remaining_usd,
        "remaining_pct": snap.remaining_pct,
        "over_budget": snap.over_budget,
        "prompt_tokens": snap.prompt_tokens,
        "completion_tokens": snap.completion_tokens,
        "total_tokens": snap.total_tokens,
        "total_calls": snap.total_calls,
    }
