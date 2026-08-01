"""
Knowledge collections — named groups of documents.
JSON-backed at storage/knowledge_collections.json.
Inspired by Open WebUI's Knowledge + KnowledgeFiles model.
"""

import json
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

from .config import STORAGE_DIR
from .logger import logger


COLLECTIONS_FILE = STORAGE_DIR / "knowledge_collections.json"


@dataclass
class KnowledgeCollection:
    collection_id: str
    name: str
    project_id: str = ""
    description: str = ""
    document_ids: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class KnowledgeStore:
    """Singleton JSON-backed knowledge collection store."""

    _instance: Optional["KnowledgeStore"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._collections: Dict[str, KnowledgeCollection] = {}
                    inst._file_lock = threading.Lock()
                    inst._load()
                    cls._instance = inst
        return cls._instance

    def _load(self) -> None:
        if COLLECTIONS_FILE.exists():
            try:
                data = json.loads(COLLECTIONS_FILE.read_text(encoding="utf-8"))
                for col_id, col in data.items():
                    self._collections[col_id] = KnowledgeCollection(**col)
                logger.info(f"[Knowledge] Loaded {len(self._collections)} collections")
            except Exception as e:
                logger.error(f"[Knowledge] Failed to load: {e}")

    def _save(self) -> None:
        COLLECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {cid: asdict(col) for cid, col in self._collections.items()}
        COLLECTIONS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def create(self, name: str, description: str = "", project_id: str = "") -> KnowledgeCollection:
        with self._file_lock:
            col_id = f"col_{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            col = KnowledgeCollection(
                collection_id=col_id,
                name=name,
                project_id=project_id,
                description=description,
                created_at=now,
                updated_at=now,
            )
            self._collections[col_id] = col
            self._save()
            logger.info(f"[Knowledge] Created collection: {name} ({col_id})")
            return col

    def get(self, col_id: str, project_id: str = "") -> Optional[KnowledgeCollection]:
        col = self._collections.get(col_id)
        if col and project_id and col.project_id != project_id:
            return None
        return col

    def list_all(self, project_id: str = "") -> List[KnowledgeCollection]:
        items = [c for c in self._collections.values()
                 if not project_id or c.project_id == project_id]
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return items

    def update(
        self,
        col_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        project_id: str = "",
    ) -> Optional[KnowledgeCollection]:
        with self._file_lock:
            col = self._collections.get(col_id)
            if not col:
                return None
            if project_id and col.project_id != project_id:
                return None
            if name is not None:
                col.name = name
            if description is not None:
                col.description = description
            col.updated_at = datetime.now().isoformat()
            self._save()
            return col

    def delete(self, col_id: str, project_id: str = "") -> bool:
        with self._file_lock:
            if col_id in self._collections and (
                not project_id or self._collections[col_id].project_id == project_id
            ):
                del self._collections[col_id]
                self._save()
                logger.info(f"[Knowledge] Deleted collection: {col_id}")
                return True
            return False

    def add_documents(self, col_id: str, doc_ids: List[str],
                      project_id: str = "") -> Optional[KnowledgeCollection]:
        with self._file_lock:
            col = self._collections.get(col_id)
            if not col:
                return None
            if project_id and col.project_id != project_id:
                return None
            existing = set(col.document_ids)
            for did in doc_ids:
                if did and did not in existing:
                    col.document_ids.append(did)
                    existing.add(did)
            col.updated_at = datetime.now().isoformat()
            self._save()
            return col

    def remove_document(self, col_id: str, doc_id: str,
                        project_id: str = "") -> Optional[KnowledgeCollection]:
        with self._file_lock:
            col = self._collections.get(col_id)
            if col and project_id and col.project_id != project_id:
                return None
            if not col or doc_id not in col.document_ids:
                return col
            col.document_ids.remove(doc_id)
            col.updated_at = datetime.now().isoformat()
            self._save()
            return col

    def prune_missing_documents(self, valid_doc_ids: set) -> int:
        """Remove doc_ids that no longer exist in the document registry. Returns count removed."""
        removed = 0
        with self._file_lock:
            for col in self._collections.values():
                before = len(col.document_ids)
                col.document_ids = [d for d in col.document_ids if d in valid_doc_ids]
                removed += before - len(col.document_ids)
            if removed:
                self._save()
        return removed


def get_knowledge_store() -> KnowledgeStore:
    return KnowledgeStore()
