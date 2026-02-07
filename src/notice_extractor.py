"""
Notice Extractor - Extract structured metadata from documents.
Uses regex-first extraction with optional LLM refinement.
Every field includes evidence_spans for debuggability.
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
    doc_type: Optional[str] = None  # letter/notice/report/minutes/contract/invoice/transmittal
    date: Optional[str] = None  # ISO format YYYY-MM-DD
    sender: Optional[str] = None
    recipient: Optional[str] = None
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
    actions: List[str] = field(default_factory=list)  # submit, respond, approve, delay, claim
    deadlines: List[Dict[str, str]] = field(default_factory=list)  # {date, context}
    jargon_found: List[Dict[str, str]] = field(default_factory=list)  # [{abbreviation, meaning}]

    # Evidence
    evidence_spans: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    extraction_method: str = "regex"  # regex | regex+llm
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat())
    project_id: Optional[str] = None


class NoticeExtractor:
    """
    Extracts structured notice metadata from documents.
    Regex-first approach with optional LLM refinement.
    """

    # Date patterns (English, ISO, Turkish months)
    DATE_PATTERNS = [
        # ISO: 2024-01-15
        (r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b', 'iso'),
        # UK/EU: 15/01/2024, 15-01-2024, 15.01.2024
        (r'\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\b', 'dmy'),
        # US: 01/15/2024
        (r'\b(\d{1,2}/\d{1,2}/\d{4})\b', 'mdy'),
        # Written: January 15, 2024 | 15 January 2024
        (r'\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b', 'written'),
        (r'\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b', 'written_us'),
        # Turkish months
        (r'\b(\d{1,2}\s+(?:Ocak|Subat|Mart|Nisan|Mayis|Haziran|Temmuz|Agustos|Eylul|Ekim|Kasim|Aralik)\s+\d{4})\b', 'turkish'),
    ]

    # From/To patterns
    SENDER_PATTERNS = [
        r'(?:From|Sender|Kimden|Gonderen)\s*[:]\s*(.+?)(?:\n|$)',
        r'^From\s*:\s*(.+?)(?:\n|$)',
        r'(?:Sent by|Issued by)\s*[:]\s*(.+?)(?:\n|$)',
    ]

    RECIPIENT_PATTERNS = [
        r'(?:To|Recipient|Kime|Alici)\s*[:]\s*(.+?)(?:\n|$)',
        r'^To\s*:\s*(.+?)(?:\n|$)',
        r'(?:Attention|Attn|Dikkat)\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:For the attention of)\s*[:]\s*(.+?)(?:\n|$)',
    ]

    # Subject patterns
    SUBJECT_PATTERNS = [
        r'(?:Subject|Re|Regarding|Konu)\s*[:]\s*(.+?)(?:\n|$)',
        r'^Subject\s*:\s*(.+?)(?:\n|$)',
        r'(?:In re|Matter)\s*[:]\s*(.+?)(?:\n|$)',
    ]

    # Reference patterns
    REF_PATTERNS = [
        r'(?:Ref|Reference|Our Ref|Your Ref|Referans)\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Doc(?:ument)?\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Letter\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Contract\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Notice\s*(?:No|Number|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'\b([A-Z]{2,4}[-/]\d{3,}[-/]?\d*)\b',  # Common ref format: ABC-001-2024
    ]

    # Action keywords
    ACTION_KEYWORDS = {
        'submit': ['submit', 'submission', 'sunmak', 'teslim'],
        'respond': ['respond', 'response', 'reply', 'answer', 'cevap', 'yanit'],
        'approve': ['approve', 'approval', 'approved', 'onay', 'onaylamak'],
        'reject': ['reject', 'rejection', 'rejected', 'red', 'reddetmek'],
        'delay': ['delay', 'delayed', 'postpone', 'extension', 'gecikme', 'erteleme'],
        'claim': ['claim', 'claims', 'claiming', 'talep', 'hak talebi'],
        'notify': ['notify', 'notification', 'notice', 'bildirim', 'ihbar'],
        'request': ['request', 'requesting', 'istek', 'talep'],
        'confirm': ['confirm', 'confirmation', 'confirmed', 'teyit', 'onay'],
        'complete': ['complete', 'completed', 'completion', 'tamamlama', 'bitirme'],
        'terminate': ['terminate', 'termination', 'fesih', 'sonlandirma'],
        'suspend': ['suspend', 'suspension', 'askiya alma', 'durdurma'],
    }

    # Document type indicators
    DOC_TYPE_INDICATORS = {
        'letter': ['dear', 'sincerely', 'regards', 'saygilarimla', 'mektup'],
        'notice': ['notice', 'notification', 'hereby notify', 'bildirim', 'ihbar'],
        'report': ['report', 'summary', 'findings', 'rapor', 'ozet'],
        'minutes': ['minutes', 'meeting', 'attendees', 'tutanak', 'toplanti'],
        'contract': ['contract', 'agreement', 'terms', 'sozlesme', 'anlasma'],
        'invoice': ['invoice', 'amount due', 'payment', 'fatura', 'odeme'],
    }

    # CC patterns
    CC_PATTERNS = [
        r'(?:CC|Cc|Copy to|Copies to|Bilgi)\s*[:]\s*(.+?)(?:\n|$)',
    ]

    # Project name patterns
    PROJECT_PATTERNS = [
        r'(?:Project|Proje)\s*(?:Name|Title|Adi)?\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:Contract|Sozlesme)\s*(?:Name|Title|Adi)?\s*[:]\s*(.+?)(?:\n|$)',
        r'(?:Re|Regarding|Konu)\s*[:]\s*(?:.*?)(Project\s+.+?)(?:\n|,|$)',
    ]

    # Contract reference patterns
    CONTRACT_REF_PATTERNS = [
        r'(?:Contract\s*(?:No|Number|Ref|#))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
        r'(?:Sozlesme\s*(?:No|Numarasi|Ref))\s*[:.]?\s*([A-Za-z0-9\-_/]+)',
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

        # Combine all text for full-doc analysis
        full_text = "\n\n".join(
            f"[PAGE {p}]\n{text}" for p, text in sorted(doc_text_by_page.items())
        )

        # Focus on header area (first 2 pages typically have metadata)
        header_pages = {p: t for p, t in doc_text_by_page.items() if p <= 2}
        header_text = "\n".join(header_pages.values())

        evidence_spans = []

        # Extract fields with regex
        date, date_evidence = self._extract_date(header_text, doc_text_by_page)
        if date_evidence:
            evidence_spans.append(date_evidence)

        sender, sender_evidence = self._extract_pattern(
            header_text, self.SENDER_PATTERNS, "sender", doc_text_by_page
        )
        if sender_evidence:
            evidence_spans.append(sender_evidence)

        recipient, recipient_evidence = self._extract_pattern(
            header_text, self.RECIPIENT_PATTERNS, "recipient", doc_text_by_page
        )
        if recipient_evidence:
            evidence_spans.append(recipient_evidence)

        subject, subject_evidence = self._extract_pattern(
            header_text, self.SUBJECT_PATTERNS, "subject", doc_text_by_page
        )
        if subject_evidence:
            evidence_spans.append(subject_evidence)

        # Extract references from full document
        ref_numbers, ref_evidence = self._extract_references(full_text, doc_text_by_page)
        evidence_spans.extend(ref_evidence)

        # Extract referenced documents
        referenced_docs = self._extract_referenced_docs(full_text)

        # Detect language
        language = self._detect_language(full_text)

        # Detect document type
        doc_type = self._detect_doc_type(full_text)

        # Extract actions
        actions, action_evidence = self._extract_actions(full_text, doc_text_by_page)
        evidence_spans.extend(action_evidence)

        # Extract deadlines
        deadlines, deadline_evidence = self._extract_deadlines(full_text, doc_text_by_page)
        evidence_spans.extend(deadline_evidence)

        # Extract key topics (simple keyword extraction)
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
            language=language,
            doc_type=doc_type,
            date=date,
            sender=sender,
            recipient=recipient,
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

        # Optional LLM refinement
        if self.use_llm_refinement and self.llm:
            notice = self._refine_with_llm(notice, header_text, evidence_spans)

        logger.info(f"[NoticeExtractor] Extracted: date={date}, sender={sender[:30] if sender else None}...")

        return notice

    def _extract_date(
        self,
        text: str,
        pages: Dict[int, str]
    ) -> Tuple[Optional[str], Optional[Dict]]:
        """Extract and normalize date."""
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
        """Normalize date to ISO format."""
        try:
            if fmt == 'iso':
                parts = re.split(r'[-/]', raw)
                return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"

            elif fmt == 'dmy':
                parts = re.split(r'[-/.]', raw)
                return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"

            elif fmt == 'mdy':
                parts = raw.split('/')
                return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"

            elif fmt in ('written', 'written_us'):
                # Parse written dates
                months = {
                    'january': '01', 'february': '02', 'march': '03', 'april': '04',
                    'may': '05', 'june': '06', 'july': '07', 'august': '08',
                    'september': '09', 'october': '10', 'november': '11', 'december': '12'
                }
                clean = re.sub(r'(st|nd|rd|th)', '', raw.lower())
                for month, num in months.items():
                    if month in clean:
                        day = re.search(r'\d{1,2}', clean).group()
                        year = re.search(r'\d{4}', clean).group()
                        return f"{year}-{num}-{day.zfill(2)}"

            elif fmt == 'turkish':
                months_tr = {
                    'ocak': '01', 'subat': '02', 'mart': '03', 'nisan': '04',
                    'mayis': '05', 'haziran': '06', 'temmuz': '07', 'agustos': '08',
                    'eylul': '09', 'ekim': '10', 'kasim': '11', 'aralik': '12'
                }
                clean = raw.lower()
                for month, num in months_tr.items():
                    if month in clean:
                        day = re.search(r'\d{1,2}', clean).group()
                        year = re.search(r'\d{4}', clean).group()
                        return f"{year}-{num}-{day.zfill(2)}"

        except Exception:
            pass
        return None

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
                    return value[:200], evidence  # Limit length

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
                    seen.add(ref)
                    refs.append(ref)
                    page = self._find_page(match.group(0), pages)
                    evidence.append({
                        "page": page,
                        "snippet": self._get_context(text, match.start(), match.end()),
                        "field_name": "ref_number",
                        "confidence": 0.8,
                    })

        return refs[:10], evidence[:10]  # Limit to 10 refs

    def _extract_referenced_docs(self, text: str) -> List[str]:
        """Extract mentions of other documents."""
        referenced = []

        # Look for explicit document references
        patterns = [
            r'(?:referring to|reference to|in response to|replying to)\s+([^,.]+)',
            r'(?:your letter|your notice|your email)\s+(?:dated|of|ref)\s+([^,.]+)',
            r'(?:our previous|previous letter|earlier notice)\s+([^,.]+)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                ref = match.group(1).strip()[:100]
                if ref and len(ref) > 5:
                    referenced.append(ref)

        return referenced[:5]

    def _detect_language(self, text: str) -> str:
        """Simple language detection."""
        text_lower = text.lower()

        # Turkish indicators
        turkish_chars = len(re.findall(r'[ığüşöçİĞÜŞÖÇ]', text))
        turkish_words = ['ve', 'ile', 'için', 'olan', 'tarafindan', 'konu', 'sayin']
        turkish_score = turkish_chars + sum(3 for w in turkish_words if w in text_lower)

        # English indicators
        english_words = ['the', 'and', 'for', 'with', 'regarding', 'dear', 'sincerely']
        english_score = sum(3 for w in english_words if w in text_lower)

        if turkish_score > english_score + 5:
            return "tr"
        return "en"

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
                        # Find first occurrence for evidence
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

        # Patterns for deadlines
        patterns = [
            r'(?:deadline|due date|by|before|until|no later than)\s*[:.]?\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})',
            r'(?:within|in)\s+(\d+)\s+(?:days?|weeks?|months?)',
            r'(?:deadline|due)\s*[:.]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
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
        """Extract key topics (simple keyword extraction)."""
        topics = set()

        # Add subject words as topics
        if subject:
            words = re.findall(r'\b[A-Za-z]{4,}\b', subject.lower())
            topics.update(w for w in words if w not in {'this', 'that', 'with', 'from', 'regarding'})

        # Look for capitalized phrases (often topic indicators)
        caps_phrases = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text)
        for phrase in caps_phrases[:10]:
            if len(phrase) > 5:
                topics.add(phrase.lower())

        # Common construction/contract topics
        topic_keywords = [
            'delay', 'extension', 'payment', 'variation', 'claim', 'completion',
            'termination', 'suspension', 'defects', 'warranty', 'milestone',
            'schedule', 'progress', 'approval', 'rejection', 'submission',
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
                # Split by comma or semicolon
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

        # Try from file name
        file_keywords = ['project', 'proje', 'contract', 'sozlesme']
        text_lower = full_text[:2000].lower()
        for kw in file_keywords:
            idx = text_lower.find(kw)
            if idx >= 0:
                # Get the next line or phrase
                end_idx = min(idx + 100, len(full_text))
                snippet = full_text[idx:end_idx]
                # Extract until newline
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

        # Look for direction indicators
        outgoing_indicators = ['we hereby', 'we wish to', 'please be advised', 'we are writing',
                               'we would like', 'tarafimizdan', 'size bildirmek']
        incoming_indicators = ['we have received', 'in response to your', 'we acknowledge',
                               'your letter dated', 'tarafinizdan', 'mektubunuza']
        internal_indicators = ['internal memo', 'internal note', 'for your information',
                               'ic yazisma', 'dahili']

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

    def _find_page(self, snippet: str, pages: Dict[int, str]) -> int:
        """Find which page contains a snippet."""
        for page_num, page_text in pages.items():
            if snippet in page_text:
                return page_num
        return 1  # Default to first page

    def _find_page_by_position(self, pos: int, pages: Dict[int, str], full_text: str) -> int:
        """Find page by position in combined text."""
        current_pos = 0
        for page_num in sorted(pages.keys()):
            page_text = pages[page_num]
            page_len = len(page_text) + 10  # Account for page markers
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

    def _refine_with_llm(
        self,
        notice: NoticeMetadata,
        header_text: str,
        evidence: List[Dict],
    ) -> NoticeMetadata:
        """
        Selective LLM refinement: only call LLM for fields with confidence
        below NOTICE_LLM_CONFIDENCE_THRESHOLD. Uses llm_client for caching
        and cost tracking.
        """
        from .config import NOTICE_LLM_CONFIDENCE_THRESHOLD

        # Determine which fields need refinement
        low_confidence_fields = []
        for e in evidence:
            conf = e.get('confidence', 1.0)
            if conf < NOTICE_LLM_CONFIDENCE_THRESHOLD:
                low_confidence_fields.append(e.get('field_name', 'unknown'))

        # Also flag missing critical fields
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

        # Build compact prompt with only relevant evidence
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
        system = build_system_prompt("You are a document metadata extractor.")

        try:
            resp = llm_client.generate_json(prompt, system=system)
            refined = resp.raw if isinstance(resp.raw, dict) else {}

            # Apply refinements only if they seem valid
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

    def save_notice(self, notice: NoticeMetadata) -> str:
        """Save notice to JSON file."""
        notice_path = NOTICES_DIR / f"{notice.doc_id}.json"

        with open(notice_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(notice), f, indent=2, ensure_ascii=False)

        logger.info(f"[NoticeExtractor] Saved notice: {notice_path.name}")
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
