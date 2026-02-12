"""
Document Understanding Agent - Intelligent agent structure for construction document analysis.

Provides three levels of understanding:
1. Document-level: Entity extraction, claim identification, key facts
2. Relationship-level: Cross-document references, reply chains, topic clusters
3. Project-level: Timeline reconstruction, party interaction maps, issue tracking

Uses regex-first extraction with selective LLM enhancement for complex analysis.
"""
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from .logger import logger
from .config import BASE_DIR

# Agent data directory
AGENT_DIR = BASE_DIR / "data" / "agent"
AGENT_DIR.mkdir(parents=True, exist_ok=True)


# ── Data Models ──────────────────────────────────────────────

@dataclass
class EntityMention:
    """An entity extracted from a document."""
    entity_type: str  # person, company, project, location, amount, date, reference
    value: str
    context: str  # surrounding text snippet
    doc_id: str
    page: int = 1
    confidence: float = 0.8


@dataclass
class DocumentClaim:
    """A claim or assertion found in a document."""
    claim_type: str  # delay, cost, completion, responsibility, instruction, request
    description: str
    parties_involved: List[str] = field(default_factory=list)
    evidence_snippet: str = ""
    doc_id: str = ""
    date: Optional[str] = None
    confidence: float = 0.7


@dataclass
class DocumentRelationship:
    """A relationship between two documents."""
    doc_a: str
    doc_b: str
    relationship_type: str  # reply_to, references, supersedes, contradicts, supports
    strength: float = 0.5
    reason: str = ""


@dataclass
class ProjectInsight:
    """A project-level insight derived from multiple documents."""
    insight_type: str  # delay_pattern, cost_trend, communication_gap, unresolved_issue
    description: str
    supporting_docs: List[str] = field(default_factory=list)
    severity: str = "medium"  # low, medium, high, critical
    date_range: Optional[str] = None


@dataclass
class ProjectProfile:
    """Aggregated project-level understanding."""
    project_name: str
    parties: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # party -> {role, doc_count, ...}
    key_issues: List[str] = field(default_factory=list)
    timeline_summary: List[Dict[str, str]] = field(default_factory=list)
    insights: List[ProjectInsight] = field(default_factory=list)
    doc_count: int = 0
    date_range: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Entity Extraction ────────────────────────────────────────

class EntityExtractor:
    """Extracts named entities from construction documents."""

    # Person name patterns
    PERSON_PATTERNS = [
        r'(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Eng\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})',
        r'(?:Dear|Attention|Attn)\s+(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Eng\.?)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})',
        r'(?:Kind\s+Regards|Best\s+Regards|Sincerely)\s*[,.]?\s*\n+\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})',
    ]

    # Company name patterns
    COMPANY_PATTERNS = [
        r'\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+(?:LLC|Ltd|Inc|Corp|Co\.|Group|Engineering|Construction|Properties|Contracting))\b',
        r'\b((?:Al\s+)?[A-Z][a-z]+(?:\s+(?:&|and)\s+[A-Z][a-z]+)*\s+(?:LLC|Ltd|Inc|Corp|Co\.))\b',
    ]

    # Money/amount patterns
    AMOUNT_PATTERNS = [
        r'\b(AED\s*[\d,]+(?:\.\d{2})?)\b',
        r'\b(USD\s*[\d,]+(?:\.\d{2})?)\b',
        r'\b(\$[\d,]+(?:\.\d{2})?)\b',
        r'\b([\d,]+(?:\.\d{2})?\s*(?:AED|USD|EUR|GBP))\b',
    ]

    # Duration/period patterns
    DURATION_PATTERNS = [
        r'\b(\d+)\s+(?:calendar\s+)?days?\b',
        r'\b(\d+)\s+(?:calendar\s+)?months?\b',
        r'\b(\d+)\s+(?:calendar\s+)?weeks?\b',
    ]

    def extract_entities(
        self,
        text: str,
        doc_id: str,
        pages: Optional[Dict[int, str]] = None,
    ) -> List[EntityMention]:
        """Extract all entities from document text."""
        entities = []

        # Extract persons
        for pattern in self.PERSON_PATTERNS:
            for match in re.finditer(pattern, text):
                name = match.group(1).strip()
                if len(name) > 3 and not name.isupper():
                    entities.append(EntityMention(
                        entity_type="person",
                        value=name,
                        context=text[max(0, match.start()-30):match.end()+30],
                        doc_id=doc_id,
                        confidence=0.85,
                    ))

        # Extract companies
        for pattern in self.COMPANY_PATTERNS:
            for match in re.finditer(pattern, text):
                company = match.group(1).strip()
                if len(company) > 5:
                    entities.append(EntityMention(
                        entity_type="company",
                        value=company,
                        context=text[max(0, match.start()-30):match.end()+30],
                        doc_id=doc_id,
                        confidence=0.80,
                    ))

        # Extract amounts
        for pattern in self.AMOUNT_PATTERNS:
            for match in re.finditer(pattern, text):
                entities.append(EntityMention(
                    entity_type="amount",
                    value=match.group(1).strip(),
                    context=text[max(0, match.start()-30):match.end()+30],
                    doc_id=doc_id,
                    confidence=0.90,
                ))

        # Extract durations
        for pattern in self.DURATION_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                full_match = match.group(0)
                entities.append(EntityMention(
                    entity_type="duration",
                    value=full_match,
                    context=text[max(0, match.start()-30):match.end()+30],
                    doc_id=doc_id,
                    confidence=0.85,
                ))

        # Deduplicate by value
        seen = set()
        unique_entities = []
        for e in entities:
            key = (e.entity_type, e.value.lower())
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)

        return unique_entities


