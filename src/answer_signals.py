"""Shared detector for answers that deny the document corpus.

There used to be two copies of this — one in the router, one in the response
builder — with different pattern sets, so each caught denials the other missed.
Live measurement against production made the cost concrete: a question about
"Phase 1b" came back "the provided document excerpts do not contain information
explicitly labeled Phase 1b" while five documents discussed *Phase 1b — Roseburn
to Granton* by name, and **neither** copy recognised it as a denial. One list,
one place, so a phrasing learned in one context is known in both.

`denies_corpus` deliberately returns False for empty text: the two callers
disagree on what an empty answer means (the router treats it as a denial, the
response builder does not), so that judgement stays with them.
"""

import re

# Ordered loosely by how often they turn up. Each is anchored on the CORPUS
# being the thing that lacks something — "the documents do not contain X" — not
# on a bare negation. "The contract does not contain a termination clause" is a
# substantive answer, not a refusal, and must not match.
_DENIAL_PATTERNS = [
    r"\bno\s+(?:relevant\s+)?(?:documents?|files?|sources?)\b",
    r"\bno\s+documents?\s+(?:are\s+)?related\b",
    r"\bnot\s+found\b",
    r"\bwas\s+not\s+found\b",
    r"\bwere\s+not\s+found\b",
    r"\bnot\s+available\b",
    r"\bnot\s+mentioned\b",
    r"\bdoes\s+not\s+appear\b",
    r"\bcould\s+not\s+find\b",
    r"\bcouldn'?t\s+find\b",
    r"\bprovided\s+(?:context|information)\s+does\s+not\s+contain\b",
    r"\bno\s+information\s+(?:related\s+to|about|regarding)\b",
    r"\bcannot\s+provide\s+information\b",
    r"\bcan'?t\s+provide\s+information\b",
    # ── added after measuring real production refusals ──
    # "The provided document excerpts do not contain information explicitly
    # labeled 'Phase 1b'" / "do not contain any information regarding X".
    # Subject-anchored so a substantive "the contract does not contain a
    # termination clause" is not swept up.
    r"\b(?:documents?|excerpts?|records?|files?|context|data)\s+"
    r"(?:provided\s+)?do(?:es)?\s+not\s+contain\b",
    r"\bdo(?:es)?\s+not\s+contain\s+(?:any\s+)?(?:information|details|data)\b",
    r"\bdo(?:es)?\s+not\s+contain\s+(?:any\s+)?(?:explicit\s+)?"
    r"(?:mention|reference)\b",
    r"\bnot\s+explicitly\s+(?:labell?ed|mentioned|stated|named|identified)\b",
    r"\bno\s+(?:explicit\s+)?(?:mention|reference)\s+(?:of|to)\b",
    # A deflection rather than a denial, but it means the same thing to the
    # reader: the system did not answer. The Phase 1b refusal opened with it.
    r"\bplease\s+provide\s+a\s+(?:more\s+)?specific\s+question\b",
]

_DENIAL_RE = [re.compile(p) for p in _DENIAL_PATTERNS]


def denies_corpus(answer: str) -> bool:
    """True when the text reads as "the documents don't have this".

    Empty text returns False — callers decide what silence means.
    """
    text = (answer or "").strip().lower()
    if not text:
        return False
    return any(rx.search(text) for rx in _DENIAL_RE)
