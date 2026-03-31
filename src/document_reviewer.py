"""
Document Reviewer - aiR for Review-inspired document review features.

Features:
1. DocumentReviewer: Relevance classification (relevant/not_relevant/borderline)
   with natural language rationale and citations.
2. CitationVerifier: Verifies RAG answer citations against source pages.
3. IssueCategorizer: Categorizes documents by construction issue + key doc detection.

Follows existing patterns:
- Regex-first, LLM only for borderline cases (notice_extractor pattern)
- All LLM calls through llm_client (caching, cost tracking)
- EvidenceSpan-style citations for debuggability
"""
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (
    BASE_DIR,
    REVIEW_HIGH_THRESHOLD,
    REVIEW_LOW_THRESHOLD,
)
from .logger import logger
from .notice_extractor import NoticeMetadata, NOTICES_DIR


# ── Data Classes ────────────────────────────────────────────

@dataclass
class ReviewResult:
    """Classification result for a single document."""
    doc_id: str
    file_name: str
    relevance: str  # "relevant" | "not_relevant" | "borderline"
    confidence: float  # 0.0-1.0
    rationale: str
    citations: List[Dict[str, Any]]  # [{page, snippet, field_name, confidence}]
    issue_tags: List[str]
    review_question: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CitationVerification:
    """Verification result for a single citation/source."""
    source_idx: int
    file_name: str
    page_number: int
    claimed_text: str
    text_found_on_page: bool
    claim_supported: bool
    verification_note: str
    confidence: float = 1.0


@dataclass
class IssueCategorization:
    """Issue categorization result for a single document."""
    doc_id: str
    file_name: str
    categories: List[str]
    primary_category: str
    is_key_document: bool
    key_document_score: float  # 0.0-1.0
    key_reasons: List[str]
    claims_count: int = 0


# ── Issue Keywords (reused from document_agent.py:525-531) ──

ISSUE_KEYWORDS = {
    'delay': ['delay', 'delayed', 'behind schedule', 'slippage', 'extension of time',
              'eot', 'postponement', 'critical path', 'programme delay'],
    'payment_dispute': ['payment', 'unpaid', 'outstanding', 'overdue', 'invoice',
                        'amount due', 'cost overrun', 'price increase'],
    'quality_concern': ['defect', 'non-conformance', 'ncr', 'quality', 'rework',
                        'snag', 'punch list', 'inspection failure'],
    'safety_issue': ['safety', 'accident', 'incident', 'hazard', 'unsafe',
                     'near miss', 'ppe', 'safety violation'],
    'scope_change': ['variation', 'change order', 'scope change', 'additional work',
                     'vo', 'variation order', 'scope creep'],
    'communication_gap': ['no response', 'awaiting', 'reminder', 'follow up',
                          'unanswered', 'overdue response', 'without reply'],
    'contractual_dispute': ['claim', 'dispute', 'breach', 'without prejudice',
                            'liability', 'liquidated damages', 'penalty',
                            'force majeure', 'termination'],
}

# Document type weights for key document scoring
_DOC_TYPE_WEIGHT = {
    'notice': 1.0,
    'letter': 0.8,
    'contract': 0.9,
    'report': 0.6,
    'minutes': 0.5,
    'email': 0.4,
    'transmittal': 0.3,
    'dpr': 0.3,
    'invoice': 0.7,
}


# ── Helper: Load all notices ────────────────────────────────

def _load_all_notices() -> List[NoticeMetadata]:
    """Load all saved notices from NOTICES_DIR."""
    notices = []
    for path in NOTICES_DIR.glob("*.json"):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            notices.append(NoticeMetadata(**data))
        except Exception as e:
            logger.warning(f"[DocumentReviewer] Failed to load notice {path.name}: {e}")
    return notices


# ══════════════════════════════════════════════════════════════
# Feature 1: Document Relevance Classification
# ══════════════════════════════════════════════════════════════

