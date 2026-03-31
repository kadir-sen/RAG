"""
Review Session Manager - Develop-Validate-Apply workflow.

Inspired by Relativity aiR for Review's iterative prompt refinement:
1. Develop: Test review question on a random sample of documents
2. Validate: User provides feedback (correct/incorrect), accuracy is calculated
3. Apply: Once accuracy >= threshold, classify all documents

Pattern: Follows ConversationStore JSON persistence from conversation_store.py.
"""
import json
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

from .config import (
    REVIEW_SESSIONS_DIR,
    REVIEW_ACCURACY_THRESHOLD,
    REVIEW_SAMPLE_SIZE,
)
from .logger import logger


# ── Data Classes ────────────────────────────────────────────

@dataclass
class ReviewFeedback:
    """Human feedback on a single document classification."""
    doc_id: str
    predicted_relevance: str  # what the system predicted
    human_label: str  # what the human says: "relevant" | "not_relevant" | "borderline"
    is_correct: bool  # predicted == human_label


@dataclass
class ReviewSession:
    """A review session tracking the Develop-Validate-Apply workflow."""
    session_id: str
    review_question: str
    status: str = "develop"  # develop | validate | apply | completed
    sample_size: int = 10
    sample_results: List[Dict[str, Any]] = field(default_factory=list)
    feedback: List[Dict[str, Any]] = field(default_factory=list)
    accuracy: Optional[float] = None
    total_documents: int = 0
    full_results: Optional[List[Dict[str, Any]]] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Session Manager ─────────────────────────────────────────

class ReviewSessionManager:
    """
    Manages review sessions with JSON persistence.
    One JSON file per session in REVIEW_SESSIONS_DIR.
    """

    def __init__(self):
        self.sessions_dir = REVIEW_SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        review_question: str,
        sample_size: int = REVIEW_SAMPLE_SIZE,
    ) -> ReviewSession:
        """
        Create a new review session and classify a sample of documents.
        Returns session in 'develop' status with sample results.
        """
        from .document_reviewer import get_document_reviewer, _load_all_notices

        reviewer = get_document_reviewer()
        all_notices = _load_all_notices()

        if not all_notices:
            session = ReviewSession(
                session_id=str(uuid.uuid4())[:8],
                review_question=review_question,
                status="develop",
                sample_size=0,
                total_documents=0,
            )
            self._save_session(session)
            return session

        # Random sample
        sample_notices = random.sample(
            all_notices,
            min(sample_size, len(all_notices)),
        )

        # Classify sample
        sample_results = []
        for notice in sample_notices:
            result = reviewer.classify_document(notice, review_question)
            sample_results.append(result.to_dict())

        session = ReviewSession(
            session_id=str(uuid.uuid4())[:8],
            review_question=review_question,
            status="develop",
            sample_size=len(sample_results),
            sample_results=sample_results,
            total_documents=len(all_notices),
        )

        self._save_session(session)
        logger.info(
            f"[ReviewSession] Created session {session.session_id}: "
            f"{len(sample_results)} sample docs classified"
        )
        return session

    def record_feedback(
        self,
        session_id: str,
        doc_id: str,
        human_label: str,
    ) -> Optional[ReviewSession]:
        """Record human feedback for a sample document."""
        session = self.get_session(session_id)
        if not session:
            return None

        # Find the predicted result for this doc
        predicted = None
        for r in session.sample_results:
            if r.get("doc_id") == doc_id:
                predicted = r.get("relevance", "")
                break

        if predicted is None:
            logger.warning(f"[ReviewSession] Doc {doc_id} not in session {session_id} sample")
            return session

        is_correct = predicted == human_label

        feedback_entry = asdict(ReviewFeedback(
            doc_id=doc_id,
            predicted_relevance=predicted,
            human_label=human_label,
            is_correct=is_correct,
        ))

        # Update or add feedback (replace if already exists for this doc)
        existing_idx = next(
            (i for i, f in enumerate(session.feedback) if f.get("doc_id") == doc_id),
            None,
        )
        if existing_idx is not None:
            session.feedback[existing_idx] = feedback_entry
        else:
            session.feedback.append(feedback_entry)

        # Recalculate accuracy
        if session.feedback:
            correct = sum(1 for f in session.feedback if f.get("is_correct"))
            session.accuracy = correct / len(session.feedback)

        # Auto-transition to validate status if any feedback recorded
        if session.status == "develop" and session.feedback:
            session.status = "validate"

        session.updated_at = datetime.now().isoformat()
        self._save_session(session)
        return session

    def can_apply(self, session_id: str) -> tuple:
        """Check if session meets the threshold to apply to all documents.
        Returns (can_apply: bool, reason: str)."""
        session = self.get_session(session_id)
        if not session:
            return False, "Session not found"

        if not session.feedback:
            return False, "No feedback provided yet"

        feedback_ratio = len(session.feedback) / max(len(session.sample_results), 1)
        if feedback_ratio < 0.5:
            return False, f"Need feedback on at least 50% of sample (currently {feedback_ratio:.0%})"

        if session.accuracy is None or session.accuracy < REVIEW_ACCURACY_THRESHOLD:
            return False, (
                f"Accuracy {session.accuracy:.0%} is below threshold "
                f"({REVIEW_ACCURACY_THRESHOLD:.0%})"
            )

        return True, f"Ready to apply (accuracy: {session.accuracy:.0%})"

    def apply_to_all(self, session_id: str) -> Optional[ReviewSession]:
        """Apply the review question classification to all documents."""
        can, reason = self.can_apply(session_id)
        if not can:
            logger.warning(f"[ReviewSession] Cannot apply: {reason}")
            return self.get_session(session_id)

        session = self.get_session(session_id)
        if not session:
            return None

        from .document_reviewer import get_document_reviewer

        reviewer = get_document_reviewer()
        results = reviewer.classify_batch(session.review_question)

        session.full_results = [r.to_dict() for r in results]
        session.status = "completed"
        session.updated_at = datetime.now().isoformat()
        self._save_session(session)

        logger.info(
            f"[ReviewSession] Applied to all: {len(results)} documents classified. "
            f"Session {session_id} completed."
        )
        return session

    def get_session(self, session_id: str) -> Optional[ReviewSession]:
        """Load a session from disk."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ReviewSession(**data)
        except Exception as e:
            logger.warning(f"[ReviewSession] Failed to load session {session_id}: {e}")
            return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all review sessions (lightweight metadata)."""
        sessions = []
        for path in sorted(self.sessions_dir.glob("*.json"), reverse=True):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", path.stem),
                    "review_question": data.get("review_question", ""),
                    "status": data.get("status", ""),
                    "accuracy": data.get("accuracy"),
                    "sample_size": data.get("sample_size", 0),
                    "total_documents": data.get("total_documents", 0),
                    "created_at": data.get("created_at", ""),
                })
            except Exception:
                continue
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a review session."""
        path = self.sessions_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def _save_session(self, session: ReviewSession):
        """Save session to disk and sync to GCS."""
        path = self.sessions_dir / f"{session.session_id}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(session), f, indent=2, ensure_ascii=False)
        # Sync to GCS for persistence across Cloud Run redeploys
        try:
            from .gcs_storage import sync_review_session_to_gcs
            sync_review_session_to_gcs(session.session_id)
        except Exception:
            pass  # GCS sync is best-effort


# ── Singleton ───────────────────────────────────────────────

_manager: Optional[ReviewSessionManager] = None


def get_review_session_manager() -> ReviewSessionManager:
    global _manager
    if _manager is None:
        _manager = ReviewSessionManager()
    return _manager
