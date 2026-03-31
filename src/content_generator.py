"""
Content Generator - Text generation utilities for documents and correspondence.

Includes:
- summarize_document(): LLM-based or truncation document summaries
- summarize_table(): Pandas-based table summaries (no LLM)
- draft_reply(): LLM-based correspondence draft generation
"""
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from .logger import logger


# ── Document & Table Summaries ──────────────────────────────

def summarize_document(
    doc_text_by_page: Dict[int, str],
    file_name: str,
    *,
    max_chars: int = 200,
) -> str:
    """
    Generate a 2-3 sentence summary for a document.

    Short text (<500 chars total) -> first 200 chars as summary.
    Longer text -> LLM-generated summary via llm_client.
    """
    full_text = "\n".join(
        doc_text_by_page[p] for p in sorted(doc_text_by_page.keys())
    ).strip()

    if not full_text:
        return ""

    # Short text: use truncation
    if len(full_text) < 500:
        summary = full_text[:max_chars].strip()
        if len(full_text) > max_chars:
            summary += "..."
        return summary

    # Longer text: use LLM
    try:
        from . import llm_client

        # Take first 3000 chars to keep costs low
        excerpt = full_text[:3000]

        prompt = (
            f"Summarize this construction document in 2-3 sentences. "
            f"Include: document type, sender/recipient if present, key topic, "
            f"and any actions or deadlines mentioned.\n\n"
            f"Document: {file_name}\n\n"
            f"Content:\n{excerpt}"
        )

        resp = llm_client.generate_text(
            prompt,
            system="You are a construction document summarizer. Be concise and factual.",
            max_tokens=256,
        )
        if resp and resp.text:
            return resp.text.strip()
    except Exception as e:
        logger.warning(f"[SummaryGen] LLM summary failed for {file_name}: {e}")

    # Fallback: truncation
    return full_text[:max_chars].strip() + "..."


def summarize_table(
    df: pd.DataFrame,
    schema_id: str,
    file_name: str,
) -> str:
    """
    Generate a summary for an Excel/table file using pandas analysis (no LLM).

    Includes: schema type, date range, row count, unique block/activity counts.
    """
    SCHEMA_NAMES = {
        "equipment_log": "Equipment Log",
        "ipc_sample": "IPC (Interim Progress Certificate)",
        "manpower_production": "Manpower Production Log",
    }

    parts = [SCHEMA_NAMES.get(schema_id, schema_id)]

    # Date range
    date_cols = [c for c in df.columns if "date" in c.lower()]
    for col in date_cols:
        dates = pd.to_datetime(df[col], errors="coerce").dropna()
        if not dates.empty:
            min_d, max_d = dates.min(), dates.max()
            if min_d.month == max_d.month and min_d.year == max_d.year:
                parts.append(min_d.strftime("%B %Y"))
            else:
                parts.append(f"{min_d.strftime('%B %Y')} - {max_d.strftime('%B %Y')}")
            break

    parts.append(f"{len(df)} rows")

    # Schema-specific details
    if schema_id == "equipment_log":
        mach_col = _find(df, ["Machinery Name", "machinery_name"])
        if mach_col:
            n = df[mach_col].dropna().nunique()
            parts.append(f"{n} unique machinery types")

    elif schema_id == "manpower_production":
        act_col = _find(df, ["Activity Description", "activity_description"])
        if act_col:
            n = df[act_col].dropna().nunique()
            parts.append(f"{n} unique activities")
        workers_col = _find(df, ["Number of Workers", "number_of_workers"])
        if workers_col:
            total = pd.to_numeric(df[workers_col], errors="coerce").sum()
            parts.append(f"{int(total)} total worker-days")

    elif schema_id == "ipc_sample":
        code_col = _find(df, ["Activity Code", "activity_code"])
        if code_col:
            n = df[code_col].dropna().nunique()
            parts.append(f"{n} activity items")

    # Block info
    block_col = _find(df, ["Block", "block"])
    if block_col:
        blocks = df[block_col].dropna().unique()
        if len(blocks) > 0:
            block_list = ", ".join(str(b) for b in blocks[:5])
            parts.append(f"blocks: {block_list}")

    # Source file
    parts.append(f"from {Path(file_name).stem}")

    summary = " | ".join(parts)
    logger.info(f"[SummaryGen] Table summary: {summary}")
    return summary


def _find(df: pd.DataFrame, candidates: list) -> Optional[str]:
    """Find first matching column name."""
    lower_map = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand in df.columns:
            return cand
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


# ── Draft Response Generation ───────────────────────────────