class DocumentReviewer:
    """
    Classifies documents as relevant/not_relevant/borderline for a review question.
    Tier 1: Keyword scoring against NoticeMetadata fields.
    Tier 2: LLM refinement only for borderline cases.
    """

    def classify_document(
        self,
        notice: NoticeMetadata,
        review_question: str,
        doc_text: Optional[str] = None,
    ) -> ReviewResult:
        """Classify a single document against a review question."""
        question_lower = review_question.lower()

        # ── Tier 1: Keyword scoring ──
        score, matched_tags, matched_evidence = self._keyword_score(notice, question_lower)

        # Build citations from evidence spans + keyword matches
        citations = []
        for ev in notice.evidence_spans[:5]:
            if isinstance(ev, dict):
                citations.append(ev)

        # Determine relevance from score
        if score >= REVIEW_HIGH_THRESHOLD:
            relevance = "relevant"
            confidence = min(1.0, score)
            rationale = self._build_rationale(notice, matched_tags, review_question, "relevant")
        elif score <= REVIEW_LOW_THRESHOLD:
            relevance = "not_relevant"
            confidence = min(1.0, 1.0 - score)
            rationale = self._build_rationale(notice, matched_tags, review_question, "not_relevant")
        else:
            # ── Tier 2: Borderline -> LLM refinement ──
            relevance, confidence, rationale = self._llm_classify(
                notice, review_question, doc_text, score, matched_tags
            )

        return ReviewResult(
            doc_id=notice.doc_id,
            file_name=notice.file_name,
            relevance=relevance,
            confidence=round(confidence, 3),
            rationale=rationale,
            citations=citations,
            issue_tags=matched_tags,
            review_question=review_question,
        )

    def classify_batch(
        self,
        review_question: str,
        limit: int = 100,
    ) -> List[ReviewResult]:
        """Classify all available notices against a review question."""
        notices = _load_all_notices()
        if not notices:
            logger.warning("[DocumentReviewer] No notices found for classification")
            return []

        results = []
        for notice in notices[:limit]:
            result = self.classify_document(notice, review_question)
            results.append(result)

        # Sort: relevant first, then borderline, then not_relevant; within group by confidence desc
        order = {"relevant": 0, "borderline": 1, "not_relevant": 2}
        results.sort(key=lambda r: (order.get(r.relevance, 2), -r.confidence))

        logger.info(
            f"[DocumentReviewer] Classified {len(results)} documents: "
            f"{sum(1 for r in results if r.relevance == 'relevant')} relevant, "
            f"{sum(1 for r in results if r.relevance == 'borderline')} borderline, "
            f"{sum(1 for r in results if r.relevance == 'not_relevant')} not_relevant"
        )
        return results

    def _keyword_score(
        self,
        notice: NoticeMetadata,
        question_lower: str,
    ) -> tuple:
        """Score document relevance using keyword matching. Returns (score, tags, evidence)."""
        score = 0.0
        matched_tags = []
        evidence = []

        # Combine searchable text from notice
        subject = (notice.subject or '').lower()
        actions = [a.lower() for a in notice.actions]
        topics = [t.lower() for t in notice.key_topics]
        doc_type = (notice.doc_type or '').lower()
        all_text = subject + ' ' + ' '.join(actions) + ' ' + ' '.join(topics)

        # Extract question keywords (words with 3+ chars)
        q_words = set(re.findall(r'\b\w{3,}\b', question_lower))

        # 1. Direct keyword overlap with question
        for word in q_words:
            if word in all_text:
                score += 0.15
                evidence.append(f"keyword '{word}' found in document metadata")

        # 2. Issue category matching
        for issue, keywords in ISSUE_KEYWORDS.items():
            question_matches = any(kw in question_lower for kw in keywords)
            doc_matches = any(kw in all_text for kw in keywords)
            if question_matches and doc_matches:
                score += 0.25
                matched_tags.append(issue)
                evidence.append(f"issue '{issue}' matches both question and document")

        # 3. Action overlap (notice.actions vs question)
        for action in actions:
            action_words = set(re.findall(r'\b\w{3,}\b', action))
            if action_words & q_words:
                score += 0.1
                evidence.append(f"action '{action}' overlaps with question")

        # 4. Deadline presence (if question asks about deadlines/dates)
        deadline_words = {'deadline', 'date', 'when', 'timeline', 'schedule', 'due'}
        if deadline_words & q_words and notice.deadlines:
            score += 0.15
            evidence.append(f"document has {len(notice.deadlines)} deadline(s)")

        # Cap at 1.0
        score = min(1.0, score)
        return score, matched_tags, evidence

    def _build_rationale(
        self,
        notice: NoticeMetadata,
        matched_tags: List[str],
        question: str,
        relevance: str,
    ) -> str:
        """Build a natural language rationale for the classification."""
        parts = []

        if relevance == "relevant":
            parts.append(f"Document '{notice.file_name}' is relevant to the review question.")
            if matched_tags:
                parts.append(f"Matched issue categories: {', '.join(matched_tags)}.")
            if notice.subject:
                parts.append(f"Subject: {notice.subject}")
            if notice.actions:
                parts.append(f"Key actions: {', '.join(notice.actions[:3])}")
        elif relevance == "not_relevant":
            parts.append(f"Document '{notice.file_name}' does not appear relevant.")
            parts.append("No significant keyword overlap found with the review question.")
            if notice.subject:
                parts.append(f"Document subject: {notice.subject}")
        else:
            parts.append(f"Document '{notice.file_name}' has partial relevance (borderline).")
            if matched_tags:
                parts.append(f"Partially matched: {', '.join(matched_tags)}.")

        return " ".join(parts)

    def _llm_classify(
        self,
        notice: NoticeMetadata,
        review_question: str,
        doc_text: Optional[str],
        keyword_score: float,
        matched_tags: List[str],
    ) -> tuple:
        """LLM-based classification for borderline documents. Returns (relevance, confidence, rationale)."""
        try:
            from .llm_client import generate_json
            from .types import RelevanceResult

            # Build context from notice metadata
            context_parts = [
                f"File: {notice.file_name}",
                f"Type: {notice.doc_type or 'unknown'}",
                f"Date: {notice.date or 'unknown'}",
                f"Subject: {notice.subject or 'N/A'}",
                f"Sender: {notice.sender or 'N/A'}",
                f"Recipient: {notice.recipient or 'N/A'}",
                f"Actions: {', '.join(notice.actions[:5]) if notice.actions else 'none'}",
                f"Topics: {', '.join(notice.key_topics[:5]) if notice.key_topics else 'none'}",
            ]
            if notice.deadlines:
                dl_strs = [f"{d.get('date', '?')}: {d.get('context', '')}" for d in notice.deadlines[:3]]
                context_parts.append(f"Deadlines: {'; '.join(dl_strs)}")

            # Add text excerpt if available
            text_excerpt = ""
            if doc_text:
                text_excerpt = f"\n\nDocument excerpt (first 1000 chars):\n{doc_text[:1000]}"

            prompt = f"""Classify whether this construction document is relevant to the review question.

Review Question: {review_question}

Document Metadata:
{chr(10).join(context_parts)}
{text_excerpt}

Keyword-based score: {keyword_score:.2f} (borderline range)
Pre-matched issues: {', '.join(matched_tags) if matched_tags else 'none'}

Return a JSON object with:
- "relevance": "relevant", "not_relevant", or "borderline"
- "confidence": float 0.0-1.0
- "rationale": natural language explanation (1-2 sentences)
- "issue_tags": list of relevant issue categories"""

            system = "You are a construction document review expert. Classify documents objectively based on their content and metadata."

            resp = generate_json(prompt, system=system)
            parsed = resp.raw if isinstance(resp.raw, dict) else json.loads(resp.text)

            # Validate through schema
            result = RelevanceResult(**parsed)
            return result.relevance, result.confidence, result.rationale

        except Exception as e:
            logger.warning(f"[DocumentReviewer] LLM classification failed: {e}")
            # Fallback: treat as borderline
            return "borderline", keyword_score, f"Borderline relevance (score: {keyword_score:.2f}). LLM refinement unavailable."