# ── Claim Extraction ─────────────────────────────────────────

class ClaimExtractor:
    """Extracts claims, assertions, and key statements from construction documents."""

    CLAIM_PATTERNS = {
        'delay': [
            r'(?:delay|delayed|postponement|behind\s+schedule|slippage)\s+(?:of|in|to)\s+(.{10,100})',
            r'(?:extension\s+of\s+time|EOT)\s+(?:for|due\s+to|of)\s+(.{10,100})',
            r'(?:critical\s+path|programme|schedule)\s+(?:has\s+been|is|was)\s+(?:delayed|impacted|affected)\s+(.{10,100})',
        ],
        'cost': [
            r'(?:additional\s+cost|extra\s+cost|cost\s+overrun|price\s+increase)\s+(?:of|for)\s+(.{10,100})',
            r'(?:claim|entitlement)\s+(?:for|of)\s+(.{10,100})',
            r'(?:invoice|payment|amount\s+due)\s+(?:of|for)\s+(.{10,100})',
        ],
        'completion': [
            r'(?:substantial\s+completion|practical\s+completion|handover)\s+(?:of|for|date)\s*(?:is|was|shall\s+be)?\s*(.{10,100})',
            r'(?:completion\s+date|target\s+date|milestone)\s+(?:is|was|shall\s+be)\s+(.{10,100})',
        ],
        'responsibility': [
            r'(?:responsibility|liable|liability|obligation)\s+(?:of|for|to)\s+(.{10,100})',
            r'(?:without\s+prejudice|disclaim|not\s+responsible)\s+(.{10,100})',
            r'(?:hereby\s+notify|formally\s+notify)\s+(.{10,100})',
        ],
        'instruction': [
            r'(?:hereby\s+instruct|please\s+(?:ensure|arrange|proceed|provide))\s+(.{10,100})',
            r'(?:you\s+are\s+(?:required|instructed|directed)\s+to)\s+(.{10,100})',
        ],
        'request': [
            r'(?:kindly\s+(?:provide|submit|arrange|confirm))\s+(.{10,100})',
            r'(?:request\s+(?:for|to|that))\s+(.{10,100})',
            r'(?:please\s+(?:provide|submit|arrange|confirm|note))\s+(.{10,100})',
        ],
    }

    def extract_claims(
        self,
        text: str,
        doc_id: str,
        date: Optional[str] = None,
    ) -> List[DocumentClaim]:
        """Extract claims and key assertions from document text."""
        claims = []
        text_lower = text.lower()

        for claim_type, patterns in self.CLAIM_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    description = match.group(1).strip() if match.groups() else match.group(0).strip()
                    # Clean up the description
                    description = re.sub(r'\s+', ' ', description).strip()
                    description = description.rstrip('.,;')

                    if len(description) > 10:
                        claims.append(DocumentClaim(
                            claim_type=claim_type,
                            description=description[:200],
                            evidence_snippet=text[max(0, match.start()-50):match.end()+50][:300],
                            doc_id=doc_id,
                            date=date,
                            confidence=0.7,
                        ))
                        break  # One claim per type per pattern group

        return claims


