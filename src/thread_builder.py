"""
Thread Builder - Build correspondence threads from the notices DuckDB table.
Groups sender-recipient communications chronologically for thread viewing.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

from .logger import logger


def _parse_date(d: str) -> datetime:
    """Parse date string for robust sorting (handles inconsistent formats)."""
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d")
    except Exception:
        return datetime.min


@dataclass
class ThreadMessage:
    """A single message in a correspondence thread."""
    doc_id: str
    date: str
    sender: str
    recipient: str
    subject: str
    body_preview: str  # First 300 chars from RAG
    actions: List[str]
    file_name: str
    doc_type: Optional[str] = None


@dataclass
class CorrespondenceThread:
    """A thread of messages between two parties."""
    party_a: str
    party_b: str
    messages: List[ThreadMessage] = field(default_factory=list)
    topic: Optional[str] = None


class ThreadBuilder:
    """
    Build correspondence threads from the notices DuckDB table + RAG.
    Uses LightGraph's DuckDB for notice queries and DocumentRAG for body previews.
    """

    def __init__(self):
        self._graph = None
        self._rag = None

    @property
    def graph(self):
        if self._graph is None:
            from .light_graph import get_light_graph
            self._graph = get_light_graph()
        return self._graph

    @property
    def rag(self):
        if self._rag is None:
            from .document_rag import get_document_rag
            self._rag = get_document_rag()
        return self._rag

    def find_threads(self, party: str) -> List[CorrespondenceThread]:
        """
        Find all correspondence threads involving a given party.
        Groups by the other party, sorted by date.

        Args:
            party: Name of a sender or recipient

        Returns:
            List of CorrespondenceThread objects
        """
        if not self.graph._notices_table_ready:
            logger.warning("[ThreadBuilder] Notices table not ready")
            return []

        party_lower = party.lower().strip()

        try:
            result = self.graph._db.execute(
                """
                SELECT doc_id, date, sender, recipient, subject,
                       doc_type, file_name, actions
                FROM notices
                WHERE LOWER(sender) LIKE ? OR LOWER(recipient) LIKE ?
                ORDER BY date ASC
                """,
                [f"%{party_lower}%", f"%{party_lower}%"],
            ).fetchall()
        except Exception as e:
            logger.warning(f"[ThreadBuilder] Query failed: {e}")
            return []

        if not result:
            return []

        # Group by other party
        threads_map: Dict[str, List[ThreadMessage]] = {}

        for row in result:
            doc_id, date, sender, recipient, subject, doc_type, file_name, actions_str = row
            sender = sender or "Unknown"
            recipient = recipient or "Unknown"

            # Determine other party
            if party_lower in sender.lower():
                other = recipient
            else:
                other = sender

            other_key = other.lower().strip() if other else "unknown"

            actions = [a.strip() for a in (actions_str or "").split(",") if a.strip()]

            msg = ThreadMessage(
                doc_id=doc_id or "",
                date=date or "",
                sender=sender,
                recipient=recipient,
                subject=subject or "",
                body_preview=self._get_body_preview(file_name),
                actions=actions,
                file_name=file_name or "",
                doc_type=doc_type,
            )

            if other_key not in threads_map:
                threads_map[other_key] = []
            threads_map[other_key].append(msg)

        # Build thread objects
        threads = []
        for other_key, messages in threads_map.items():
            display_name = messages[0].recipient if party_lower in messages[0].sender.lower() else messages[0].sender
            thread = CorrespondenceThread(
                party_a=party,
                party_b=display_name or other_key,
                messages=sorted(messages, key=lambda m: _parse_date(m.date)),
            )
            threads.append(thread)

        logger.info(f"[ThreadBuilder] Found {len(threads)} threads for '{party}'")
        return threads

    def get_thread_between(self, party_a: str, party_b: str) -> CorrespondenceThread:
        """
        Get the correspondence thread between two specific parties.

        Args:
            party_a: First party name
            party_b: Second party name

        Returns:
            CorrespondenceThread with all messages between them
        """
        a_lower = party_a.lower().strip()
        b_lower = party_b.lower().strip()

        thread = CorrespondenceThread(party_a=party_a, party_b=party_b)

        if not self.graph._notices_table_ready:
            return thread

        try:
            result = self.graph._db.execute(
                """
                SELECT doc_id, date, sender, recipient, subject,
                       doc_type, file_name, actions
                FROM notices
                WHERE (LOWER(sender) LIKE ? AND LOWER(recipient) LIKE ?)
                   OR (LOWER(sender) LIKE ? AND LOWER(recipient) LIKE ?)
                ORDER BY date ASC
                """,
                [f"%{a_lower}%", f"%{b_lower}%", f"%{b_lower}%", f"%{a_lower}%"],
            ).fetchall()
        except Exception as e:
            logger.warning(f"[ThreadBuilder] Query failed: {e}")
            return thread

        for row in result:
            doc_id, date, sender, recipient, subject, doc_type, file_name, actions_str = row
            actions = [a.strip() for a in (actions_str or "").split(",") if a.strip()]

            thread.messages.append(ThreadMessage(
                doc_id=doc_id or "",
                date=date or "",
                sender=sender or "",
                recipient=recipient or "",
                subject=subject or "",
                body_preview=self._get_body_preview(file_name),
                actions=actions,
                file_name=file_name or "",
                doc_type=doc_type,
            ))

        logger.info(f"[ThreadBuilder] Thread {party_a} <-> {party_b}: "
                     f"{len(thread.messages)} messages")
        return thread

    def get_latest_unanswered(self) -> List[ThreadMessage]:
        """
        Find messages that appear to be unanswered:
        the latest message in each sender-recipient pair where the recipient
        has no newer reply.

        Returns:
            List of potentially unanswered messages
        """
        if not self.graph._notices_table_ready:
            return []

        try:
            # Get latest message per sender-recipient pair
            result = self.graph._db.execute("""
                WITH ranked AS (
                    SELECT doc_id, date, sender, recipient, subject,
                           doc_type, file_name, actions,
                           ROW_NUMBER() OVER (
                               PARTITION BY
                                   CASE WHEN sender < recipient
                                        THEN sender || '|' || recipient
                                        ELSE recipient || '|' || sender
                                   END
                               ORDER BY date DESC
                           ) AS rn
                    FROM notices
                    WHERE sender IS NOT NULL AND recipient IS NOT NULL
                      AND sender != '' AND recipient != ''
                )
                SELECT doc_id, date, sender, recipient, subject,
                       doc_type, file_name, actions
                FROM ranked
                WHERE rn = 1
                ORDER BY date DESC
                LIMIT 20
            """).fetchall()
        except Exception as e:
            logger.warning(f"[ThreadBuilder] Unanswered query failed: {e}")
            return []

        messages = []
        for row in result:
            doc_id, date, sender, recipient, subject, doc_type, file_name, actions_str = row
            actions = [a.strip() for a in (actions_str or "").split(",") if a.strip()]

            messages.append(ThreadMessage(
                doc_id=doc_id or "",
                date=date or "",
                sender=sender or "",
                recipient=recipient or "",
                subject=subject or "",
                body_preview=self._get_body_preview(file_name),
                actions=actions,
                file_name=file_name or "",
                doc_type=doc_type,
            ))

        return messages

    def _get_body_preview(self, file_name: str, max_chars: int = 300) -> str:
        """Get a body preview from RAG for a given file."""
        if not file_name:
            return ""

        try:
            for doc in self.rag.documents:
                if doc.metadata.get("file_name") == file_name:
                    text = doc.text.strip()
                    if len(text) > max_chars:
                        return text[:max_chars] + "..."
                    return text
        except Exception as e:
            logger.warning(f"[ThreadBuilder] Body preview failed for {file_name}: {e}")
            return ""

        logger.debug(f"[ThreadBuilder] No RAG content found for {file_name}")
        return ""


# Module-level singleton
_builder: Optional["ThreadBuilder"] = None


def get_thread_builder() -> ThreadBuilder:
    """Get or create ThreadBuilder singleton."""
    global _builder
    if _builder is None:
        _builder = ThreadBuilder()
    return _builder
