"""Project-scoped, immutable Delay Analysis Toolkit evidence packages."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .config import STORAGE_DIR
from .evidence_model import EvidenceItem


DB_PATH = Path(STORAGE_DIR) / "toolkit_evidence.db"


class ToolkitEvidenceStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path); self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS toolkit_artifacts ("
                "artifact_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,title TEXT NOT NULL,"
                "methodology TEXT NOT NULL,payload_json TEXT NOT NULL,created_by TEXT NOT NULL,"
                "created_at TEXT NOT NULL)"
            )

    def create(self, *, project_id: str, title: str, methodology: str,
               findings: List[str], source_doc_ids: List[str], created_by: str) -> Dict:
        payload = {"findings": findings, "source_doc_ids": source_doc_ids}
        material = json.dumps({"project_id": project_id, "title": title,
                               "methodology": methodology, **payload}, sort_keys=True)
        artifact_id = "toolkit_" + hashlib.sha256(material.encode()).hexdigest()[:16]
        created_at = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO toolkit_artifacts VALUES (?,?,?,?,?,?,?)",
                [artifact_id, project_id, title[:300], methodology[:300],
                 json.dumps(payload, ensure_ascii=False), created_by, created_at],
            )
        return self.get(artifact_id, project_id) or {}

    def get(self, artifact_id: str, project_id: str) -> Dict | None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM toolkit_artifacts WHERE artifact_id=? AND project_id=?",
                [artifact_id, project_id],
            ).fetchone()
        if not row:
            return None
        item = dict(row); item.update(json.loads(item.pop("payload_json")))
        return item

    def list_project(self, project_id: str) -> List[Dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM toolkit_artifacts WHERE project_id=? ORDER BY created_at DESC",
                [project_id],
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row); item.update(json.loads(item.pop("payload_json"))); out.append(item)
        return out

    def as_evidence(self, artifact_ids: List[str], project_id: str) -> List[EvidenceItem]:
        out: List[EvidenceItem] = []
        for artifact_id in artifact_ids:
            artifact = self.get(artifact_id, project_id)
            if not artifact:
                raise ValueError(f"Toolkit artifact does not belong to project: {artifact_id}")
            for index, finding in enumerate(artifact["findings"], 1):
                out.append(EvidenceItem(
                    source_id=f"{artifact_id}_{index}", doc_id=artifact_id,
                    file_name=artifact["title"], title=artifact["methodology"],
                    kind="toolkit", excerpt=str(finding), score=1.0,
                ))
        return out


_store: ToolkitEvidenceStore | None = None


def get_toolkit_evidence_store() -> ToolkitEvidenceStore:
    global _store
    if _store is None:
        _store = ToolkitEvidenceStore()
    return _store


__all__ = ["ToolkitEvidenceStore", "get_toolkit_evidence_store"]