# ── Relationship Extraction ──────────────────────────────────

class RelationshipExtractor:
    """Extracts and infers relationships between documents."""

    def extract_relationships(
        self,
        notices: List[Dict[str, Any]],
    ) -> List[DocumentRelationship]:
        """
        Extract relationships between documents based on:
        - Shared reference numbers
        - Reply patterns (sender/recipient swap)
        - Subject line similarity
        - Chronological proximity
        - Explicit cross-references
        """
        relationships = []
        n = len(notices)

        for i in range(n):
            for j in range(i + 1, n):
                doc_a = notices[i]
                doc_b = notices[j]

                rels = self._find_relationships(doc_a, doc_b)
                relationships.extend(rels)

        # Sort by strength descending
        relationships.sort(key=lambda r: r.strength, reverse=True)
        return relationships

    def _find_relationships(
        self,
        doc_a: Dict[str, Any],
        doc_b: Dict[str, Any],
    ) -> List[DocumentRelationship]:
        """Find all relationships between two documents."""
        rels = []
        id_a = doc_a.get('doc_id', '')
        id_b = doc_b.get('doc_id', '')

        # 1. Shared reference numbers
        refs_a = set(doc_a.get('ref_numbers', []))
        refs_b = set(doc_b.get('ref_numbers', []))
        shared_refs = refs_a & refs_b
        if shared_refs:
            rels.append(DocumentRelationship(
                doc_a=id_a,
                doc_b=id_b,
                relationship_type='references',
                strength=min(1.0, 0.6 + len(shared_refs) * 0.1),
                reason=f"Shared references: {', '.join(list(shared_refs)[:3])}",
            ))

        # 2. Reply pattern (A's recipient is B's sender and vice versa)
        sender_a = (doc_a.get('sender') or '').lower().strip()
        recip_a = (doc_a.get('recipient') or '').lower().strip()
        sender_b = (doc_b.get('sender') or '').lower().strip()
        recip_b = (doc_b.get('recipient') or '').lower().strip()

        if sender_a and recip_a and sender_b and recip_b:
            if self._names_match(recip_a, sender_b) and self._names_match(sender_a, recip_b):
                date_a = doc_a.get('date', '')
                date_b = doc_b.get('date', '')
                if date_a and date_b and date_b > date_a:
                    rels.append(DocumentRelationship(
                        doc_a=id_a,
                        doc_b=id_b,
                        relationship_type='reply_to',
                        strength=0.85,
                        reason=f"{sender_b} replied to {sender_a}",
                    ))

        # 3. Subject similarity
        subj_a = (doc_a.get('subject') or '').lower()
        subj_b = (doc_b.get('subject') or '').lower()
        if subj_a and subj_b:
            words_a = set(re.findall(r'\b\w{4,}\b', subj_a))
            words_b = set(re.findall(r'\b\w{4,}\b', subj_b))
            if words_a and words_b:
                overlap = words_a & words_b
                union = words_a | words_b
                jaccard = len(overlap) / len(union) if union else 0
                if jaccard > 0.3:
                    rels.append(DocumentRelationship(
                        doc_a=id_a,
                        doc_b=id_b,
                        relationship_type='same_topic',
                        strength=round(jaccard, 3),
                        reason=f"Subject overlap: {', '.join(list(overlap)[:3])}",
                    ))

        # 4. Explicit cross-reference in text
        for ref_doc in doc_a.get('referenced_docs', []):
            ref_lower = ref_doc.lower()
            if doc_b.get('file_name', '').lower() in ref_lower or any(
                r.lower() in ref_lower for r in doc_b.get('ref_numbers', [])
            ):
                rels.append(DocumentRelationship(
                    doc_a=id_a,
                    doc_b=id_b,
                    relationship_type='references',
                    strength=0.90,
                    reason=f"Explicit reference found: {ref_doc[:50]}",
                ))

        return rels

    @staticmethod
    def _names_match(name_a: str, name_b: str) -> bool:
        """Check if two party names refer to the same entity."""
        if not name_a or not name_b:
            return False
        # Simple: check if one contains the other
        a = name_a.lower().strip()
        b = name_b.lower().strip()
        if a == b:
            return True
        # Partial match (one name is substring of the other)
        if len(a) > 3 and len(b) > 3:
            return a in b or b in a
        return False


