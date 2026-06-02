"""
Jargon Manager - Central abbreviation and domain terminology system.

Custom (user-added) terms persist to ``storage/jargon_custom.json`` so they
survive process restarts. Built-in terms are immutable and cannot be removed
through the admin API.
Loads jargon dictionaries from Excel and provides:
- Abbreviation expansion (SOW -> Scope of Work)
- Reverse lookup (Scope of Work -> SOW)
- Query expansion for better search/SQL results
- Column name normalization with domain awareness
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

import pandas as pd

from .logger import logger
from .config import BASE_DIR


# Default jargon dictionary path
JARGON_DIR = BASE_DIR / "data" / "jargon"
JARGON_DIR.mkdir(parents=True, exist_ok=True)
JARGON_CACHE_FILE = JARGON_DIR / "jargon_cache.json"


class JargonManager:
    """
    Central jargon and abbreviation management.
    Loads from Excel files and provides lookup/expansion services.
    """

    # Built-in construction/contract domain abbreviations
    BUILTIN_JARGON = {
        # Universal business abbreviations
        "SOW": "Scope of Work",
        "SLA": "Service Level Agreement",
        "NDA": "Non-Disclosure Agreement",
        "KPI": "Key Performance Indicator",
        "MTD": "Month to Date",
        "QTD": "Quarter to Date",
        "YTD": "Year to Date",
        "PO": "Purchase Order",
        "PR": "Purchase Requisition",
        "T&C": "Terms and Conditions",
        # Common construction/contract abbreviations
        "BOQ": "Bill of Quantities",
        "BOM": "Bill of Materials",
        "RFI": "Request for Information",
        "RFP": "Request for Proposal",
        "RFQ": "Request for Quotation",
        "EOT": "Extension of Time",
        "LD": "Liquidated Damages",
        "LAD": "Liquidated and Ascertained Damages",
        "VO": "Variation Order",
        "CO": "Change Order",
        "WBS": "Work Breakdown Structure",
        "OBS": "Organization Breakdown Structure",
        "ITP": "Inspection and Test Plan",
        "QA": "Quality Assurance",
        "QC": "Quality Control",
        "HSE": "Health Safety and Environment",
        "EHS": "Environment Health and Safety",
        "QHSE": "Quality Health Safety and Environment",
        "MEP": "Mechanical Electrical and Plumbing",
        "HVAC": "Heating Ventilation and Air Conditioning",
        "P&ID": "Piping and Instrumentation Diagram",
        "GA": "General Arrangement",
        "DWG": "Drawing",
        "SPEC": "Specification",
        "TBD": "To Be Determined",
        "TBA": "To Be Announced",
        "TBC": "To Be Confirmed",
        "N/A": "Not Applicable",
        "WIP": "Work in Progress",
        "PMO": "Project Management Office",
        "PM": "Project Manager",
        "CM": "Construction Manager",
        "RE": "Resident Engineer",
        "QS": "Quantity Surveyor",
        "IFC": "Issued for Construction",
        "IFR": "Issued for Review",
        "IFA": "Issued for Approval",
        "AFC": "Approved for Construction",
        "FIDIC": "Federation Internationale Des Ingenieurs-Conseils",
        "JV": "Joint Venture",
        "LOI": "Letter of Intent",
        "LOA": "Letter of Acceptance",
        "MOM": "Minutes of Meeting",
        "NCR": "Non-Conformance Report",
        "NCN": "Non-Conformance Notice",
        "RCA": "Root Cause Analysis",
        "CAPA": "Corrective and Preventive Action",
        "EPC": "Engineering Procurement and Construction",
        "EPCC": "Engineering Procurement Construction and Commissioning",
        "FEED": "Front End Engineering Design",
        "BIM": "Building Information Modeling",
        "CAD": "Computer Aided Design",
        "CPI": "Cost Performance Index",
        "SPI": "Schedule Performance Index",
        "EV": "Earned Value",
        "PV": "Planned Value",
        "AC": "Actual Cost",
        "EAC": "Estimate at Completion",
        "ETC": "Estimate to Complete",
        "BAC": "Budget at Completion",
        "VAC": "Variance at Completion",
        "FAT": "Factory Acceptance Test",
        "SAT": "Site Acceptance Test",
        "O&M": "Operation and Maintenance",
        # Project-specific (TABH / Dubai construction)
        "TABH": "The Address Boulevard Hotel",
        "DPR": "Daily Progress Report",
        "NOC": "No Objection Certificate",
        "NOD": "Notice of Delay",
        "NOP": "Notice of Progress",
        "CCTV": "Closed Circuit Television",
        "UPS": "Uninterruptible Power Supply",
        "LTR": "Letter",
        "DEWA": "Dubai Electricity and Water Authority",
        "DM": "Dubai Municipality",
        "JAFZA": "Jebel Ali Free Zone Authority",
        "AED": "United Arab Emirates Dirham",
        "UAE": "United Arab Emirates",
        "GCC": "Gulf Cooperation Council",
        "LEED": "Leadership in Energy and Environmental Design",
        "MDC": "Main Distribution Center",
        "CMAR": "Construction Management at Risk",
        "TIR": "Technical Inspection Report",
        "DPS": "Dubai Properties",
        "MVP": "Material Verification Procedure",
        "BMM": "Building Maintenance and Management",
        "TCI": "TCI Engineering",
        "SIRA": "Systematic Integrated Risk Assessment",
        "FASTA": "Fire Alarm System Testing and Approval",
    }

    # Domain concept groups: maps a concept to related search terms
    DOMAIN_CONCEPT_GROUPS = {
        "delay": [
            "delay", "NOD", "notice of delay", "postponement",
            "extension of time", "EOT", "delayed", "late completion",
            "schedule delay", "time extension",
        ],
        "claim": [
            "claim", "notice of claim", "compensation",
            "loss and expense", "damages", "liquidated damages",
            "LD", "LAD", "entitlement",
        ],
        "approval": [
            "approval", "approve", "consent", "no objection",
            "NOC", "acceptance", "LOA", "approved",
        ],
        "variation": [
            "variation", "change order", "VO", "modification",
            "amendment", "revised scope", "scope change",
        ],
        "payment": [
            "payment", "IPC", "interim payment", "invoice",
            "valuation", "certification", "progress payment",
        ],
        "termination": [
            "termination", "terminate", "cancellation",
            "suspension", "suspend", "breach of contract",
        ],
        "progress": [
            "progress", "DPR", "daily progress", "milestone",
            "schedule", "programme", "completion",
        ],
        "quality": [
            "quality", "NCR", "NCN", "non-conformance",
            "defect", "deficiency", "inspection", "QA", "QC",
        ],
        "fire_alarm": [
            "fire alarm", "FASTA", "Fire Alarm System Testing and Approval",
            "fire alarm system", "fire alarm testing", "fire alarm approval",
            "SIRA", "DPS", "NOC", "life safety",
        ],
    }

    def __init__(self):
        """Initialize jargon manager."""
        # abbreviation -> full meaning
        self._abbr_to_meaning: Dict[str, str] = {}
        # lowercase meaning -> abbreviation (for reverse lookup)
        self._meaning_to_abbr: Dict[str, str] = {}
        # synonym groups: maps any form to canonical form
        self._synonyms: Dict[str, str] = {}
        # User-added custom terms (subset of _abbr_to_meaning, not built-in)
        self._custom_terms: Dict[str, Dict[str, str]] = {}
        # Path for custom term persistence
        self._custom_store_path = JARGON_DIR / "jargon_custom.json"

        # Load built-in jargon
        self._load_builtin()

        logger.info(f"[JargonManager] Initialized with {len(self._abbr_to_meaning)} terms")

    def _load_builtin(self):
        """Load built-in domain abbreviations."""
        for abbr, meaning in self.BUILTIN_JARGON.items():
            self._add_term(abbr, meaning)

    def _add_term(self, abbreviation: str, meaning: str):
        """Add a jargon term to the dictionaries."""
        abbr_upper = abbreviation.upper().strip()
        meaning_clean = meaning.strip()

        self._abbr_to_meaning[abbr_upper] = meaning_clean
        self._meaning_to_abbr[meaning_clean.lower()] = abbr_upper

        # Build synonym mappings
        self._synonyms[abbr_upper.lower()] = abbr_upper
        self._synonyms[meaning_clean.lower()] = abbr_upper

        # Also map individual significant words from meaning
        words = meaning_clean.lower().split()
        if len(words) >= 2:
            # Map the key noun phrase (last 2-3 words typically)
            key_phrase = " ".join(words[-2:])
            if key_phrase not in self._synonyms:
                self._synonyms[key_phrase] = abbr_upper

    def load_from_excel(self, file_path: str) -> int:
        """
        Load jargon dictionary from Excel file.
        Expects 2 columns: Abbreviation, Meaning.

        Args:
            file_path: Path to Excel file

        Returns:
            Number of terms loaded
        """
        try:
            df = pd.read_excel(file_path, header=None)

            if df.empty or len(df.columns) < 2:
                logger.warning(f"[JargonManager] Invalid jargon file format: {file_path}")
                return 0

            # Detect header row
            header_row = 0
            for i in range(min(5, len(df))):
                row = df.iloc[i]
                val0 = str(row.iloc[0]).lower() if pd.notna(row.iloc[0]) else ""
                val1 = str(row.iloc[1]).lower() if pd.notna(row.iloc[1]) else ""
                if any(kw in val0 for kw in ['abbreviation', 'abbr', 'term', 'acronym']):
                    header_row = i
                    break
                if any(kw in val1 for kw in ['meaning', 'definition', 'full', 'description']):
                    header_row = i
                    break

            count = 0
            for i in range(header_row + 1, len(df)):
                row = df.iloc[i]
                abbr = row.iloc[0]
                meaning = row.iloc[1]

                if pd.notna(abbr) and pd.notna(meaning):
                    abbr_str = str(abbr).strip()
                    meaning_str = str(meaning).strip()
                    if abbr_str and meaning_str and len(abbr_str) >= 1:
                        self._add_term(abbr_str, meaning_str)
                        count += 1

            logger.info(f"[JargonManager] Loaded {count} terms from: {Path(file_path).name}")
            return count

        except Exception as e:
            logger.error(f"[JargonManager] Error loading jargon file: {e}")
            return 0

    def auto_discover_and_load(self) -> int:
        """
        Auto-discover and load jargon files from known locations.

        Returns:
            Total number of new terms loaded
        """
        total = 0
        search_paths = [
            BASE_DIR / "data" / "jargon",
            BASE_DIR,
        ]

        for search_path in search_paths:
            if not search_path.exists():
                continue
            for xlsx_path in search_path.rglob("*[Jj]argon*.[Xx][Ll][Ss][Xx]"):
                if xlsx_path.name.startswith("~$"):
                    continue
                total += self.load_from_excel(str(xlsx_path))

            for xlsx_path in search_path.rglob("*[Aa]bbreviation*.[Xx][Ll][Ss][Xx]"):
                if xlsx_path.name.startswith("~$"):
                    continue
                total += self.load_from_excel(str(xlsx_path))

        logger.info(f"[JargonManager] Auto-loaded {total} terms total. Dictionary size: {len(self._abbr_to_meaning)}")
        return total

    def expand(self, abbreviation: str) -> Optional[str]:
        """
        Expand an abbreviation to its full meaning.

        Args:
            abbreviation: The abbreviation to expand

        Returns:
            Full meaning or None if not found
        """
        return self._abbr_to_meaning.get(abbreviation.upper().strip())

    def abbreviate(self, meaning: str) -> Optional[str]:
        """
        Find abbreviation for a full meaning.

        Args:
            meaning: The full meaning text

        Returns:
            Abbreviation or None if not found
        """
        return self._meaning_to_abbr.get(meaning.lower().strip())

    def get_canonical(self, term: str) -> Optional[str]:
        """
        Get canonical abbreviation for any form of a term.

        Args:
            term: Any form (abbreviation or meaning)

        Returns:
            Canonical abbreviation or None
        """
        return self._synonyms.get(term.lower().strip())

    def compress_query(self, query: str) -> str:
        """
        Compress full forms to canonical abbreviations.
        "Extension of Time approved" -> "EOT approved".

        Uses longest-match-first to avoid partial overlaps. If a full form
        appears already paired with its abbreviation (case-insensitive), the
        compression is skipped to keep the original phrasing.
        """
        if not query:
            return query

        # Lazy reverse-index of full-form -> abbreviation, longest first.
        if not hasattr(self, "_compress_index"):
            self._compress_index = sorted(
                self._meaning_to_abbr.items(),
                key=lambda kv: len(kv[0]),
                reverse=True,
            )

        out = query
        out_lower = out.lower()
        for meaning_lower, abbr in self._compress_index:
            if len(meaning_lower) < 4:
                continue
            if meaning_lower not in out_lower:
                continue
            if abbr.lower() in out_lower:
                continue
            pattern = re.compile(re.escape(meaning_lower), re.IGNORECASE)
            out = pattern.sub(abbr, out)
            out_lower = out.lower()
        return out

    def normalize_query_bidirectional(self, query: str) -> str:
        """expand_query + compress_query for retrieval-friendly normalization."""
        return self.compress_query(self.expand_query(query))

    def replace_query_terms_with_meanings(self, query: str) -> str:
        """
        Replace exact jargon abbreviation matches with their full meanings.

        This is intentionally different from ``expand_query``. RAG retrieval
        should embed the semantic meaning of the user's term, not a parenthetical
        mix that can later be compressed back to the abbreviation.

        Example:
            "documents related to EOT" -> "documents related to Extension of Time"
        """
        if not query:
            return query

        replaced = query
        for abbr, meaning in sorted(
            self._abbr_to_meaning.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            if not abbr or not meaning:
                continue
            paired_pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(abbr)}(?![A-Za-z0-9])"
                rf"\s*\(\s*{re.escape(meaning)}\s*\)",
                re.IGNORECASE,
            )
            replaced = paired_pattern.sub(meaning, replaced)
            pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(abbr)}(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            replaced = pattern.sub(meaning, replaced)

        return replaced

    def lookup_concept_group(self, term: str) -> Optional[List[str]]:
        """
        Return synonyms for a term if it belongs to a DOMAIN_CONCEPT_GROUP.
        Match is case-insensitive substring against group keys and members.
        """
        if not term:
            return None
        t = term.lower().strip()
        for concept, members in self.DOMAIN_CONCEPT_GROUPS.items():
            if t == concept or t in concept:
                return list(members)
            for m in members:
                if t == m.lower():
                    return list(members)
        return None

    def expand_query(self, query: str) -> str:
        """
        Expand abbreviations in a query text.
        Adds both the abbreviation and its meaning for better matching.

        Example:
            "List deliverables in the SOW" ->
            "List deliverables in the SOW (Scope of Work)"

        Args:
            query: User query text

        Returns:
            Expanded query with abbreviation meanings
        """
        expanded = query
        words = re.findall(r'\b[A-Z][A-Z0-9&/]{1,10}\b', query)

        for word in words:
            meaning = self.expand(word)
            if meaning:
                # Add meaning in parentheses if not already present
                if meaning.lower() not in query.lower():
                    expanded = expanded.replace(word, f"{word} ({meaning})")

        return expanded

    def normalize_column_name(self, column: str) -> Tuple[str, Optional[str]]:
        """
        Normalize a column name and identify if it's a known abbreviation.

        Args:
            column: Raw column name from table

        Returns:
            Tuple of (normalized_name, expanded_meaning or None)
        """
        clean = column.strip()

        # Check if column name is a known abbreviation
        meaning = self.expand(clean)
        if meaning:
            return clean, meaning

        # Check if column name contains known abbreviations
        words = clean.split("_")
        expanded_parts = []
        has_expansion = False
        for w in words:
            m = self.expand(w.upper())
            if m:
                expanded_parts.append(m)
                has_expansion = True
            else:
                expanded_parts.append(w)

        if has_expansion:
            return clean, " - ".join(expanded_parts)

        return clean, None

    def expand_domain_concepts(self, query: str) -> List[str]:
        """
        Expand domain concepts in a query to related search terms.
        Unlike expand_query (which handles abbreviations), this maps
        semantic concepts to broader term sets.

        Example:
            "delay events" -> ["delay", "NOD", "notice of delay", "postponement", ...]

        Args:
            query: User query text

        Returns:
            List of related search terms (deduplicated)
        """
        query_lower = query.lower()
        terms: Set[str] = set()

        for concept, related in self.DOMAIN_CONCEPT_GROUPS.items():
            if concept in query_lower:
                terms.update(related)

        return list(terms)

    def get_concept_search_terms(self, query: str) -> List[str]:
        """
        Combine abbreviation expansion and domain concept expansion
        to produce a comprehensive list of search terms.

        Args:
            query: User query text

        Returns:
            Deduplicated list of search terms
        """
        terms: Set[str] = set()

        # 1. Domain concept expansion
        terms.update(self.expand_domain_concepts(query))

        # 2. Find any abbreviations in the query and add their meanings
        for found in self.find_related_terms(query):
            terms.add(found["abbreviation"])
            terms.add(found["meaning"].lower())

        # 3. If no concept groups matched, use key words from the query
        if not terms:
            stop_words = {"what", "are", "the", "in", "is", "a", "an", "of",
                          "how", "many", "show", "me", "list", "all", "from",
                          "to", "and", "or", "for", "with", "about", "do"}
            for word in query.lower().split():
                word = word.strip("?.,!")
                if word and len(word) > 2 and word not in stop_words:
                    terms.add(word)

        return list(terms)

    def build_column_context(self, columns: List[str]) -> str:
        """
        Build a context string explaining column abbreviations.
        Useful for providing context to LLM prompts.

        Args:
            columns: List of column names

        Returns:
            Context string with abbreviation explanations
        """
        explanations = []
        for col in columns:
            _, meaning = self.normalize_column_name(col)
            if meaning:
                explanations.append(f"  - {col} = {meaning}")

        if explanations:
            return "Column abbreviation reference:\n" + "\n".join(explanations)
        return ""

    def build_query_context(self) -> str:
        """
        Build a compact context string of all jargon for LLM prompts.

        Returns:
            Formatted jargon reference string
        """
        lines = []
        for abbr, meaning in sorted(self._abbr_to_meaning.items()):
            lines.append(f"  {abbr} = {meaning}")

        return "Domain Jargon Reference:\n" + "\n".join(lines)

    def find_related_terms(self, text: str) -> List[Dict]:
        """
        Find all jargon terms (abbreviations or full meanings) mentioned in text.

        Args:
            text: Text to scan

        Returns:
            List of dicts with abbreviation, meaning, and where found
        """
        found = []
        text_lower = text.lower()
        text_upper = text.upper()

        # Check for abbreviations
        for abbr, meaning in self._abbr_to_meaning.items():
            # Look for abbreviation as whole word
            pattern = r'\b' + re.escape(abbr) + r'\b'
            if re.search(pattern, text_upper):
                found.append({
                    "abbreviation": abbr,
                    "meaning": meaning,
                    "found_as": "abbreviation",
                })
            # Look for full meaning
            elif meaning.lower() in text_lower:
                found.append({
                    "abbreviation": abbr,
                    "meaning": meaning,
                    "found_as": "full_meaning",
                })

        return found

    def get_all_terms(self) -> Dict[str, str]:
        """Get all abbreviation -> meaning mappings."""
        return dict(self._abbr_to_meaning)

    @property
    def size(self) -> int:
        """Number of terms in dictionary."""
        return len(self._abbr_to_meaning)

    # ── Custom term management (persisted) ────────────────────────────

    def add_custom_term(
        self,
        abbreviation: str,
        full_form: str,
        concept_group: Optional[str] = None,
    ) -> Dict[str, str]:
        """Add a user-defined term and persist it. Built-ins cannot be overridden via API."""
        abbr_upper = abbreviation.strip().upper()
        if not abbr_upper or not full_form.strip():
            raise ValueError("abbreviation and full_form are required")
        if abbr_upper in self.BUILTIN_JARGON:
            raise ValueError(f"'{abbr_upper}' is a built-in term and cannot be overridden")

        record = {"abbreviation": abbr_upper, "full_form": full_form.strip()}
        if concept_group:
            record["concept_group"] = concept_group.strip().lower()

        self._add_term(abbr_upper, full_form.strip())
        self._custom_terms[abbr_upper] = record

        if concept_group:
            grp = self.DOMAIN_CONCEPT_GROUPS.setdefault(concept_group.strip().lower(), [])
            for token in (abbr_upper, full_form.strip()):
                if token and token not in grp:
                    grp.append(token)

        # Invalidate caches
        if hasattr(self, "_compress_index"):
            del self._compress_index

        self.save_to_disk()
        logger.info(f"[JargonManager] Added custom term: {abbr_upper} = {full_form}")
        return record

    def remove_custom_term(self, abbreviation: str) -> bool:
        """Remove a previously-added custom term. Built-ins are protected."""
        abbr_upper = abbreviation.strip().upper()
        if abbr_upper in self.BUILTIN_JARGON:
            raise ValueError(f"'{abbr_upper}' is a built-in term and cannot be removed")
        if abbr_upper not in self._custom_terms:
            return False

        meaning = self._abbr_to_meaning.pop(abbr_upper, None)
        self._custom_terms.pop(abbr_upper, None)
        if meaning:
            self._meaning_to_abbr.pop(meaning.lower(), None)
            self._synonyms.pop(meaning.lower(), None)
        self._synonyms.pop(abbr_upper.lower(), None)

        if hasattr(self, "_compress_index"):
            del self._compress_index

        self.save_to_disk()
        logger.info(f"[JargonManager] Removed custom term: {abbr_upper}")
        return True

    def list_custom_terms(self) -> List[Dict[str, str]]:
        """Return all user-added terms."""
        return list(self._custom_terms.values())

    def save_to_disk(self, path: Optional[Path] = None) -> None:
        """Persist current custom-term set to disk as JSON."""
        import json as _json
        target = Path(path) if path else self._custom_store_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                _json.dump(
                    {"terms": list(self._custom_terms.values())},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception as e:
            logger.error(f"[JargonManager] save_to_disk failed: {e}")

    def load_from_disk(self, path: Optional[Path] = None) -> int:
        """Load custom terms from JSON. Returns number of terms loaded."""
        import json as _json
        target = Path(path) if path else self._custom_store_path
        if not target.exists():
            return 0
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = _json.load(f)
            count = 0
            for record in data.get("terms", []):
                abbr = record.get("abbreviation", "").strip().upper()
                full = record.get("full_form", "").strip()
                concept = record.get("concept_group")
                if not abbr or not full:
                    continue
                if abbr in self.BUILTIN_JARGON:
                    continue
                self._add_term(abbr, full)
                self._custom_terms[abbr] = {
                    "abbreviation": abbr,
                    "full_form": full,
                    **({"concept_group": concept} if concept else {}),
                }
                if concept:
                    grp = self.DOMAIN_CONCEPT_GROUPS.setdefault(concept.lower(), [])
                    for token in (abbr, full):
                        if token and token not in grp:
                            grp.append(token)
                count += 1
            if hasattr(self, "_compress_index"):
                del self._compress_index
            logger.info(f"[JargonManager] Loaded {count} custom terms from disk")
            return count
        except Exception as e:
            logger.error(f"[JargonManager] load_from_disk failed: {e}")
            return 0


# Singleton
_jargon_manager: Optional[JargonManager] = None


def get_jargon_manager() -> JargonManager:
    """Get or create JargonManager singleton."""
    global _jargon_manager
    if _jargon_manager is None:
        _jargon_manager = JargonManager()
        _jargon_manager.auto_discover_and_load()
        _jargon_manager.load_from_disk()
    return _jargon_manager
