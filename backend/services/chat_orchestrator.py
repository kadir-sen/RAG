"""Replaces app.py handle_input() — conversation memory + routing + response contract."""

import asyncio
import re
from datetime import datetime
from typing import List, Optional

from src.router import QueryRouter
from src.conversation_store import ConversationStore, Message, format_chat_context
from src.config import LLM_PROVIDERS, ENABLE_DUAL_PROVIDER, CHAT_MEMORY_MESSAGES, CHAT_MEMORY_MAX_CHARS

from backend.services.response_builder import build_chat_response
from backend.models.responses import ChatResponse, QuotaInfo


class ChatOrchestrator:

    @staticmethod
    def _serialize_response_sources(response: ChatResponse, query_type: str) -> list | None:
        """Persist enough source metadata to rebuild the UI response on reload.

        IMPORTANT: The stored format must match what _extract_citations_and_related()
        expects on reload: file_name (not doc_name), page_number (not anchor),
        text_snippet (not snippet), subject (not reason).
        """
        import re
        sources: list[dict] = []

        if response.citations:
            for c in response.citations:
                item = c.model_dump()
                # Map Citation model fields → raw source fields for round-trip
                item["file_name"] = item.pop("doc_name", "")
                anchor = item.pop("anchor", "")
                match = re.search(r"page_(\d+)", anchor)
                item["page_number"] = int(match.group(1)) if match else 1
                item["text_snippet"] = item.pop("snippet", "")
                sources.append(item)

        if response.related_docs:
            if query_type == "thread":
                related_type = "thread_message"
            elif query_type == "file_list":
                related_type = "search_result"
            else:
                related_type = "notice"

            for doc in response.related_docs:
                item = doc.model_dump()
                item["type"] = related_type
                # Map RelatedDoc model fields → raw source fields for round-trip
                item["file_name"] = item.pop("doc_name", "")
                item["subject"] = item.pop("reason", "")
                sources.append(item)

        return sources or None

    async def process(
        self,
        query: str,
        conversation_id: str,
        router: QueryRouter,
        store: ConversationStore,
        doc_ids: list | None = None,
        email_ids: list | None = None,
        mode: str | None = None,
        username: str | None = None,
        request_id: str | None = None,
    ) -> ChatResponse:
        now = datetime.now().isoformat()

        # Live activity feed: stamp the request_id on a contextvar (propagates
        # into the query worker thread via asyncio.to_thread, same as corpus_var)
        # so deep router/agent code can publish progress steps the client polls.
        from backend.tasks.query_progress import query_progress, query_request_var
        import uuid as _uuid
        request_id = request_id or _uuid.uuid4().hex[:12]
        query_request_var.set(request_id)
        query_progress.start(request_id)

        # 1. Save user message
        user_msg = Message(role="user", content=query, timestamp=now)
        store.add_message(conversation_id, user_msg)

        # 2. Build context-augmented query from recent messages
        recent = store.get_recent_messages(conversation_id, CHAT_MEMORY_MESSAGES)
        context_msgs = recent[:-1] if recent else []
        context = format_chat_context(
            context_msgs, CHAT_MEMORY_MESSAGES, CHAT_MEMORY_MAX_CHARS
        )
        augmented = f"{context}\n\nCurrent question: {query}" if context else query

        # Capture the user's EXPLICIT selection (before the conversation-scoped
        # fallback below) so we can inject the selected docs' full text directly.
        explicit_doc_ids = list(doc_ids) if doc_ids else []

        # 3. Build email context for correspondence mode (email files only)
        if email_ids:
            email_context = self._build_email_context(email_ids)
            if email_context:
                augmented = f"{email_context}\n\n{augmented}"
                # Also scope doc_ids to selected emails for RAG
                if not doc_ids:
                    doc_ids = email_ids

        # 3b. Inject the full OCR/extracted text of explicitly selected NON-email
        # documents (PDF/DOCX/TXT) directly into the prompt. Covers general doc
        # selection and PDF "conversations" picked in correspondence mode (those
        # are not .eml/.msg, so the email path skips them and they land here).
        doc_context = self._build_document_context(
            list(dict.fromkeys((email_ids or []) + explicit_doc_ids))
        )
        if doc_context:
            augmented = f"{doc_context}\n\n{augmented}"

        # 4. Route and execute in thread pool (src/ code is synchronous)
        if not doc_ids:
            doc_ids = store.get_document_ids(conversation_id) or None

        # Per-user contextvars: stamp the user's corpus AND identity on contextvars
        # in THIS async task so they propagate into the query worker thread via
        # asyncio.to_thread. The auth dependency (sync → FastAPI threadpool) sets
        # these in a DIFFERENT context that never reaches here, so without this:
        #  - corpus_var would be unset → retrieval/timeline lose corpus scope;
        #  - current_user_var would be None → llm_client can't attribute tokens to
        #    the user, so used_tokens stays 0 and the quota bar is stuck at 100%.
        try:
            from src.document_rag import corpus_var
            from backend.core.security import current_user_var, UserContext
            _corpus = ""
            if username:
                from src.user_store import get_user_store
                _u = get_user_store().get_user(username)
                if _u:
                    _corpus = str((_u.get("features") or {}).get("corpus") or "").lower()
                    current_user_var.set(UserContext(
                        username=_u["username"],
                        role=_u.get("role", "user"),
                        display_name=_u.get("display_name", _u["username"]),
                        features=_u.get("features", {}) or {},
                        token_limit=_u.get("token_limit", 0),
                    ))
            corpus_var.set(_corpus)
        except Exception:
            pass

        # 3c. Draft enrichment: when composing a REPLY to selected emails, gather
        # supporting facts from the user's OWN project documents (corpus-scoped RAG
        # — corpus_var is set above, so no cross-corpus leak) so the draft can cite
        # contract terms / costs / prior decisions, not just the emails. Conversation
        # state is already in `augmented` (step 2).
        if email_ids and self._is_draft_intent(query):
            support = self._build_draft_support_context(query)
            if support:
                augmented = f"{augmented}\n\n{support}"

        is_dual = ENABLE_DUAL_PROVIDER and len(LLM_PROVIDERS) >= 2
        try:
            if is_dual:
                raw_result = await asyncio.to_thread(
                    router.route_and_execute_dual, augmented, doc_ids, mode, email_ids
                )
            else:
                raw_result = await asyncio.to_thread(
                    router.route_and_execute, augmented, doc_ids, mode, email_ids
                )
        except Exception as e:
            import logging
            logging.getLogger("app").error(f"[Orchestrator] Router execution failed: {e}")
            fallback_answer = (
                "I'm having trouble processing your query right now. "
                "Please try rephrasing your question or try again in a moment."
            )
            if is_dual:
                raw_result = {
                    "query_type": "document",
                    "answers": {
                        provider: {
                            "answer": fallback_answer,
                            "sources": [],
                        }
                        for provider in LLM_PROVIDERS
                    },
                    "routing": {
                        "decision": "document",
                        "confidence": 0.0,
                        "reasons": ["router execution failed"],
                        "used_llm": False,
                    },
                }
            else:
                raw_result = {
                    "query_type": "document",
                    "answer": fallback_answer,
                    "sources": [],
                    "routing": {
                        "decision": "document",
                        "confidence": 0.0,
                        "reasons": ["router execution failed"],
                        "used_llm": False,
                    },
                }

        # 4b. Corpus catch-all: for an 'edinburgh' user, drop any source whose file
        # isn't in their (chunk-store) corpus. Belt-and-suspenders over the handler
        # gates — kills demo leaks (light_graph notices / SQL tables) into the
        # citations or "Related Documents" from ANY handler. Demo users untouched.
        try:
            if _corpus == "edinburgh":
                from src.document_rag import edinburgh_filenames
                allowed = edinburgh_filenames()
                if allowed:
                    def _keep(s):
                        return (not isinstance(s, dict)) or (s.get("file_name") in allowed)
                    if isinstance(raw_result.get("sources"), list):
                        raw_result["sources"] = [s for s in raw_result["sources"] if _keep(s)]
                    for _ans in (raw_result.get("answers") or {}).values():
                        if isinstance(_ans, dict) and isinstance(_ans.get("sources"), list):
                            _ans["sources"] = [s for s in _ans["sources"] if _keep(s)]
        except Exception:
            pass

        # 4c. Trust Guard: single choke point — EVERY answer path (document,
        # agent, hybrid, dual, greeting, selected-context) flows through here;
        # the guard itself decides to skip and records why. Runs AFTER the
        # corpus filter so verification sees the final citation set. Sync +
        # LLM-calling → own to_thread (contextvars set above propagate, so
        # re-retrieval stays corpus-scoped and progress steps still publish).
        import time as _time
        _guard_t0 = _time.perf_counter()
        guard_verdict = None
        try:
            from src import trust_guard
            guard_verdict = await asyncio.to_thread(
                trust_guard.run_trust_guard_on_result,
                router, augmented, raw_result, doc_ids, email_ids,
            )
        except Exception:
            guard_verdict = None
        _guard_ms = (_time.perf_counter() - _guard_t0) * 1000.0

        # 5. Map to response contract
        response = build_chat_response(raw_result, is_dual=is_dual)

        # 5b. Feedback-free learning substrate: log the answered query + the docs
        # that surfaced together (co-retrieval graph). Best-effort, never blocks.
        try:
            srcs = raw_result.get("sources") or []
            src_files = [s.get("file_name") for s in srcs
                         if isinstance(s, dict) and s.get("file_name")]
            from src.interaction_log import get_interaction_log
            get_interaction_log().log(
                query=query,
                route=raw_result.get("query_type", ""),
                source_files=src_files,
                username=username or "",
                scope=raw_result.get("scope") or {},
                verdict=raw_result.get("verify_verdict", ""),
                ts=datetime.now().isoformat(),
            )
        except Exception:
            pass

        # 5c. Trust Guard telemetry: one row per query, INCLUDING skipped runs
        # (they are the coverage denominator). Best-effort, never blocks.
        try:
            if guard_verdict is not None:
                from src.interaction_log import get_interaction_log
                routing = raw_result.get("routing") or {}
                get_interaction_log().log_trust_guard_run(
                    run_id=request_id,
                    username=username or "",
                    query=query,
                    route=raw_result.get("query_type", ""),
                    risk=guard_verdict.risk,
                    routing_confidence=routing.get("confidence"),
                    action=guard_verdict.action if not guard_verdict.skipped else "",
                    sufficiency=guard_verdict.sufficiency,
                    unknown_entities=len(guard_verdict.unknown_entities or []),
                    re_retrieved=guard_verdict.re_retrieved,
                    llm_calls=guard_verdict.llm_calls,
                    latency_ms=_guard_ms,
                    skipped=guard_verdict.skipped,
                    skipped_reason=guard_verdict.skipped_reason,
                    ts=datetime.now().isoformat(),
                )
        except Exception:
            pass

        # 6. Save assistant message
        assistant_msg = Message(
            role="assistant",
            content=response.assistant_text,
            timestamp=datetime.now().isoformat(),
            query_type=raw_result.get("query_type", "document"),
            sources=self._serialize_response_sources(
                response,
                raw_result.get("query_type", "document"),
            ),
            sql=response.sql_artifact.generated_sql if response.sql_artifact else None,
            result_data=response.sql_artifact.preview_rows if response.sql_artifact else None,
        )
        store.add_message(conversation_id, assistant_msg)

        # 7. Auto-title on first message
        conv_meta = next(
            (c for c in store.list_conversations()
             if c.conversation_id == conversation_id),
            None,
        )
        if conv_meta and conv_meta.title == "New Chat":
            store.auto_title(conversation_id, query)

        # 8. Attach per-user quota snapshot so the UI bar updates instantly.
        if username:
            try:
                from src.user_store import get_user_store

                snap = get_user_store().get_usage(username)
                response.quota = QuotaInfo(
                    used_tokens=snap["used_tokens"],
                    token_limit=snap["token_limit"],
                    percent_remaining=snap["percent_remaining"],
                )
            except Exception:
                pass

        # Mark the activity feed complete (client also stops polling when this
        # POST resolves; this flips `done` for the final render).
        query_progress.finish(request_id)

        return response

    @staticmethod
    def _read_email_body_direct(file_path_or_name: str) -> str:
        """Read email body directly from file using email_parser, bypassing RAG."""
        from pathlib import Path
        from src.config import BASE_DIR

        # Resolve file path
        candidates = [
            Path(file_path_or_name),
            BASE_DIR / "data" / "emails" / Path(file_path_or_name).name,
            BASE_DIR / "data" / "documents" / Path(file_path_or_name).name,
        ]
        file_path = None
        for c in candidates:
            if c.exists():
                file_path = c
                break
        if not file_path:
            return ""

        suffix = file_path.suffix.lower()
        if suffix in (".msg", ".eml"):
            from src.email_parser import EmailParser
            parser = EmailParser()
            parsed = parser.parse(str(file_path))
            return parsed.body_text if parsed else ""
        return ""

    # Reply-draft intent: "draft/write/prepare/compose a reply/response/letter",
    # or "reply/respond to …". Mirrors the router's _DRAFT_PATTERNS.
    _DRAFT_INTENT_RE = re.compile(
        r"(?:draft|write|prepare|compose)\s+(?:a\s+)?(?:reply|response|answer|letter)"
        r"|(?:reply|respond)\s+to\b",
        re.IGNORECASE,
    )

    def _is_draft_intent(self, query: str) -> bool:
        return bool(self._DRAFT_INTENT_RE.search(query or ""))

    def _build_draft_support_context(self, query: str, max_facts: int = 6) -> str:
        """Corpus-scoped supporting facts for a reply draft. Retrieve-only (no
        synthesis LLM) over the WHOLE corpus (NOT the selected emails) so the draft
        can ground itself in contract terms / costs / prior decisions. corpus_var is
        already set by the caller, so this stays within the user's corpus."""
        try:
            from src.document_rag import get_document_rag
            r = get_document_rag().query(query, top_k=max_facts * 2, synthesize=False)
        except Exception:
            return ""
        srcs = (r or {}).get("sources", []) if isinstance(r, dict) else []
        lines, seen = [], set()
        for s in srcs:
            fn = s.get("file_name")
            txt = (s.get("highlight_text") or s.get("text_snippet") or "").strip()
            if not fn or not txt:
                continue
            key = (fn, s.get("page_number"))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- [{fn} p.{s.get('page_number', '?')}] {txt[:280]}")
            if len(lines) >= max_facts:
                break
        if not lines:
            return ""
        return ("SUPPORTING FACTS FROM PROJECT DOCUMENTS (use these to ground the "
                "reply — cite the file where relevant; never contradict the selected "
                "emails):\n" + "\n".join(lines))

    def _build_email_context(self, email_ids: List[str]) -> str:
        """Build full email body context from selected email IDs for correspondence mode."""
        try:
            from src.document_registry import get_document_registry
            from src.document_rag import get_document_rag

            registry = get_document_registry()
            rag = get_document_rag()

            # Gather email metadata and bodies
            emails = []
            for doc_id in email_ids:
                rec = registry.get(doc_id)
                if not rec:
                    continue

                # Only real email files belong here. Non-email selections (e.g. a
                # PDF of a conversation chosen in correspondence mode) are handled
                # by _build_document_context via the chunk store — no RAG fallback.
                fname_l = (rec.file_name or "").lower()
                is_email = fname_l.endswith((".eml", ".msg")) or getattr(rec, "file_type", "") == "email"
                if not is_email:
                    continue

                # Get notice metadata for date/sender/recipient
                notice_meta = {}
                try:
                    from src.light_graph import get_light_graph
                    graph = get_light_graph()
                    node = graph.graph.nodes.get(rec.file_name, {})
                    notice_meta = {
                        "date": node.get("date", ""),
                        "sender": node.get("sender", ""),
                        "recipient": node.get("recipient", ""),
                        "subject": node.get("subject", rec.file_name),
                    }
                except Exception:
                    notice_meta = {"date": "", "sender": "", "recipient": "", "subject": rec.file_name}

                # Get full body: try direct file parsing first, then RAG fallback
                body = ""
                try:
                    body = self._read_email_body_direct(rec.file_path or rec.file_name)
                except Exception:
                    pass

                if not body:
                    # Fallback: retrieve via RAG
                    try:
                        file_info = rag.file_registry.get(rec.file_name, {})
                        if file_info:
                            result = rag.query(
                                f"full content of {rec.file_name}",
                                top_k=10,
                                doc_ids=[doc_id],
                            )
                            body = result.get("answer", "")
                    except Exception:
                        pass

                emails.append({
                    "date": notice_meta.get("date", ""),
                    "sender": notice_meta.get("sender", "Unknown"),
                    "recipient": notice_meta.get("recipient", "Unknown"),
                    "subject": notice_meta.get("subject", rec.file_name),
                    "body": body or f"[Content of {rec.file_name}]",
                    "file_name": rec.file_name,
                })

            if not emails:
                return ""

            # Sort chronologically
            emails.sort(key=lambda e: e["date"])

            # Build context string
            parts = [f"SELECTED EMAILS ({len(emails)} emails, chronological order):"]
            for i, email in enumerate(emails, 1):
                parts.append(
                    f"\n--- EMAIL {i} [{email['date']}] ---\n"
                    f"From: {email['sender']}\n"
                    f"To: {email['recipient']}\n"
                    f"Subject: {email['subject']}\n"
                    f"File: {email['file_name']}\n\n"
                    f"{email['body']}\n"
                    f"--- END EMAIL {i} ---"
                )

            # Add instruction for the LLM
            last = emails[-1]
            parts.append(
                f"\nINSTRUCTIONS:\n"
                f"- The user has selected the {len(emails)} email(s) above — they are the correspondence being acted on.\n"
                f"- If the user asks to draft / write / prepare / compose a reply or response, generate a formal "
                f"reply on behalf of {last['recipient']} addressed to {last['sender']}, "
                f"referencing the latest message dated {last['date']} (subject: \"{last['subject']}\"). "
                f"Use construction-correspondence tone with reference / subject / salutation / body / closing. "
                f"Address every point and action raised in the emails; reflect the conversation so far. "
                f"If a 'SUPPORTING FACTS FROM PROJECT DOCUMENTS' block is provided below, use it to ground the "
                f"reply (cite the file) but never contradict the selected emails.\n"
                f"- Otherwise, answer the user's question using only the content of these emails. "
                f"If the answer is not present, say so explicitly."
            )

            return "\n".join(parts)

        except Exception as e:
            import logging
            logging.getLogger("app").warning(f"[Orchestrator] Email context build failed: {e}")
            return ""

    # Per-document and total caps so a large selection never blows up the prompt
    # (and the LLM cost). Mirrors the spirit of CHAT_MEMORY_MAX_CHARS.
    _DOC_CONTEXT_PER_DOC_MAX = 8000
    _DOC_CONTEXT_TOTAL_MAX = 16000

    def _build_document_context(self, doc_ids: List[str]) -> str:
        """Inject the full OCR/extracted text of explicitly selected NON-email
        documents (PDF/DOCX/TXT) into the prompt.

        When a user selects specific documents (general selection, chronological
        view, or a PDF conversation in correspondence mode), ground the answer
        directly in those files' text rather than relying only on RAG retrieval
        scope. Full text is read from the chunk store (the persistent mirror of
        post-OCR chunk text), ordered by page. Emails are skipped here — they are
        handled by _build_email_context.
        """
        if not doc_ids:
            return ""
        try:
            from src.document_registry import get_document_registry
            from src.chunk_store import get_chunk_store

            registry = get_document_registry()
            con = get_chunk_store().connection()
        except Exception as e:
            import logging
            logging.getLogger("app").warning(f"[Orchestrator] Document context init failed: {e}")
            return ""

        blocks: List[str] = []
        total = 0
        seen: set[str] = set()
        for doc_id in doc_ids:
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            rec = registry.get(doc_id)
            if not rec:
                continue
            file_name = rec.file_name or doc_id
            fl = file_name.lower()
            if fl.endswith((".eml", ".msg")) or getattr(rec, "file_type", "") == "email":
                continue  # emails handled by _build_email_context

            # Full extracted text from the chunk store, ordered by page. Fall back
            # to a file_name lookup when the doc_id doesn't match (the same id
            # mismatch _resolve_canonical_doc_id guards against on the read side).
            text = ""
            try:
                rows = con.execute(
                    "SELECT text FROM chunks WHERE doc_id = ? ORDER BY page_number",
                    [doc_id],
                ).fetchall()
                if not rows and file_name:
                    rows = con.execute(
                        "SELECT text FROM chunks WHERE file_name = ? ORDER BY page_number",
                        [file_name],
                    ).fetchall()
                text = "\n\n".join((r[0] or "") for r in rows).strip()
            except Exception:
                text = ""
            if not text:
                continue

            if len(text) > self._DOC_CONTEXT_PER_DOC_MAX:
                text = text[: self._DOC_CONTEXT_PER_DOC_MAX] + "\n…[truncated]"
            block = f"--- DOCUMENT: {file_name} ---\n{text}\n--- END {file_name} ---"
            if total + len(block) > self._DOC_CONTEXT_TOTAL_MAX:
                break
            blocks.append(block)
            total += len(block)

        if not blocks:
            return ""

        header = (
            f"SELECTED DOCUMENTS ({len(blocks)}) — treat the text below as the "
            f"primary source of truth for the user's request. If the answer is "
            f"not present in it, say so explicitly:"
        )
        return header + "\n\n" + "\n\n".join(blocks)
