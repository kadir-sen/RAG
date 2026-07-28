"""Recovery for JSON files damaged by the old text-mode path normalizer.

Until this commit, ``src.config.normalize_stored_paths()`` ran at import time —
on every process start — and rewrote the RAW TEXT of every JSON file under
``storage/`` and ``data/``::

    raw = raw.replace("\\\\", "/")        # two backslashes -> one slash
    raw = raw.replace("\\", "/")          # every remaining backslash -> slash
    raw = re.sub(r'(?<!:)//', '/', raw)   # collapse the resulting doubles

It never parsed the JSON, so it destroyed the escapes the format is built on:
``\\"`` became ``/"`` — the string terminates early and the file stops parsing —
``\\n`` became ``/n``, ``\\t`` became ``/t``. The write was guarded by
``if raw != original``, so each file was corrupted the first time it was swept
after being written. That is what "history resets on every deploy" was.

The whole corruption is therefore "some backslashes became forward slashes", so
this module is exactly its inverse: it only ever turns an existing ``/`` back
into a ``\\``. A repaired text is accepted only when

  1. ``json.loads`` succeeds on it, AND
  2. it is the same length as the input, AND
  3. every position where the two differ has ``/`` in the input and ``\\`` in
     the output.

A repair satisfying those three cannot insert, drop, reorder or invent a single
character — which is what makes this a proof rather than a hope. Anything that
cannot be verified is left exactly as it was found, and the original is always
kept beside the repaired file.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set, Tuple

_log = logging.getLogger("app")

BACKUP_SUFFIX = ".corrupt.bak"
MARKER_NAME = ".escape_repair_v1.json"

# Characters that follow a backslash in a JSON escape. '"' and '\\' are handled
# by the string scanner itself. '/' is deliberately excluded: a surviving "//"
# is nearly always a real URL, and "\\/" decodes to "/" anyway.
_ESCAPE_TAIL = frozenset("ntrbf")
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")

# Content-escape repair (phase B) must not touch a real path or URL that happens
# to sit inside the prose. "/app/data/tables/Manpower.xlsx" would otherwise have
# its "/tables" turned into TAB + "ables". These spans are masked out.
_PATH_SPAN = re.compile(r"(?:[a-z][a-z0-9+.-]*://|/app/|/data/|/storage/|/Users/)[^\s\"]*")


def _masked_spans(text: str) -> List[Tuple[int, int]]:
    return [(m.start(), m.end()) for m in _PATH_SPAN.finditer(text)]


def _in_span(pos: int, spans: List[Tuple[int, int]]) -> bool:
    for start, end in spans:
        if start <= pos < end:
            return True
        if start > pos:
            break
    return False


def _scan(text: str, flips: Set[int], restore_content_escapes: bool) -> Tuple[str, List[int]]:
    """One repair pass. Returns (candidate_text, ambiguous_quote_offsets).

    A ``"`` reached while inside a string literal is a genuine terminator unless
    the character before it is ``/`` — the corruption always leaves exactly one
    slash where the escaping backslash used to be. When it *is* preceded by
    ``/`` the two readings are separated by what ``json.dumps(indent=2)`` can
    emit right after a terminator: ``:`` immediately, ``,`` then a newline, or a
    newline. Anything else means the quote is content and the ``/`` before it
    was a ``\\``. Positions that stay genuinely ambiguous are returned so the
    caller can flip them one at a time when the parse fails.
    """
    buf = list(text)
    ambiguous: List[int] = []
    spans = _masked_spans(text) if restore_content_escapes else []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = buf[i]
        if not in_string:
            if ch == '"':
                in_string = True
            i += 1
            continue
        if ch == "\\":                     # an escape we already restored
            i += 2
            continue
        if ch == '"':
            if (buf[i - 1] if i else "") != "/":
                in_string = False          # certain terminator
                i += 1
                continue
            after = text[i + 1:i + 3]
            terminator = (
                after[:1] == ":" or after[:2] == ",\n" or after[:1] == "\n" or i + 1 >= n
            )
            ambiguous.append(i)
            if i in flips:
                terminator = not terminator
            if terminator:
                in_string = False
            else:
                buf[i - 1] = "\\"          # restore the escaping backslash
            i += 1
            continue
        if restore_content_escapes and ch == "/" and not _in_span(i, spans):
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt in _ESCAPE_TAIL:
                buf[i] = "\\"
            elif nxt == "u" and _HEX4.match(text[i + 2:i + 6]):
                buf[i] = "\\"
            i += 1
            continue
        i += 1
    return "".join(buf), ambiguous


def is_slash_only_inverse(original: str, repaired: str) -> bool:
    """The safety invariant: the repair only ever turned '/' into '\\'."""
    if len(original) != len(repaired):
        return False
    return all(a == b or (a == "/" and b == "\\") for a, b in zip(original, repaired))


def repair_json_text(
    text: str,
    *,
    restore_content_escapes: bool = False,
    max_backtracks: int = 80,
) -> Tuple[Optional[Any], Optional[str]]:
    """Undo the slash damage. Returns ``(parsed, repaired_text)`` or ``(None, None)``.

    Because the transform is length-preserving, ``JSONDecodeError.pos`` indexes
    the input as well as the candidate — so a failure tells us which ambiguous
    quote decision to flip. We flip the last one before the failure point and
    retry, which converges in a handful of passes.
    """
    flips: Set[int] = set()
    for _ in range(max_backtracks + 1):
        candidate, ambiguous = _scan(text, flips, restore_content_escapes)
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError as exc:
            unresolved = [p for p in ambiguous if p < exc.pos and p not in flips]
            if not unresolved:
                return None, None
            flips.add(max(unresolved))
            continue
        except Exception:
            return None, None
        if not is_slash_only_inverse(text, candidate):
            return None, None
        return obj, candidate
    return None, None


def payload_looks_sane(obj: Any) -> bool:
    """Reject a 'successful' parse that plainly is not what was written.

    The input did not parse, so it cannot have been ``{}`` / ``[]`` / a bare
    scalar — a repair that lands on one of those found the wrong reading.
    """
    return isinstance(obj, (dict, list)) and bool(obj)


def conversation_looks_sane(obj: Any) -> bool:
    """Stricter shape check for storage/conversations/**."""
    if not isinstance(obj, dict):
        return False
    msgs = obj.get("messages")
    if msgs is None:
        return "conversation_id" in obj or "title" in obj
    if not isinstance(msgs, list):
        return False
    return all(isinstance(m, dict) and "role" in m for m in msgs)


def repair_file(path: Path, *, restore_content_escapes: bool = False) -> str:
    """Repair one JSON file in place, keeping the original beside it.

    Returns "ok" (already parsed — left byte-identical), "repaired",
    "unrepairable" or "unreadable". Never raises, never deletes, never shortens.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        _log.warning("[JSONRepair] cannot read %s: %s", path, exc)
        return "unreadable"

    try:
        json.loads(text)
        return "ok"                      # not structurally damaged — do not touch
    except json.JSONDecodeError:
        pass
    except Exception:
        return "unreadable"

    checker = (conversation_looks_sane
               if "conversations" in path.parts else payload_looks_sane)
    obj, repaired = repair_json_text(
        text, restore_content_escapes=restore_content_escapes)
    if obj is None or repaired is None or not checker(obj):
        _log.error("[JSONRepair] UNREPAIRABLE — left untouched: %s", path)
        return "unrepairable"

    backup = path.with_name(path.name + BACKUP_SUFFIX)
    try:
        if not backup.exists():          # keep the *first* original, forever
            shutil.copy2(path, backup)
        tmp = path.with_name(path.name + ".repair.tmp")
        tmp.write_text(repaired, encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))   # read-back check
        tmp.replace(path)                              # atomic
    except Exception as exc:
        _log.error("[JSONRepair] could not write repair for %s: %s", path, exc)
        return "unrepairable"
    _log.warning("[JSONRepair] repaired %s (original kept as %s)", path, backup.name)
    return "repaired"


def repair_tree(roots: Iterable[Path], *, restore_content_escapes: bool = False) -> dict:
    """Repair every damaged JSON under `roots`. Backups are never re-scanned."""
    counts = {"ok": 0, "repaired": 0, "unrepairable": 0, "unreadable": 0}
    problems: List[str] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for json_file in sorted(root.rglob("*.json")):
            if json_file.name.endswith(BACKUP_SUFFIX):
                continue
            status = repair_file(
                json_file, restore_content_escapes=restore_content_escapes)
            counts[status] += 1
            if status in ("unrepairable", "unreadable"):
                problems.append(str(json_file))
    counts["problem_files"] = problems
    return counts


def run_escape_repair_migration(
    roots: Iterable[Path],
    marker_dir: Path,
    *,
    force: bool = False,
    restore_content_escapes: bool = False,
) -> Optional[dict]:
    """One-shot and idempotent — safe to call on every boot.

    Gated by a marker file so a healthy restart costs one ``stat``. ``force``
    (env REPAIR_JSON_FORCE=1) re-runs it; because ``repair_file`` leaves already
    parseable files byte-identical, re-running is a no-op on healthy data.
    """
    marker = Path(marker_dir) / MARKER_NAME
    if marker.exists() and not force:
        return None
    result = repair_tree(roots, restore_content_escapes=restore_content_escapes)
    _log.warning(
        "[JSONRepair] migration complete: %d intact, %d repaired, "
        "%d unrepairable, %d unreadable",
        result["ok"], result["repaired"], result["unrepairable"], result["unreadable"],
    )
    for p in result["problem_files"]:
        _log.error("[JSONRepair] still unreadable after migration: %s", p)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({**result, "completed_at": datetime.now().isoformat()}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        _log.error("[JSONRepair] could not write marker %s: %s", marker, exc)
    return result