# ══════════════════════════════════════════════════════════════
# Feature 2: Citation Verification
# ══════════════════════════════════════════════════════════════

class CitationVerifier:
    """
    Verifies RAG answer citations by checking if cited text
    actually exists on the referenced page.
    """

    def verify_citations(
        self,
        answer_text: str,
        sources: List[Dict[str, Any]],
        max_citations: int = 5,
    ) -> List[CitationVerification]:
        """
        Verify up to max_citations sources.
        For each source, checks if highlight_text appears on the referenced page.
        """
        results = []

        for idx, src in enumerate(sources[:max_citations]):
            file_path = src.get("file_path", "")
            page_num = src.get("page_number", 1)
            highlight = src.get("highlight_text", "")
            file_name = src.get("file_name", "Unknown")

            try:
                page_num = int(page_num)
            except (ValueError, TypeError):
                page_num = 1

            if not file_path or not highlight:
                results.append(CitationVerification(
                    source_idx=idx,
                    file_name=file_name,
                    page_number=page_num,
                    claimed_text=highlight[:100] if highlight else "(no text)",
                    text_found_on_page=False,
                    claim_supported=False,
                    verification_note="Missing file path or highlight text",
                    confidence=0.0,
                ))
                continue

            # Get page content
            page_text = self._get_page_text(file_path, page_num)
            if not page_text:
                results.append(CitationVerification(
                    source_idx=idx,
                    file_name=file_name,
                    page_number=page_num,
                    claimed_text=highlight[:100],
                    text_found_on_page=False,
                    claim_supported=False,
                    verification_note="Could not read page content",
                    confidence=0.0,
                ))
                continue

            # Check if highlight text appears on page (fuzzy matching)
            text_found, match_score = self._fuzzy_text_search(highlight, page_text)

            # LLM claim support check (only if text found and answer references this source)
            claim_supported = text_found  # default to text_found
            support_note = ""

            if text_found:
                support_note = f"Text found on page (match: {match_score:.0%})"
                claim_supported = True
            else:
                support_note = f"Text not found on page (best match: {match_score:.0%})"

            results.append(CitationVerification(
                source_idx=idx,
                file_name=file_name,
                page_number=page_num,
                claimed_text=highlight[:100],
                text_found_on_page=text_found,
                claim_supported=claim_supported,
                verification_note=support_note,
                confidence=match_score,
            ))

        verified = sum(1 for r in results if r.text_found_on_page)
        logger.info(
            f"[CitationVerifier] Verified {len(results)} citations: "
            f"{verified} found, {len(results) - verified} not found"
        )
        return results

    def _get_page_text(self, file_path: str, page_num: int) -> Optional[str]:
        """Get text content from a PDF page."""
        try:
            from .document_rag import get_document_rag
            rag = get_document_rag()
            return rag.get_page_content(file_path, page_num)
        except Exception:
            # Fallback: direct fitz access
            try:
                import fitz
                doc = fitz.open(file_path)
                if 1 <= page_num <= len(doc):
                    text = doc[page_num - 1].get_text()
                    doc.close()
                    return text
                doc.close()
            except Exception as e:
                logger.warning(f"[CitationVerifier] Cannot read page: {e}")
        return None

    def _fuzzy_text_search(self, highlight: str, page_text: str) -> tuple:
        """
        Check if highlight text appears on the page using fuzzy matching.
        Returns (found: bool, best_match_score: float).
        """
        if not highlight or not page_text:
            return False, 0.0

        # Normalize both texts
        clean_highlight = re.sub(r'\s+', ' ', highlight).strip().lower()
        clean_page = re.sub(r'\s+', ' ', page_text).strip().lower()

        # Exact substring check
        if clean_highlight[:50] in clean_page:
            return True, 1.0

        # Try sentence-level matching
        sentences = [s.strip() for s in clean_highlight.split('. ') if len(s.strip()) > 10]
        best_score = 0.0

        for sent in sentences[:3]:
            sent_clean = sent[:80]
            if sent_clean in clean_page:
                return True, 0.95

            # Sliding window fuzzy match
            window_size = len(sent_clean)
            if window_size > len(clean_page):
                continue

            for i in range(0, min(len(clean_page) - window_size, 2000), 20):
                window = clean_page[i:i + window_size]
                ratio = SequenceMatcher(None, sent_clean, window).ratio()
                best_score = max(best_score, ratio)
                if ratio > 0.75:
                    return True, ratio

        # Short phrase check (first 30 chars)
        short_phrase = clean_highlight[:30]
        if short_phrase in clean_page:
            return True, 0.85

        return best_score > 0.6, best_score