# ── Project Analyzer ─────────────────────────────────────────

class ProjectAnalyzer:
    """Builds project-level understanding from document collection."""

    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.claim_extractor = ClaimExtractor()
        self.relationship_extractor = RelationshipExtractor()

    def analyze_project(
        self,
        notices: List[Dict[str, Any]],
        project_name: Optional[str] = None,
    ) -> ProjectProfile:
        """
        Analyze all documents for a project and build a project profile.

        Args:
            notices: List of notice metadata dicts
            project_name: Optional project name override

        Returns:
            ProjectProfile with aggregated insights
        """
        if not notices:
            return ProjectProfile(project_name=project_name or "Unknown")

        # Detect project name if not provided
        if not project_name:
            project_name = self._detect_project_name(notices)

        # Build party map
        parties = self._build_party_map(notices)

        # Build timeline summary
        timeline = self._build_timeline(notices)

        # Detect key issues
        key_issues = self._detect_key_issues(notices)

        # Generate insights
        insights = self._generate_insights(notices, parties, timeline)

        # Date range
        dates = [n.get('date') for n in notices if n.get('date')]
        date_range = None
        if dates:
            dates.sort()
            date_range = f"{dates[0]} to {dates[-1]}"

        return ProjectProfile(
            project_name=project_name,
            parties=parties,
            key_issues=key_issues,
            timeline_summary=timeline,
            insights=insights,
            doc_count=len(notices),
            date_range=date_range,
        )

    def _detect_project_name(self, notices: List[Dict[str, Any]]) -> str:
        """Detect project name from notices."""
        name_counts: Dict[str, int] = defaultdict(int)
        for n in notices:
            pname = n.get('project_name')
            if pname:
                name_counts[pname] += 1

        if name_counts:
            return max(name_counts, key=name_counts.get)
        return "Unknown Project"

    def _build_party_map(self, notices: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Build a map of all parties and their roles."""
        parties: Dict[str, Dict[str, Any]] = {}

        for n in notices:
            sender = n.get('sender', '')
            recipient = n.get('recipient', '')

            if sender:
                key = sender.strip()[:50]
                if key not in parties:
                    parties[key] = {'role': 'unknown', 'sent': 0, 'received': 0, 'docs': []}
                parties[key]['sent'] += 1
                parties[key]['docs'].append(n.get('doc_id', ''))

            if recipient:
                key = recipient.strip()[:50]
                if key not in parties:
                    parties[key] = {'role': 'unknown', 'sent': 0, 'received': 0, 'docs': []}
                parties[key]['received'] += 1

        # Infer roles based on communication patterns
        for party, info in parties.items():
            total = info['sent'] + info['received']
            if total == 0:
                continue
            send_ratio = info['sent'] / total
            if send_ratio > 0.7:
                info['role'] = 'initiator'
            elif send_ratio < 0.3:
                info['role'] = 'responder'
            else:
                info['role'] = 'active_participant'

        return parties

    def _build_timeline(self, notices: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Build a chronological timeline of key events."""
        events = []

        for n in notices:
            date = n.get('date')
            if not date:
                continue

            event = {
                'date': date,
                'type': n.get('doc_type', 'document'),
                'summary': '',
                'doc_id': n.get('doc_id', ''),
            }

            # Build summary
            sender = n.get('sender', 'Unknown')[:30]
            recipient = n.get('recipient', 'Unknown')[:30]
            subject = n.get('subject', '')[:60]
            actions = n.get('actions', [])

            event['summary'] = f"{sender} -> {recipient}: {subject}"
            if actions:
                event['actions'] = ', '.join(actions[:3])

            events.append(event)

        events.sort(key=lambda e: e['date'])
        return events

    def _detect_key_issues(self, notices: List[Dict[str, Any]]) -> List[str]:
        """Detect key issues mentioned across documents."""
        issue_counts: Dict[str, int] = defaultdict(int)

        issue_keywords = {
            'delay': ['delay', 'delayed', 'behind schedule', 'slippage', 'extension of time'],
            'payment_dispute': ['payment', 'unpaid', 'outstanding', 'overdue', 'invoice'],
            'quality_concern': ['defect', 'non-conformance', 'NCR', 'quality', 'rework'],
            'safety_issue': ['safety', 'accident', 'incident', 'hazard', 'unsafe'],
            'scope_change': ['variation', 'change order', 'scope change', 'additional work'],
            'communication_gap': ['no response', 'awaiting', 'reminder', 'follow up'],
            'contractual_dispute': ['claim', 'dispute', 'breach', 'without prejudice', 'liability'],
        }

        for n in notices:
            subject = (n.get('subject') or '').lower()
            actions = [a.lower() for a in n.get('actions', [])]
            text = subject + ' ' + ' '.join(actions)

            for issue, keywords in issue_keywords.items():
                if any(kw in text for kw in keywords):
                    issue_counts[issue] += 1

        # Return issues sorted by frequency
        return [issue for issue, _ in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)]

    def _generate_insights(
        self,
        notices: List[Dict[str, Any]],
        parties: Dict[str, Dict[str, Any]],
        timeline: List[Dict[str, str]],
    ) -> List[ProjectInsight]:
        """Generate project-level insights from aggregated data."""
        insights = []

        # 1. Communication patterns
        if parties:
            top_sender = max(parties.items(), key=lambda x: x[1]['sent'])
            if top_sender[1]['sent'] > 3:
                insights.append(ProjectInsight(
                    insight_type='communication_pattern',
                    description=f"Most active sender: {top_sender[0]} ({top_sender[1]['sent']} documents sent)",
                    severity='low',
                ))

        # 2. Delay pattern detection
        delay_notices = [n for n in notices if 'delay' in (n.get('actions') or [])]
        if len(delay_notices) >= 2:
            dates = [n.get('date') for n in delay_notices if n.get('date')]
            insights.append(ProjectInsight(
                insight_type='delay_pattern',
                description=f"Found {len(delay_notices)} delay-related documents",
                supporting_docs=[n.get('doc_id', '') for n in delay_notices],
                severity='high' if len(delay_notices) >= 5 else 'medium',
                date_range=f"{min(dates)} to {max(dates)}" if dates else None,
            ))

        # 3. Unanswered communication detection
        reply_pairs = self._detect_unanswered(notices)
        if reply_pairs:
            insights.append(ProjectInsight(
                insight_type='communication_gap',
                description=f"Found {len(reply_pairs)} potentially unanswered communications",
                supporting_docs=[p[0] for p in reply_pairs],
                severity='medium',
            ))

        # 4. Document volume trends
        if timeline:
            monthly_counts = defaultdict(int)
            for event in timeline:
                month = event['date'][:7]  # YYYY-MM
                monthly_counts[month] += 1

            if monthly_counts:
                peak_month = max(monthly_counts, key=monthly_counts.get)
                insights.append(ProjectInsight(
                    insight_type='volume_trend',
                    description=f"Peak correspondence month: {peak_month} ({monthly_counts[peak_month]} documents)",
                    severity='low',
                ))

        return insights

    def _detect_unanswered(self, notices: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        """Detect documents that appear to be unanswered."""
        unanswered = []

        # Sort by date
        dated = [n for n in notices if n.get('date')]
        dated.sort(key=lambda x: x['date'])

        for n in dated:
            sender = (n.get('sender') or '').lower()
            recipient = (n.get('recipient') or '').lower()
            if not sender or not recipient:
                continue

            # Check if there's a reply (recipient becomes sender later)
            has_reply = False
            for later_n in dated:
                if later_n.get('date', '') <= n.get('date', ''):
                    continue
                later_sender = (later_n.get('sender') or '').lower()
                later_recipient = (later_n.get('recipient') or '').lower()
                if recipient in later_sender and sender in later_recipient:
                    has_reply = True
                    break

            if not has_reply:
                unanswered.append((n.get('doc_id', ''), n.get('file_name', '')))

        return unanswered


# ── Main Document Agent ──────────────────────────────────────

class DocumentAgent:
    """
    Main agent that orchestrates document understanding.
    Combines entity extraction, claim analysis, relationship mapping,
    and project-level insights.
    """

    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.claim_extractor = ClaimExtractor()
        self.relationship_extractor = RelationshipExtractor()
        self.project_analyzer = ProjectAnalyzer()
        self._profiles: Dict[str, ProjectProfile] = {}

    def analyze_document(
        self,
        doc_id: str,
        text: str,
        notice_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Deep analysis of a single document.

        Args:
            doc_id: Document identifier
            text: Full document text
            notice_metadata: Optional pre-extracted notice metadata

        Returns:
            Analysis dict with entities, claims, and key facts
        """
        logger.info(f"[DocumentAgent] Analyzing document: {doc_id}")

        entities = self.entity_extractor.extract_entities(text, doc_id)
        claims = self.claim_extractor.extract_claims(
            text, doc_id,
            date=notice_metadata.get('date') if notice_metadata else None,
        )

        # Group entities by type
        entity_groups = defaultdict(list)
        for e in entities:
            entity_groups[e.entity_type].append(asdict(e))

        result = {
            'doc_id': doc_id,
            'entities': dict(entity_groups),
            'entity_count': len(entities),
            'claims': [asdict(c) for c in claims],
            'claim_count': len(claims),
            'analysis_timestamp': datetime.now().isoformat(),
        }

        if notice_metadata:
            result['notice'] = notice_metadata

        return result

    def analyze_project(
        self,
        project_name: Optional[str] = None,
    ) -> ProjectProfile:
        """
        Build project-level understanding from all notices.

        Args:
            project_name: Optional project name filter

        Returns:
            ProjectProfile with insights
        """
        from .notice_extractor import NOTICES_DIR
        import json

        notices = []
        for notice_path in NOTICES_DIR.glob("*.json"):
            try:
                with open(notice_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Filter by project if specified
                if project_name:
                    doc_project = (data.get('project_name') or '').lower()
                    if project_name.lower() not in doc_project:
                        continue

                notices.append(data)
            except Exception as e:
                logger.warning(f"[DocumentAgent] Error loading notice {notice_path.name}: {e}")

        profile = self.project_analyzer.analyze_project(notices, project_name)

        # Cache the profile
        cache_key = project_name or "all"
        self._profiles[cache_key] = profile

        # Save to disk
        self._save_profile(profile)

        logger.info(f"[DocumentAgent] Project analysis complete: {profile.doc_count} docs, "
                    f"{len(profile.insights)} insights")
        return profile

    def get_relationships(
        self,
        project_name: Optional[str] = None,
    ) -> List[DocumentRelationship]:
        """
        Extract relationships between all documents.

        Args:
            project_name: Optional project filter

        Returns:
            List of document relationships
        """
        from .notice_extractor import NOTICES_DIR
        import json

        notices = []
        for notice_path in NOTICES_DIR.glob("*.json"):
            try:
                with open(notice_path, 'r', encoding='utf-8') as f:
                    notices.append(json.load(f))
            except Exception:
                continue

        if project_name:
            notices = [n for n in notices
                       if project_name.lower() in (n.get('project_name') or '').lower()]

        return self.relationship_extractor.extract_relationships(notices)

    def answer_project_question(
        self,
        question: str,
        project_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Answer a project-level question using aggregated understanding.

        Args:
            question: Natural language question
            project_name: Optional project filter

        Returns:
            Answer dict with response and supporting evidence
        """
        # Get or build project profile
        cache_key = project_name or "all"
        if cache_key not in self._profiles:
            self.analyze_project(project_name)

        profile = self._profiles.get(cache_key)
        if not profile:
            return {"answer": "No project data available.", "sources": []}

        q = question.lower()

        # Pattern-based answers for common questions
        if any(kw in q for kw in ['how many', 'count', 'total documents']):
            return {
                "answer": f"Project '{profile.project_name}' contains {profile.doc_count} documents"
                          f" spanning {profile.date_range or 'unknown dates'}.",
                "sources": [],
            }

        if any(kw in q for kw in ['parties', 'who is involved', 'participants']):
            party_lines = []
            for name, info in sorted(profile.parties.items(), key=lambda x: x[1]['sent'] + x[1]['received'], reverse=True):
                party_lines.append(f"- **{name}**: {info['sent']} sent, {info['received']} received ({info['role']})")
            return {
                "answer": f"Parties involved in '{profile.project_name}':\n\n" + "\n".join(party_lines[:15]),
                "sources": [],
            }

        if any(kw in q for kw in ['issues', 'problems', 'concerns']):
            if profile.key_issues:
                issue_lines = [f"- {issue.replace('_', ' ').title()}" for issue in profile.key_issues]
                return {
                    "answer": f"Key issues identified in '{profile.project_name}':\n\n" + "\n".join(issue_lines),
                    "sources": [],
                }

        if any(kw in q for kw in ['insight', 'analysis', 'overview', 'summary']):
            if profile.insights:
                insight_lines = []
                for ins in profile.insights:
                    severity_icon = {"critical": "!!", "high": "!", "medium": "-", "low": "."}.get(ins.severity, "-")
                    insight_lines.append(f"[{severity_icon}] {ins.description}")
                return {
                    "answer": f"Project Insights for '{profile.project_name}':\n\n" + "\n".join(insight_lines),
                    "sources": [d for ins in profile.insights for d in ins.supporting_docs],
                }

        # Default: use LLM for complex questions
        return self._llm_project_answer(question, profile)

    def _llm_project_answer(
        self,
        question: str,
        profile: ProjectProfile,
    ) -> Dict[str, Any]:
        """Use LLM to answer complex project questions."""
        try:
            from . import llm_client
            from .prompt_security import safe_render_prompt, build_system_prompt

            # Build context from profile
            party_context = "\n".join(
                f"- {name}: sent={info['sent']}, received={info['received']}, role={info['role']}"
                for name, info in list(profile.parties.items())[:15]
            )

            timeline_context = "\n".join(
                f"- {e['date']}: [{e['type']}] {e['summary']}"
                for e in profile.timeline_summary[:20]
            )

            insight_context = "\n".join(
                f"- [{i.severity}] {i.insight_type}: {i.description}"
                for i in profile.insights
            )

            issues_context = ", ".join(profile.key_issues) if profile.key_issues else "None identified"

            prompt = safe_render_prompt(
                "Answer the question about this construction project based ONLY on the data below.\n\n"
                "PROJECT: {project_name}\n"
                "DOCUMENTS: {doc_count} documents, date range: {date_range}\n\n"
                "PARTIES:\n{parties}\n\n"
                "TIMELINE (recent):\n{timeline}\n\n"
                "KEY ISSUES: {issues}\n\n"
                "INSIGHTS:\n{insights}\n\n"
                "{user_query}\n\n"
                "RULES:\n"
                "1. Only use information from the data above\n"
                "2. Be specific with dates, names, and references\n"
                "3. If the answer is not in the data, say so clearly",
                project_name=profile.project_name,
                doc_count=str(profile.doc_count),
                date_range=profile.date_range or "Unknown",
                parties=party_context,
                timeline=timeline_context,
                issues=issues_context,
                insights=insight_context,
                user_query=question,
            )

            system = build_system_prompt(
                "You are an expert construction project analyst."
            )

            resp = llm_client.generate_text(prompt, system=system, max_tokens=1024)

            return {
                "answer": resp.text,
                "sources": [],
                "method": "llm_project_analysis",
            }

        except Exception as e:
            logger.error(f"[DocumentAgent] LLM project answer failed: {e}")
            return {
                "answer": f"Project '{profile.project_name}': {profile.doc_count} documents, "
                          f"key issues: {', '.join(profile.key_issues[:5])}",
                "sources": [],
            }

    def _save_profile(self, profile: ProjectProfile):
        """Save project profile to disk."""
        safe_name = re.sub(r'[^\w\-]', '_', profile.project_name)[:50]
        path = AGENT_DIR / f"profile_{safe_name}.json"
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(asdict(profile), f, indent=2, ensure_ascii=False)
            logger.info(f"[DocumentAgent] Saved profile: {path.name}")
        except Exception as e:
            logger.warning(f"[DocumentAgent] Failed to save profile: {e}")


# ── Singleton ────────────────────────────────────────────────

_agent: Optional[DocumentAgent] = None


def get_document_agent() -> DocumentAgent:
    """Get or create DocumentAgent singleton."""
    global _agent
    if _agent is None:
        _agent = DocumentAgent()
    return _agent