def draft_reply(
    thread: "CorrespondenceThread",
    instruction: str = "",
    our_company: str = "",
) -> str:
    """
    Generate a draft reply to the latest message in a correspondence thread.

    Uses the thread history + detected actions + user instruction to produce
    a formal construction correspondence draft.
    """
    if not thread.messages:
        return "No messages found in this thread to reply to."

    last_msg = thread.messages[-1]

    # Build chronological correspondence flow
    flow_parts = []
    for msg in thread.messages:
        flow_parts.append(f"  {msg.date}: {msg.sender} → {msg.recipient} | {msg.subject}")
    flow_description = "\n".join(flow_parts)

    # Build thread summary for context (last 5 messages with previews)
    thread_summary_parts = []
    for msg in thread.messages[-5:]:
        actions_str = ""
        if msg.actions:
            actions_str = f" [Actions: {', '.join(msg.actions)}]"
        thread_summary_parts.append(
            f"- {msg.date} | {msg.sender} -> {msg.recipient}: "
            f"{msg.subject}{actions_str}"
        )
        if msg.body_preview:
            thread_summary_parts.append(f"  Preview: {msg.body_preview[:200]}")

    thread_summary = "\n".join(thread_summary_parts)

    # Build actions list
    all_actions = []
    for msg in thread.messages:
        all_actions.extend(msg.actions)
    actions_context = ""
    if all_actions:
        actions_context = f"\n\nPending actions identified in thread:\n" + "\n".join(
            f"- {a}" for a in all_actions[-10:]
        )

    # Build instruction
    instruction_text = ""
    if instruction:
        instruction_text = f"\n\nUser instruction for the draft: {instruction}"

    reply_as = our_company or thread.party_a or "Our Company"
    reply_to = last_msg.sender or thread.party_b or "the sender"

    prompt = (
        f"Generate a formal construction correspondence reply to the latest message "
        f"in this thread.\n\n"
        f"CORRESPONDENCE FLOW (chronological):\n{flow_description}\n\n"
        f"You are replying AS {reply_as} TO {reply_to}.\n"
        f"The last message was FROM {last_msg.sender} on {last_msg.date}.\n"
        f"Subject: {last_msg.subject}\n\n"
        f"Thread history (recent messages with previews):\n{thread_summary}"
        f"{actions_context}"
        f"{instruction_text}\n\n"
        f"Write a professional, formal reply addressing the points raised in the "
        f"latest message. Include reference numbers if available. Keep the tone "
        f"formal and appropriate for construction industry correspondence."
    )

    system = (
        "You are a construction project correspondence assistant. "
        "You write formal letters and replies in standard construction "
        "industry format. Be concise, professional, and address all "
        "action items mentioned. Use proper letter formatting with "
        "reference, subject, salutation, body, and closing."
    )

    try:
        from . import llm_client

        resp = llm_client.generate_text(
            prompt,
            system=system,
            max_tokens=1024,
        )
        if resp and resp.text:
            logger.info(f"[DraftResponse] Generated reply for thread "
                        f"{thread.party_a} <-> {thread.party_b}")
            return resp.text.strip()
    except Exception as e:
        logger.error(f"[DraftResponse] Generation failed: {e}")
        return f"Draft generation failed: {e}"

    return "Could not generate draft reply."


def summarize_thread(
    thread: "CorrespondenceThread",
) -> str:
    """
    Generate a chronological summary of a correspondence thread.

    Highlights key decisions, action items, and unresolved issues.
    """
    if not thread.messages:
        return "No messages found in this thread to summarize."

    context_parts = [
        f"Summarize this email correspondence thread between "
        f"{thread.party_a} and {thread.party_b}:\n"
    ]

    for msg in thread.messages:
        entry = f"[{msg.date}] {msg.sender or 'Unknown'} → {msg.recipient or 'Unknown'}\n"
        entry += f"Subject: {msg.subject}\n"
        if msg.body_preview:
            entry += f"Content: {msg.body_preview}\n"
        if msg.actions:
            entry += f"Actions: {', '.join(msg.actions)}\n"
        context_parts.append(entry)

    prompt = "\n".join(context_parts)

    system = (
        "You are a construction project correspondence analyst. "
        "Summarize the thread chronologically, highlighting key decisions, "
        "action items, and unresolved issues. Be concise and factual."
    )

    try:
        from . import llm_client

        resp = llm_client.generate_text(
            prompt,
            system=system,
            max_tokens=1024,
        )
        if resp and resp.text:
            logger.info(f"[ThreadSummary] Generated summary for "
                        f"{thread.party_a} <-> {thread.party_b}")
            return resp.text.strip()
    except Exception as e:
        logger.error(f"[ThreadSummary] Summary generation failed: {e}")
        return f"Summary generation failed: {e}"

    return "Could not generate thread summary."
