"""
Notice Extractor - Extract structured metadata from construction documents.
Uses regex-first extraction with optional LLM refinement.
Every field includes evidence_spans for debuggability.
OCR-aware: handles noisy text, fuzzy label matching, de-hyphenation.

Optimized for English-only construction correspondence (TABH project format).
"""
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

from .logger import logger
from .config import GOOGLE_API_KEY, GEMINI_MODEL, BASE_DIR

# Notice storage directory
NOTICES_DIR = BASE_DIR / "data" / "notices"
NOTICES_DIR.mkdir(parents=True, exist_ok=True)


# ── OCR Post-Processing ─────────────────────────────────────

def ocr_cleanup(text: str) -> str:
    """
    Clean up OCR-noisy text:
    - normalize whitespace, collapse multiple spaces
    - de-hyphenation (join words split by line-break hyphens)
    - fix common OCR symbol errors
    """
    # De-hyphenation: "re-\ncognize" -> "recognize"
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)

    # Collapse multiple spaces
    text = re.sub(r'[ \t]+', ' ', text)

    # Normalize line endings
    text = re.sub(r'\r\n', '\n', text)

    # Remove excessive blank lines (keep max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Fix common OCR ligature issues
    text = text.replace('ﬁ', 'fi').replace('ﬂ', 'fl')

    return text.strip()


# ── Fuzzy Header Label Matching ──────────────────────────────

# Canonical labels -> list of known OCR variants (English only)
_CANONICAL_LABELS = {
    "date": ["date", "dated", "dat", "dae", "daie"],
    "from": ["from", "sender", "frorn", "fron", "frm", "issued by", "sent by"],
    "to": ["to", "recipient", "reclpient", "recipien", "attention", "attn"],
    "subject": ["subject", "re", "regarding", "subj", "subjeet", "subjecl", "re:"],
    "cc": ["cc", "copy to", "copies to", "c.c."],
    "ref": ["ref", "reference", "our ref", "your ref", "letter no",
            "doc no", "document no"],
}


def _fuzzy_match_label(label: str, threshold: int = 75) -> Optional[str]:
    """
    Match an OCR-noisy label to a canonical field using RapidFuzz.
    Returns canonical name or None.
    """
    label = label.strip().lower().rstrip(":").strip()
    if not label or len(label) < 2:
        return None

    # Exact match first
    for canonical, variants in _CANONICAL_LABELS.items():
        if label in variants:
            return canonical

    # Fuzzy match with RapidFuzz
    try:
        from rapidfuzz import fuzz
        best_match = None
        best_score = 0
        for canonical, variants in _CANONICAL_LABELS.items():
            for variant in variants:
                score = fuzz.ratio(label, variant)
                if score > best_score:
                    best_score = score
                    best_match = canonical

        if best_score >= threshold:
            return best_match
    except ImportError:
        # Fallback: simple substring check
        for canonical, variants in _CANONICAL_LABELS.items():
            for variant in variants:
                if variant in label or label in variant:
                    return canonical

    return None


@dataclass
class EvidenceSpan:
    """Citation showing where a field was extracted from."""
    page: int
    snippet: str
    field_name: str
    confidence: float = 1.0


@dataclass
class NoticeMetadata:
    """Structured metadata extracted from a document."""
    doc_id: str
    file_path: str
    file_name: str

    # Core fields
    language: Optional[str] = None
    doc_type: Optional[str] = None  # letter/notice/report/minutes/contract/invoice/transmittal/email/dpr
    date: Optional[str] = None  # ISO format YYYY-MM-DD
    sender: Optional[str] = None
    sender_title: Optional[str] = None
    sender_company: Optional[str] = None
    recipient: Optional[str] = None
    recipient_title: Optional[str] = None
    subject: Optional[str] = None

    # Communication flow
    cc_list: List[str] = field(default_factory=list)  # CC recipients
    direction: Optional[str] = None  # "outgoing" | "incoming" | "internal"

    # References
    ref_numbers: List[str] = field(default_factory=list)
    referenced_docs: List[str] = field(default_factory=list)
    contract_ref: Optional[str] = None  # Contract reference number
    project_name: Optional[str] = None  # Detected project name

    # Semantics
    key_topics: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    deadlines: List[Dict[str, str]] = field(default_factory=list)  # {date, context}
    jargon_found: List[Dict[str, str]] = field(default_factory=list)  # [{abbreviation, meaning}]

    # Evidence
    evidence_spans: List[Dict[str, Any]] = field(default_factory=list)

    # Summary
    summary: str = ""

    # Metadata
    extraction_method: str = "regex"  # regex | regex+llm
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat())
    project_id: Optional[str] = None