# ══════════════════════════════════════════════════════════════
# Feature 3: Issue Categorization + Key Document Detection
# ══════════════════════════════════════════════════════════════

class IssueCategorizer:
    """
    Categorizes documents by construction issue categories and
    identifies key/critical documents per category.
    """

    def categorize_document(self, notice: NoticeMetadata) -> IssueCategorization:
        """Categorize a single document by issue types."""
        subject = (notice.subject or '').lower()
        actions = [a.lower() for a in notice.actions]
        topics = [t.lower() for t in notice.key_topics]
        all_text = subject + ' ' + ' '.join(actions) + ' ' + ' '.join(topics)

        categories = []
        for issue, keywords in ISSUE_KEYWORDS.items():
            if any(kw in all_text for kw in keywords):
                categories.append(issue)

        primary = categories[0] if categories else "uncategorized"

        # Key document scoring
        score, reasons = self._key_document_score(notice, categories)

        return IssueCategorization(
            doc_id=notice.doc_id,
            file_name=notice.file_name,
            categories=categories,
            primary_category=primary,
            is_key_document=score >= 0.6,
            key_document_score=round(score, 3),
            key_reasons=reasons,
            claims_count=len(notice.actions),
        )

    def categorize_all(self) -> Dict[str, List[IssueCategorization]]:
        """Categorize all notices, grouped by issue category."""
        notices = _load_all_notices()
        if not notices:
            return {}

        # Get graph in-degrees for key document scoring
        in_degrees = self._get_graph_in_degrees()

        by_category: Dict[str, List[IssueCategorization]] = defaultdict(list)
        for notice in notices:
            cat = self.categorize_document(notice)

            # Augment with graph in-degree
            in_deg = in_degrees.get(notice.doc_id, 0)
            if in_deg >= 3:
                cat.key_document_score = min(1.0, cat.key_document_score + 0.15)
                cat.key_reasons.append(f"Referenced by {in_deg} other documents")
                cat.is_key_document = cat.key_document_score >= 0.6

            for c in cat.categories:
                by_category[c].append(cat)

            if not cat.categories:
                by_category["uncategorized"].append(cat)

        # Sort each category by key_document_score descending
        for category in by_category:
            by_category[category].sort(key=lambda x: -x.key_document_score)

        total = sum(len(v) for v in by_category.values())
        key_count = sum(1 for cats in by_category.values() for c in cats if c.is_key_document)
        logger.info(
            f"[IssueCategorizer] Categorized {len(notices)} documents into "
            f"{len(by_category)} categories, {key_count} key documents"
        )
        return dict(by_category)

    def find_key_documents(
        self,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> List[IssueCategorization]:
        """Find the top-K key documents, optionally filtered by category."""
        all_cats = self.categorize_all()

        if category and category in all_cats:
            pool = all_cats[category]
        else:
            # Merge all categories, deduplicate by doc_id
            seen = set()
            pool = []
            for cats in all_cats.values():
                for c in cats:
                    if c.doc_id not in seen:
                        seen.add(c.doc_id)
                        pool.append(c)

        pool.sort(key=lambda x: -x.key_document_score)
        return pool[:top_k]

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of document categories and counts."""
        all_cats = self.categorize_all()
        summary = {}
        for cat, docs in all_cats.items():
            key_docs = [d for d in docs if d.is_key_document]
            summary[cat] = {
                "count": len(docs),
                "key_documents": len(key_docs),
                "top_files": [d.file_name for d in docs[:3]],
            }
        return summary

    def _key_document_score(
        self,
        notice: NoticeMetadata,
        categories: List[str],
    ) -> tuple:
        """
        Calculate key document score based on multiple signals.
        Returns (score, reasons).
        """
        score = 0.0
        reasons = []

        # 1. Document type weight
        doc_type = (notice.doc_type or '').lower()
        type_weight = _DOC_TYPE_WEIGHT.get(doc_type, 0.3)
        score += type_weight * 0.25
        if type_weight >= 0.8:
            reasons.append(f"Formal document type: {doc_type}")

        # 2. Number of matched categories
        if len(categories) >= 3:
            score += 0.2
            reasons.append(f"Touches {len(categories)} issue categories")
        elif len(categories) >= 2:
            score += 0.1

        # 3. Actions/claims density
        action_count = len(notice.actions)
        if action_count >= 4:
            score += 0.2
            reasons.append(f"High claim density ({action_count} actions)")
        elif action_count >= 2:
            score += 0.1

        # 4. Deadlines present
        if notice.deadlines:
            score += 0.15
            reasons.append(f"Contains {len(notice.deadlines)} deadline(s)")

        # 5. Monetary amounts (check for currency patterns in subject/actions)
        money_pattern = r'(?:USD|AED|GBP|EUR|\$|£|€)\s*[\d,.]+'
        all_text = (notice.subject or '') + ' ' + ' '.join(notice.actions)
        if re.search(money_pattern, all_text, re.IGNORECASE):
            score += 0.15
            reasons.append("Contains monetary amounts")

        # 6. Reference to other documents
        if notice.referenced_docs:
            score += 0.1
            reasons.append(f"References {len(notice.referenced_docs)} other document(s)")

        score = min(1.0, score)
        return score, reasons

    def _get_graph_in_degrees(self) -> Dict[str, int]:
        """Get in-degree (incoming reference count) for each document from the graph."""
        try:
            from .light_graph import get_light_graph
            graph = get_light_graph()
            in_degrees: Dict[str, int] = defaultdict(int)
            for edge in graph.graph.edges:
                target = edge.get("target", edge.get("doc_b", ""))
                if target:
                    in_degrees[target] += 1
            return dict(in_degrees)
        except Exception as e:
            logger.warning(f"[IssueCategorizer] Cannot access graph: {e}")
            return {}


# ── Singleton accessors ─────────────────────────────────────

_reviewer: Optional[DocumentReviewer] = None
_verifier: Optional[CitationVerifier] = None
_categorizer: Optional[IssueCategorizer] = None


def get_document_reviewer() -> DocumentReviewer:
    global _reviewer
    if _reviewer is None:
        _reviewer = DocumentReviewer()
    return _reviewer


def get_citation_verifier() -> CitationVerifier:
    global _verifier
    if _verifier is None:
        _verifier = CitationVerifier()
    return _verifier


def get_issue_categorizer() -> IssueCategorizer:
    global _categorizer
    if _categorizer is None:
        _categorizer = IssueCategorizer()
    return _categorizer
