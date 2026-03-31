"""Replaces app.py handle_input() — conversation memory + routing + response contract."""

import asyncio
from datetime import datetime
from typing import List, Optional

from src.router import QueryRouter
from src.conversation_store import ConversationStore, Message, format_chat_context
from src.config import LLM_PROVIDERS, CHAT_MEMORY_MESSAGES, CHAT_MEMORY_MAX_CHARS

from backend.services.response_builder import build_chat_response
from backend.models.responses import ChatResponse


class ChatOrchestrator:

    async def process(
        self,
        query: str,
        conversation_id: str,
        router: QueryRouter,
        store: ConversationStore,
        doc_ids: list | None = None,
        email_ids: list | None = None,
    ) -> ChatResponse:
        now = datetime.now().isoformat()

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

        # 3. Build email context for correspondence mode
        if email_ids:
            email_context = self._build_email_context(email_ids)
            if email_context:
                augmented = f"{email_context}\n\n{augmented}"
                # Also scope doc_ids to selected emails for RAG
                if not doc_ids:
                    doc_ids = email_ids

        # 4. Route and execute in thread pool (src/ code is synchronous)
        if not doc_ids:
            doc_ids = store.get_document_ids(conversation_id) or None

        is_dual = len(LLM_PROVIDERS) >= 2
        if is_dual:
            raw_result = await asyncio.to_thread(
                router.route_and_execute_dual, augmented, doc_ids
            )
        else:
            raw_result = await asyncio.to_thread(
                router.route_and_execute, augmented, doc_ids
            )

        # 5. Map to response contract
        response = build_chat_response(raw_result, is_dual=is_dual)

        # 6. Save assistant message
        assistant_msg = Message(
            role="assistant",
            content=response.assistant_text,
            timestamp=datetime.now().isoformat(),
            query_type=response.ui_intent,
            sources=[c.model_dump() for c in response.citations] if response.citations else None,
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

        return response

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

                # Get full body from RAG
                body = ""
                try:
                    file_info = rag.file_registry.get(rec.file_name, {})
                    if file_info:
                        # Get all pages/chunks for this document
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
                f"\nCONTEXT: The user has selected these {len(emails)} emails for analysis. "
                f"The most recent email is from {last['sender']} to {last['recipient']}. "
                f"If asked to draft a reply, respond on behalf of {last['recipient']} to {last['sender']}."
            )

            return "\n".join(parts)

        except Exception as e:
            import logging
            logging.getLogger("app").warning(f"[Orchestrator] Email context build failed: {e}")
            return ""