class NoticeExtractor:
    """
    Extracts structured notice metadata from construction documents.
    Regex-first approach with optional LLM refinement.
    Optimized for English construction correspondence (TABH/Dubai project formats).
    """

    # ── Date patterns (English only, ordered by specificity) ──

    DATE_PATTERNS = [
        # ISO: 2024-01-15
        (r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b', 'iso'),
        # Written: 15th January 2024 | 15 January 2024
        (r'\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b', 'written'),
        # Written US: January 15, 2024
        (r'\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b', 'written_us'),
        # Short month: 15-Jan-2024, 15 Jan 2024
        (r'\b(\d{1,2}[-\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-\s,]*\d{4})\b', 'written_short'),
        # UK/EU 4-digit year: 15/01/2024, 15-01-2024, 15.01.2024
        (r'\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\b', 'dmy'),
        # 2-digit year (common in TABH docs): 15.01.24, 15/01/24
        (r'\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{2})\b', 'dmy_short'),
    ]

    # ── Sender patterns (English + OCR typos) ──

    SENDER_PATTERNS = [
        r'(?:From|Sender)\s*[:]\s*(.+?)(?:\n|$)',
        r'^From\s*:\s*(.+?)(?:\n|$)',
        r'(?:Sent\s*by|Issued\s*by|Prepared\s*by)\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:Frorn|Fron|Frm)\s*[:]\s*(.+?)(?:\n|$)',  # OCR typos
    ]

    # ── Signature block patterns for sender extraction ──

    SIGNATURE_PATTERNS = [
        # "Kind Regards," / "Best Regards," / "Yours faithfully," followed by name
        r'(?:Kind\s+Regards|Best\s+Regards|Yours\s+(?:faithfully|sincerely|truly)|Regards|Sincerely)\s*[,.]?\s*\n+\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})',
        # Name on line after signature phrase, possibly with title
        r'(?:Kind\s+Regards|Best\s+Regards|Regards|Sincerely)\s*[,.]?\s*\n+\s*([A-Z][A-Za-z.\s]+?)(?:\n|$)',
    ]

    # Patterns to extract title/company from signature block
    SIGNATURE_TITLE_PATTERNS = [
        # Title line after name: "Project Manager", "Senior Engineer", etc.
        r'(?:Kind\s+Regards|Best\s+Regards|Regards|Sincerely)\s*[,.]?\s*\n+\s*[A-Z][A-Za-z.\s]+?\n\s*([A-Z][A-Za-z\s&]+?)(?:\n|$)',
    ]

    # ── Recipient patterns (English only) ──

    RECIPIENT_PATTERNS = [
        r'(?:To|Recipient)\s*[:]\s*(.+?)(?:\n|$)',
        r'^To\s*:\s*(.+?)(?:\n|$)',
        r'(?:Attention|Attn)\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:For\s+the\s+attention\s+of)\s*[:.]?\s*(.+?)(?:\n|$)',
        # "Dear Mr. / Ms. / Dr. Name" pattern (common in TABH letters)
        r'Dear\s+(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Sir|Madam)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
        r'Dear\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s*[,]',
    ]

    # ── Subject patterns (English only) ──

    SUBJECT_PATTERNS = [
        r'(?:Subject|Subj|Subjeet|Subjecl)\s*[:]\s*(.+?)(?:\n|$)',
        r'^Subject\s*:\s*(.+?)(?:\n|$)',
        r'(?:Re|Regarding|In\s+re|Matter)\s*[:]\s*(.+?)(?:\n|$)',
    ]

    # ── Reference patterns (real TABH formats + generic) ──

    REF_PATTERNS = [
        # Labeled references
        r'(?:Ref|Reference|Our\s*Ref|Your\s*Ref)\s*[:.]?\s*([A-Za-z0-9\-_/]+(?:[-/][A-Za-z0-9]+)*)',
        r'(?:Doc(?:ument)?\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Letter\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Contract\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Notice\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        # TABH project format: TABH-LTR-TCI-BMM-0001
        r'\b(TABH[-/][A-Z]{2,5}[-/][A-Z]{2,5}[-/][A-Z]{2,5}[-/]\d{3,5})\b',
        # MVP/BM format: MVP/BM/DD.MM.YY
        r'\b(MVP[/-][A-Z]{2,4}[/-]\d{1,2}\.\d{1,2}\.\d{2,4})\b',
        # BMDXB format: BMDXB-SUBCONLET-XXXXXX
        r'\b(BMDXB[-/][A-Z]+-\d{4,8})\b',
        # Generic: ABC-001-2024 or ABC/001/2024
        r'\b([A-Z]{2,5}[-/]\d{3,}(?:[-/]\d+)*)\b',
        # Slash-separated refs: ABC/DEF/001
        r'\b([A-Z]{2,5}/[A-Z]{2,5}/\d{3,})\b',
    ]

    # ── Action keywords (English only, expanded for construction) ──

    ACTION_KEYWORDS = {
        'submit': ['submit', 'submission', 'submitted', 'submitting'],
        'respond': ['respond', 'response', 'reply', 'answer', 'replying'],
        'approve': ['approve', 'approval', 'approved', 'approving'],
        'reject': ['reject', 'rejection', 'rejected', 'rejecting'],
        'delay': ['delay', 'delayed', 'postpone', 'postponement', 'extension of time'],
        'claim': ['claim', 'claims', 'claiming', 'entitlement'],
        'notify': ['notify', 'notification', 'notice', 'hereby notify', 'notifying'],
        'request': ['request', 'requesting', 'requested', 'kindly request'],
        'confirm': ['confirm', 'confirmation', 'confirmed', 'confirming'],
        'complete': ['complete', 'completed', 'completion', 'substantial completion'],
        'terminate': ['terminate', 'termination', 'terminated'],
        'suspend': ['suspend', 'suspension', 'suspended'],
        # Construction-specific actions
        'handover': ['handover', 'hand over', 'handing over', 'takeover'],
        'inspect': ['inspect', 'inspection', 'inspected', 'site inspection'],
        'instruct': ['instruct', 'instruction', 'instructed', 'hereby instruct'],
        'certify': ['certify', 'certificate', 'certification', 'certified'],
        'warranty': ['warranty', 'defects liability', 'retention', 'defect notification'],
        'payment': ['payment', 'interim payment', 'final payment', 'pay', 'invoice'],
        'variation': ['variation', 'variation order', 'change order', 'scope change'],
        'disclaimer': ['responsibility', 'liable', 'liability', 'disclaim', 'without prejudice'],
        'progress': ['progress', 'progress report', 'daily progress', 'weekly progress'],
    }

    # ── Document type indicators (English only, expanded) ──

    DOC_TYPE_INDICATORS = {
        'letter': ['dear', 'sincerely', 'regards', 'kind regards', 'best regards',
                    'yours faithfully', 'yours sincerely'],
        'notice': ['notice', 'notification', 'hereby notify', 'formal notice',
                    'notice of delay', 'notice of claim'],
        'report': ['report', 'summary', 'findings', 'daily progress report',
                    'weekly report', 'monthly report', 'inspection report'],
        'minutes': ['minutes', 'meeting', 'attendees', 'minutes of meeting',
                     'action items', 'agenda'],
        'contract': ['contract', 'agreement', 'terms and conditions', 'conditions of contract',
                      'general conditions', 'particular conditions'],
        'invoice': ['invoice', 'amount due', 'payment', 'bill', 'tax invoice',
                     'interim payment certificate'],
        'transmittal': ['transmittal', 'transmitted', 'enclosed', 'herewith',
                         'please find attached', 'for your review'],
        'email': ['from:', 'sent:', 'to:', 'cc:', 'subject:', 'forwarded message'],
        'dpr': ['daily progress report', 'dpr', 'manpower', 'weather condition',
                'equipment on site', 'work description'],
    }

    # ── CC patterns ──

    CC_PATTERNS = [
        r'(?:CC|Cc|C\.C\.|Copy\s*to|Copies\s*to)\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:Carbon\s*Copy|Distribution)\s*[:]\s*(.+?)(?:\n|$)',
    ]

    # ── Project name patterns ──

    PROJECT_PATTERNS = [
        r'(?:Project)\s*(?:Name|Title)?\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:Contract)\s*(?:Name|Title)?\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:Re|Regarding)\s*[:]\s*(?:.*?)(Project\s+.+?)(?:\n|,|$)',
        # TABH-specific: capture "The Address Boulevard Hotel" mentions
        r'(The\s+Address\s+Boulevard\s+Hotel(?:\s*[-–]\s*[A-Za-z\s]+)?)',
        r'(TABH\s*[-–:]\s*[A-Za-z\s]+)',
    ]

    # ── Contract reference patterns ──

    CONTRACT_REF_PATTERNS = [
        r'(?:Contract\s*(?:No|Number|Ref|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Agreement\s*(?:No|Number|Ref|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
    ]

    # ── Known project entities (for entity recognition) ──

    KNOWN_COMPANIES = [
        "TCI Engineering", "TCI", "BMM", "Dubai Properties", "DPS",
        "BMDXB", "Emaar", "Al Shafar", "Al Habtoor", "Arabtec",
        "Drake & Scull", "ALEC", "Shapoorji Pallonji",
    ]

    def __init__(self, use_llm_refinement: bool = False):
        """
        Initialize notice extractor.

        Args:
            use_llm_refinement: If True, use LLM to refine low-confidence fields
        """
        self.use_llm_refinement = use_llm_refinement
        self._jargon = None

        if use_llm_refinement:
            logger.info("[NoticeExtractor] Selective LLM refinement enabled (via llm_client)")

    @property
    def jargon(self):
        """Lazy-load jargon manager."""
        if self._jargon is None:
            from .jargon_manager import get_jargon_manager
            self._jargon = get_jargon_manager()
        return self._jargon

    def extract_notice(
        self,
        doc_id: str,
        file_path: str,
        doc_text_by_page: Dict[int, str],
        project_id: Optional[str] = None,
    ) -> NoticeMetadata:
        """
        Extract notice metadata from document.

        Args:
            doc_id: Unique document identifier
            file_path: Path to source file
            doc_text_by_page: Dict mapping page numbers to text content
            project_id: Optional project identifier

        Returns:
            NoticeMetadata with extracted fields and evidence
        """
        logger.info(f"[NoticeExtractor] Extracting notice from: {Path(file_path).name}")

        # OCR post-processing: clean all page texts
        cleaned_pages = {p: ocr_cleanup(text) for p, text in doc_text_by_page.items()}

        # Combine all text for full-doc analysis
        full_text = "\n\n".join(
            f"[PAGE {p}]\n{text}" for p, text in sorted(cleaned_pages.items())
        )

        # Focus on header area (first 2 pages typically have metadata)
        header_pages = {p: t for p, t in cleaned_pages.items() if p <= 2}
        header_text = "\n".join(header_pages.values())

        # Footer/signature area (last page)
        last_page_num = max(cleaned_pages.keys()) if cleaned_pages else 1
        footer_text = cleaned_pages.get(last_page_num, "")

        evidence_spans = []

        # Extract fields with regex
        date, date_evidence = self._extract_date(header_text, cleaned_pages)
        if date_evidence:
            evidence_spans.append(date_evidence)

        sender, sender_evidence = self._extract_pattern(
            header_text, self.SENDER_PATTERNS, "sender", cleaned_pages
        )
        if sender_evidence:
            evidence_spans.append(sender_evidence)

        # Try signature block extraction if header sender not found
        sender_title = None
        sender_company = None
        if not sender:
            sig_result = self._extract_sender_from_signature(full_text, cleaned_pages)
            if sig_result:
                sender = sig_result['name']
                sender_title = sig_result.get('title')
                sender_company = sig_result.get('company')
                if sig_result.get('evidence'):
                    evidence_spans.append(sig_result['evidence'])

        recipient, recipient_evidence = self._extract_pattern(
            header_text, self.RECIPIENT_PATTERNS, "recipient", cleaned_pages
        )
        if recipient_evidence:
            evidence_spans.append(recipient_evidence)

        # Try "Dear Mr./Ms. X" extraction if no recipient found
        recipient_title = None
        if not recipient:
            dear_result = self._extract_recipient_from_dear(header_text, cleaned_pages)
            if dear_result:
                recipient = dear_result['name']
                recipient_title = dear_result.get('title')
                if dear_result.get('evidence'):
                    evidence_spans.append(dear_result['evidence'])

        subject, subject_evidence = self._extract_pattern(
            header_text, self.SUBJECT_PATTERNS, "subject", cleaned_pages
        )
        if subject_evidence:
            evidence_spans.append(subject_evidence)

        # Fuzzy-label fallback: scan header lines for "Label: Value" patterns
        fuzzy_results = self._fuzzy_label_fallback(header_text, cleaned_pages)
        if not date and fuzzy_results.get("date"):
            date = fuzzy_results["date"][0]
            evidence_spans.append(fuzzy_results["date"][1])
        if not sender and fuzzy_results.get("from"):
            sender = fuzzy_results["from"][0]
            evidence_spans.append(fuzzy_results["from"][1])
        if not recipient and fuzzy_results.get("to"):
            recipient = fuzzy_results["to"][0]
            evidence_spans.append(fuzzy_results["to"][1])
        if not subject and fuzzy_results.get("subject"):
            subject = fuzzy_results["subject"][0]
            evidence_spans.append(fuzzy_results["subject"][1])

        # Extract references from full document
        ref_numbers, ref_evidence = self._extract_references(full_text, cleaned_pages)
        evidence_spans.extend(ref_evidence)

        # Extract referenced documents
        referenced_docs = self._extract_referenced_docs(full_text)

        # Detect document type
        doc_type = self._detect_doc_type(full_text)

        # Extract actions
        actions, action_evidence = self._extract_actions(full_text, cleaned_pages)
        evidence_spans.extend(action_evidence)

        # Extract deadlines
        deadlines, deadline_evidence = self._extract_deadlines(full_text, cleaned_pages)
        evidence_spans.extend(deadline_evidence)

        # Extract key topics
        key_topics = self._extract_topics(full_text, subject)

        # Extract CC list
        cc_list = self._extract_cc(header_text)

        # Extract project name
        project_name = self._extract_project_name(header_text, full_text)

        # Extract contract reference
        contract_ref = self._extract_contract_ref(full_text)

        # Determine communication direction
        direction = self._detect_direction(sender, recipient, full_text)

        # Find jargon terms in document
        jargon_found = self.jargon.find_related_terms(full_text)

        # Build notice
        notice = NoticeMetadata(
            doc_id=doc_id,
            file_path=file_path,
            file_name=Path(file_path).name,
            language="en",
            doc_type=doc_type,
            date=date,
            sender=sender,
            sender_title=sender_title,
            sender_company=sender_company,
            recipient=recipient,
            recipient_title=recipient_title,
            subject=subject,
            cc_list=cc_list,
            direction=direction,
            ref_numbers=ref_numbers,
            referenced_docs=referenced_docs,
            contract_ref=contract_ref,
            project_name=project_name,
            key_topics=key_topics,
            actions=actions,
            deadlines=deadlines,
            jargon_found=[{"abbreviation": j["abbreviation"], "meaning": j["meaning"]} for j in jargon_found[:20]],
            evidence_spans=[asdict(e) if hasattr(e, '__dataclass_fields__') else e for e in evidence_spans],
            extraction_method="regex",
            project_id=project_id,
        )

        # Optional LLM refinement (selective: only for low-confidence fields)
        if self.use_llm_refinement:
            notice = self._refine_with_llm(notice, header_text, evidence_spans)

        logger.info(f"[NoticeExtractor] Extracted: date={date}, sender={sender[:30] if sender else None}...")

        return notice

    # ── Date Extraction ──────────────────────────────────────

    def _extract_date(
        self,
        text: str,
        pages: Dict[int, str]
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Extract and normalize date. Searches near 'Date:' label first."""
        # Priority: look for "Date:" labeled field first
        date_label_match = re.search(
            r'(?:Date|Dated)\s*[:]\s*(.{5,40})',
            text, re.IGNORECASE
        )
        if date_label_match:
            date_value = date_label_match.group(1).strip()
            for pattern, fmt in self.DATE_PATTERNS:
                dm = re.search(pattern, date_value, re.IGNORECASE)
                if dm:
                    raw_date = dm.group(1)
                    normalized = self._normalize_date(raw_date, fmt)
                    page = self._find_page(date_label_match.group(0), pages)
                    evidence = {
                        "page": page,
                        "snippet": self._get_context(text, date_label_match.start(), date_label_match.end()),
                        "field_name": "date",
                        "confidence": 0.95,
                    }
                    return normalized or raw_date, evidence

        # Fallback: scan for any date pattern in header
        for pattern, fmt in self.DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_date = match.group(1)
                normalized = self._normalize_date(raw_date, fmt)
                page = self._find_page(match.group(0), pages)

                evidence = {
                    "page": page,
                    "snippet": self._get_context(text, match.start(), match.end()),
                    "field_name": "date",
                    "confidence": 0.9 if normalized else 0.7,
                }
                return normalized or raw_date, evidence

        return None, None

    def _normalize_date(self, raw: str, fmt: str) -> Optional[str]:
        """Normalize date to ISO format YYYY-MM-DD."""
        try:
            if fmt == 'iso':
                parts = re.split(r'[-/]', raw)
                return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"

            elif fmt == 'dmy':
                parts = re.split(r'[-/.]', raw)
                day, month, year = parts[0], parts[1], parts[2]
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

            elif fmt == 'dmy_short':
                # 2-digit year: 15.01.24 -> 2024-01-15
                parts = re.split(r'[-/.]', raw)
                day, month, year_short = parts[0], parts[1], parts[2]
                # Assume 2000s for 2-digit years (00-99 -> 2000-2099)
                year = f"20{year_short}" if len(year_short) == 2 else year_short
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

            elif fmt in ('written', 'written_us', 'written_short'):
                months = {
                    'january': '01', 'february': '02', 'march': '03', 'april': '04',
                    'may': '05', 'june': '06', 'july': '07', 'august': '08',
                    'september': '09', 'october': '10', 'november': '11', 'december': '12',
                    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
                    'jun': '06', 'jul': '07', 'aug': '08',
                    'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
                }
                clean = re.sub(r'(st|nd|rd|th)', '', raw.lower()).strip()
                clean = re.sub(r'[,]', ' ', clean)
                for month_name, num in months.items():
                    if month_name in clean:
                        day_match = re.search(r'\d{1,2}', clean)
                        year_match = re.search(r'\d{4}', clean)
                        if day_match and year_match:
                            day = day_match.group()
                            year = year_match.group()
                            return f"{year}-{num}-{day.zfill(2)}"
                        break

        except Exception:
            pass
        return None

    # ── Signature Block Extraction ───────────────────────────

    def _extract_sender_from_signature(
        self,
        text: str,
        pages: Dict[int, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Extract sender name, title, and company from signature block.
        Looks for "Kind Regards" / "Best Regards" / "Sincerely" followed by name.
        """
        for pattern in self.SIGNATURE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Validate: must look like a person's name (2+ words, starts with capital)
                if len(name) > 3 and re.match(r'^[A-Z]', name):
                    # Clean up: remove trailing punctuation and whitespace
                    name = re.sub(r'[\s,.:]+$', '', name).strip()

                    page = self._find_page(match.group(0), pages)
                    result = {
                        'name': name[:100],
                        'evidence': {
                            "page": page,
                            "snippet": self._get_context(text, match.start(), match.end()),
                            "field_name": "sender_signature",
                            "confidence": 0.80,
                        },
                    }

                    # Try to get title/company from lines after name
                    after_name_start = match.end()
                    after_text = text[after_name_start:after_name_start + 200]
                    lines_after = [l.strip() for l in after_text.split('\n') if l.strip()]

                    if lines_after:
                        # First non-empty line after name is likely title
                        potential_title = lines_after[0]
                        if len(potential_title) > 3 and not re.match(r'^[0-9(+]', potential_title):
                            result['title'] = potential_title[:100]
                        # Second line might be company
                        if len(lines_after) > 1:
                            potential_company = lines_after[1]
                            if len(potential_company) > 3 and not re.match(r'^[0-9(+]', potential_company):
                                result['company'] = potential_company[:100]

                    return result

        return None

    # ── Recipient "Dear X" Extraction ────────────────────────

    def _extract_recipient_from_dear(
        self,
        text: str,
        pages: Dict[int, str],
    ) -> Optional[Dict[str, Any]]:
        """Extract recipient from 'Dear Mr./Ms. X' salutation."""
        # "Dear Mr. Smith," or "Dear Sir/Madam,"
        patterns = [
            r'Dear\s+(Mr\.?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
            r'Dear\s+(Ms\.?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
            r'Dear\s+(Mrs\.?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
            r'Dear\s+(Dr\.?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
            r'Dear\s+(Eng\.?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)',
            r'Dear\s+(Sir|Madam|Sir/Madam|Sirs)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip().rstrip(',')
                # Extract title prefix
                title = None
                title_match = re.match(r'(Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Eng\.?)\s+', name)
                if title_match:
                    title = title_match.group(1)

                page = self._find_page(match.group(0), pages)
                return {
                    'name': name[:100],
                    'title': title,
                    'evidence': {
                        "page": page,
                        "snippet": self._get_context(text, match.start(), match.end()),
                        "field_name": "recipient_dear",
                        "confidence": 0.85,
                    },
                }
        return None

    # ── Generic Pattern Extraction ───────────────────────────

    def _fuzzy_label_fallback(
        self,
        header_text: str,
        pages: Dict[int, str],
    ) -> Dict[str, Optional[Tuple[str, Dict]]]:
        """
        Scan header lines for "Label: Value" patterns using fuzzy matching.
        Returns dict mapping canonical field names to (value, evidence) tuples.
        """
        results: Dict[str, Optional[Tuple[str, Dict]]] = {}

        for line in header_text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Match "SomeLabel : SomeValue" or "SomeLabel: SomeValue"
            m = re.match(r'^([A-Za-z\s]{2,30})\s*:\s*(.+)$', line)
            if not m:
                continue

            raw_label = m.group(1).strip()
            raw_value = m.group(2).strip()

            if len(raw_value) < 2:
                continue

            canonical = _fuzzy_match_label(raw_label)
            if canonical and canonical not in results:
                page = self._find_page(line, pages)
                evidence = {
                    "page": page,
                    "snippet": line[:200],
                    "field_name": canonical,
                    "confidence": 0.65,
                }

                # For date fields, try to normalize
                if canonical == "date":
                    for pattern, fmt in self.DATE_PATTERNS:
                        dm = re.search(pattern, raw_value, re.IGNORECASE)
                        if dm:
                            normalized = self._normalize_date(dm.group(1), fmt)
                            raw_value = normalized or dm.group(1)
                            evidence["confidence"] = 0.7
                            break

                results[canonical] = (raw_value[:200], evidence)

        return results

    def _extract_pattern(
        self,
        text: str,
        patterns: List[str],
        field_name: str,
        pages: Dict[int, str],
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Extract field using pattern list."""
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                value = match.group(1).strip()
                if len(value) > 3:  # Minimum meaningful length
                    page = self._find_page(match.group(0), pages)
                    evidence = {
                        "page": page,
                        "snippet": self._get_context(text, match.start(), match.end()),
                        "field_name": field_name,
                        "confidence": 0.85,
                    }
                    return value[:200], evidence

        return None, None

    def _extract_references(
        self,
        text: str,
        pages: Dict[int, str],
    ) -> Tuple[List[str], List[Dict]]:
        """Extract reference numbers."""
        refs = []
        evidence = []
        seen = set()

        for pattern in self.REF_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                ref = match.group(1).strip()
                if ref and ref not in seen and len(ref) >= 4:
                    # Filter out obvious false positives (page markers, etc.)
                    if ref.startswith('PAGE') or ref.startswith('http'):
                        continue
                    seen.add(ref)
                    refs.append(ref)
                    page = self._find_page(match.group(0), pages)
                    evidence.append({
                        "page": page,
                        "snippet": self._get_context(text, match.start(), match.end()),
                        "field_name": "ref_number",
                        "confidence": 0.8,
                    })

        return refs[:10], evidence[:10]

    def _extract_referenced_docs(self, text: str) -> List[str]:
        """Extract mentions of other documents."""
        referenced = []

        patterns = [
            r'(?:referring to|reference to|in response to|replying to)\s+([^,.]+)',
            r'(?:your letter|your notice|your email)\s+(?:dated|of|ref)\s+([^,.]+)',
            r'(?:our previous|previous letter|earlier notice)\s+([^,.]+)',
            r'(?:attached|enclosed|annexed)\s+(?:herewith|hereto)?\s*(?:is|are)?\s*([^,.]+)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                ref = match.group(1).strip()[:100]
                if ref and len(ref) > 5:
                    referenced.append(ref)

        return referenced[:5]

    # ── Document Type Detection ──────────────────────────────

    def _detect_doc_type(self, text: str) -> Optional[str]:
        """Detect document type from content."""
        text_lower = text.lower()

        scores = {}
        for doc_type, indicators in self.DOC_TYPE_INDICATORS.items():
            score = sum(1 for ind in indicators if ind in text_lower)
            if score > 0:
                scores[doc_type] = score

        if scores:
            return max(scores, key=scores.get)
        return None

    # ── Action Extraction ────────────────────────────────────

    def _extract_actions(
        self,
        text: str,
        pages: Dict[int, str],
    ) -> Tuple[List[str], List[Dict]]:
        """Extract action keywords from text."""
        actions = []
        evidence = []
        text_lower = text.lower()

        for action, keywords in self.ACTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    if action not in actions:
                        actions.append(action)
                        idx = text_lower.find(keyword)
                        page = self._find_page_by_position(idx, pages, text)
                        evidence.append({
                            "page": page,
                            "snippet": self._get_context(text, idx, idx + len(keyword)),
                            "field_name": f"action:{action}",
                            "confidence": 0.7,
                        })
                    break

        return actions, evidence

    def _extract_deadlines(
        self,
        text: str,
        pages: Dict[int, str],
    ) -> Tuple[List[Dict], List[Dict]]:
        """Extract deadline mentions."""
        deadlines = []
        evidence = []

        patterns = [
            r'(?:deadline|due date|by|before|until|no later than)\s*[:.]?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})',
            r'(?:within|in)\s+(\d+)\s+(?:days?|weeks?|months?)',
            r'(?:deadline|due)\s*[:.]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'(?:not\s+later\s+than|on\s+or\s+before)\s+(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                deadline_text = match.group(1)
                context = self._get_context(text, match.start(), match.end())
                page = self._find_page(match.group(0), pages)

                deadlines.append({
                    "date": deadline_text,
                    "context": context[:150],
                })
                evidence.append({
                    "page": page,
                    "snippet": context,
                    "field_name": "deadline",
                    "confidence": 0.75,
                })

        return deadlines[:5], evidence[:5]

    def _extract_topics(self, text: str, subject: Optional[str]) -> List[str]:
        """Extract key topics."""
        topics = set()

        if subject:
            words = re.findall(r'\b[A-Za-z]{4,}\b', subject.lower())
            topics.update(w for w in words if w not in {'this', 'that', 'with', 'from', 'regarding', 'subject'})

        # Look for capitalized phrases (often topic indicators)
        caps_phrases = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text)
        for phrase in caps_phrases[:10]:
            if len(phrase) > 5:
                topics.add(phrase.lower())

        # Construction/contract topics
        topic_keywords = [
            'delay', 'extension', 'payment', 'variation', 'claim', 'completion',
            'termination', 'suspension', 'defects', 'warranty', 'milestone',
            'schedule', 'progress', 'approval', 'rejection', 'submission',
            'handover', 'inspection', 'safety', 'quality', 'procurement',
            'subcontractor', 'material', 'manpower', 'equipment',
        ]
        text_lower = text.lower()
        for kw in topic_keywords:
            if kw in text_lower:
                topics.add(kw)

        return list(topics)[:15]

    def _extract_cc(self, text: str) -> List[str]:
        """Extract CC recipients."""
        cc_list = []
        for pattern in self.CC_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                raw = match.group(1).strip()
                parts = re.split(r'[;,]', raw)
                for part in parts:
                    part = part.strip()
                    if part and len(part) > 2:
                        cc_list.append(part[:100])
                break
        return cc_list[:10]

    def _extract_project_name(self, header_text: str, full_text: str) -> Optional[str]:
        """Extract project name from document."""
        for pattern in self.PROJECT_PATTERNS:
            match = re.search(pattern, header_text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                if len(name) > 3:
                    return name[:150]

        # Check for known project names in text
        known_projects = [
            'The Address Boulevard Hotel',
            'TABH',
            'Address Boulevard',
        ]
        text_lower = full_text[:3000].lower()
        for proj in known_projects:
            if proj.lower() in text_lower:
                return proj

        # Try from content keywords
        file_keywords = ['project', 'contract']
        for kw in file_keywords:
            idx = text_lower.find(kw)
            if idx >= 0:
                end_idx = min(idx + 100, len(full_text))
                snippet = full_text[idx:end_idx]
                line_end = snippet.find('\n')
                if line_end > 0:
                    snippet = snippet[:line_end]
                if len(snippet) > 5:
                    return snippet.strip()[:150]

        return None

    def _extract_contract_ref(self, text: str) -> Optional[str]:
        """Extract contract reference number."""
        for pattern in self.CONTRACT_REF_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                ref = match.group(1).strip()
                if len(ref) >= 3:
                    return ref[:50]
        return None

    def _detect_direction(self, sender: Optional[str], recipient: Optional[str], text: str) -> Optional[str]:
        """Detect communication direction based on sender/recipient patterns."""
        text_lower = text[:1000].lower()

        outgoing_indicators = ['we hereby', 'we wish to', 'please be advised', 'we are writing',
                               'we would like', 'we kindly request', 'please note that',
                               'this is to inform', 'we refer to']
        incoming_indicators = ['we have received', 'in response to your', 'we acknowledge',
                               'your letter dated', 'we note your', 'receipt of your']
        internal_indicators = ['internal memo', 'internal note', 'for your information',
                               'for internal use', 'confidential']

        out_score = sum(1 for ind in outgoing_indicators if ind in text_lower)
        in_score = sum(1 for ind in incoming_indicators if ind in text_lower)
        int_score = sum(1 for ind in internal_indicators if ind in text_lower)

        if int_score > 0:
            return "internal"
        if out_score > in_score:
            return "outgoing"
        if in_score > out_score:
            return "incoming"
        return None

    # ── Utility Methods ──────────────────────────────────────

    def _find_page(self, snippet: str, pages: Dict[int, str]) -> int:
        """Find which page contains a snippet."""
        for page_num, page_text in pages.items():
            if snippet in page_text:
                return page_num
        return 1

    def _find_page_by_position(self, pos: int, pages: Dict[int, str], full_text: str) -> int:
        """Find page by position in combined text."""
        current_pos = 0
        for page_num in sorted(pages.keys()):
            page_text = pages[page_num]
            page_len = len(page_text) + 10
            if current_pos + page_len > pos:
                return page_num
            current_pos += page_len
        return 1

    def _get_context(self, text: str, start: int, end: int, window: int = 50) -> str:
        """Get surrounding context for a match."""
        ctx_start = max(0, start - window)
        ctx_end = min(len(text), end + window)
        context = text[ctx_start:ctx_end].replace('\n', ' ').strip()
        return f"...{context}..." if ctx_start > 0 or ctx_end < len(text) else context

    # ── LLM Refinement ───────────────────────────────────────

    def _refine_with_llm(
        self,
        notice: NoticeMetadata,
        header_text: str,
        evidence: List[Dict],
    ) -> NoticeMetadata:
        """
        Selective LLM refinement: only call LLM for fields with confidence
        below NOTICE_LLM_CONFIDENCE_THRESHOLD.
        """
        from .config import NOTICE_LLM_CONFIDENCE_THRESHOLD

        low_confidence_fields = []
        for e in evidence:
            conf = e.get('confidence', 1.0)
            if conf < NOTICE_LLM_CONFIDENCE_THRESHOLD:
                low_confidence_fields.append(e.get('field_name', 'unknown'))

        if not notice.date:
            low_confidence_fields.append('date')
        if not notice.sender:
            low_confidence_fields.append('sender')
        if not notice.recipient:
            low_confidence_fields.append('recipient')

        if not low_confidence_fields:
            logger.info("[NoticeExtractor] All fields high-confidence, skipping LLM")
            return notice

        logger.info(f"[NoticeExtractor] LLM refining low-confidence fields: {low_confidence_fields}")

        from . import llm_client
        from .prompt_security import build_system_prompt

        evidence_summary = "\n".join(
            f"- {e.get('field_name', 'unknown')}: \"{e.get('snippet', '')[:100]}\""
            for e in evidence[:15]
        )

        prompt = (
            "Given the evidence snippets below, normalize and validate the extracted fields.\n\n"
            "RULES:\n"
            "1. DO NOT INVENT information not present in evidence\n"
            "2. ONLY use the given snippets\n"
            "3. Return valid JSON matching the schema\n"
            "4. If a field cannot be determined from evidence, use null\n\n"
            f"FIELDS TO REFINE: {', '.join(low_confidence_fields)}\n\n"
            f"EVIDENCE:\n{evidence_summary}\n\n"
            f"HEADER TEXT (first 1000 chars):\n{header_text[:1000]}\n\n"
            f"CURRENT EXTRACTION:\n"
            f"- date: {notice.date}\n"
            f"- sender: {notice.sender}\n"
            f"- recipient: {notice.recipient}\n"
            f"- subject: {notice.subject}\n\n"
            'Return ONLY a JSON object with refined values:\n'
            '{"date": "YYYY-MM-DD or null", "sender": "string or null", '
            '"recipient": "string or null", "subject": "string or null"}'
        )
        system = build_system_prompt("You are a construction document metadata extractor.")

        try:
            resp = llm_client.generate_json(prompt, system=system)
            refined = resp.raw if isinstance(resp.raw, dict) else {}

            if refined.get('date') and len(refined['date']) == 10:
                notice.date = refined['date']
            if refined.get('sender') and len(refined['sender']) > 3:
                notice.sender = refined['sender']
            if refined.get('recipient') and len(refined['recipient']) > 3:
                notice.recipient = refined['recipient']
            if refined.get('subject') and len(refined['subject']) > 5:
                notice.subject = refined['subject']

            notice.extraction_method = "regex+llm_selective"
            logger.info("[NoticeExtractor] Selective LLM refinement applied")

        except Exception as e:
            logger.warning(f"[NoticeExtractor] LLM refinement failed: {e}")

        return notice

    # ── Persistence ──────────────────────────────────────────

    def save_notice(self, notice: NoticeMetadata) -> str:
        """Save notice to JSON file."""
        notice_path = NOTICES_DIR / f"{notice.doc_id}.json"

        with open(notice_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(notice), f, indent=2, ensure_ascii=False)

        logger.info(f"[NoticeExtractor] Saved notice: {notice_path.name}")
        try:
            from .gcs_storage import sync_uploaded_file_to_gcs
            sync_uploaded_file_to_gcs(str(notice_path))
        except Exception:
            pass
        return str(notice_path)

    def load_notice(self, doc_id: str) -> Optional[NoticeMetadata]:
        """Load notice from JSON file."""
        notice_path = NOTICES_DIR / f"{doc_id}.json"

        if not notice_path.exists():
            return None

        with open(notice_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return NoticeMetadata(**data)

    def list_notices(self) -> List[str]:
        """List all extracted notice doc_ids."""
        return [p.stem for p in NOTICES_DIR.glob("*.json")]

    def delete_notice(self, doc_id: str) -> bool:
        """Delete notice JSON for a given doc_id. Returns True if deleted."""
        notice_path = NOTICES_DIR / f"{doc_id}.json"
        if notice_path.exists():
            notice_path.unlink()
            try:
                from .gcs_storage import delete_uploaded_file_from_gcs
                delete_uploaded_file_from_gcs(str(notice_path))
            except Exception:
                pass
            logger.info(f"[Notice] Deleted notice: {doc_id}")
            return True
        return False


# Singleton
_extractor: Optional[NoticeExtractor] = None


def get_notice_extractor(use_llm: bool = False) -> NoticeExtractor:
    """Get or create NoticeExtractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = NoticeExtractor(use_llm_refinement=use_llm)
    return _extractor


def extract_and_save_notice(
    doc_id: str,
    file_path: str,
    doc_text_by_page: Dict[int, str],
    project_id: Optional[str] = None,
    use_llm: bool = False,
) -> Tuple[NoticeMetadata, str]:
    """
    Convenience function to extract and save notice.

    Returns:
        Tuple of (NoticeMetadata, path to saved JSON)
    """
    extractor = get_notice_extractor(use_llm)
    notice = extractor.extract_notice(doc_id, file_path, doc_text_by_page, project_id)
    path = extractor.save_notice(notice)
    return notice, path
