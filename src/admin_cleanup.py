"""Two-phase, count-gated cleanup for the demo admin document corpus."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .config import QDRANT_COLLECTION, STORAGE_DIR, VECTOR_STORE_BACKEND


EXPECTED = {"document": 26, "email": 24, "data": 33}
MANIFEST_DIR = Path(STORAGE_DIR) / "cleanup_manifests"


def _counts(records) -> Dict[str, int]:
    out = {"document": 0, "email": 0, "data": 0}
    for record in records:
        key = record.file_type if record.file_type in out else "document"
        out[key] += 1
    return out


def prepare_cleanup(*, project_id: str = "", expected: Optional[Dict[str, int]] = None) -> Dict:
    from .document_registry import REGISTRY_FILE, get_document_registry
    records = get_document_registry().get_all(project_id=project_id if project_id else None)
    actual = _counts(records); expected = expected or EXPECTED
    if actual != expected:
        return {"ready": False, "expected": expected, "actual": actual,
                "reason": "count_mismatch"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(STORAGE_DIR) / "artifacts" / f"cleanup-backup-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    # Back up originals and the registries/databases that name their derivatives.
    archive = backup_dir / "files.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for record in records:
            path = Path(record.file_path)
            if path.is_file():
                zf.write(path, arcname=f"originals/{record.doc_id}/{path.name}")
    for path in (REGISTRY_FILE, Path(STORAGE_DIR) / "chunks" / "chunks.db",
                 Path(STORAGE_DIR) / "events" / "events.db",
                 Path(STORAGE_DIR) / "interactions" / "interactions.db",
                 Path(STORAGE_DIR) / "parquet" / "catalog.json",
                 Path(STORAGE_DIR) / "knowledge_collections.json",
                 Path(STORAGE_DIR) / "document_clusters.json"):
        if path.is_file():
            shutil.copy2(path, backup_dir / path.name)

    # Preserve only affected notice/parquet derivatives inside the same
    # recoverable archive; conversations and query history are intentionally
    # left untouched by execution.
    record_names = {record.file_name for record in records}
    record_ids = {record.doc_id for record in records}
    with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        notices_dir = Path(__file__).resolve().parents[1] / "data" / "notices"
        for notice in notices_dir.glob("*.json") if notices_dir.is_dir() else []:
            if notice.stem in record_ids:
                zf.write(notice, arcname=f"notices/{notice.name}")
        try:
            from .catalog import get_catalog
            for entry in get_catalog().entries.values():
                if Path(entry.source_file).name not in record_names:
                    continue
                for table in entry.tables:
                    parquet = Path(table.parquet_path)
                    if parquet.is_file():
                        zf.write(parquet, arcname=f"parquet/{parquet.name}")
        except Exception:
            pass

    qdrant_snapshot = "not-applicable"
    if VECTOR_STORE_BACKEND == "qdrant":
        from .document_rag import get_document_rag
        snap = get_document_rag().qdrant_client.create_snapshot(QDRANT_COLLECTION)
        qdrant_snapshot = str(getattr(snap, "name", "") or "created")

    items = [{
        "doc_id": r.doc_id, "name": r.file_name, "type": r.file_type,
        "checksum": r.file_hash, "path": r.file_path, "project_id": r.project_id,
    } for r in records]
    payload = {"created_at": stamp, "project_id": project_id, "expected": expected,
               "actual": actual, "backup_dir": str(backup_dir),
               "qdrant_snapshot": qdrant_snapshot, "items": items, "status": "prepared"}
    token = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    payload["token"] = token
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    path = MANIFEST_DIR / f"{token}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ready": True, "token": token, "actual": actual,
            "backup_dir": str(backup_dir), "items": items}


def execute_cleanup(token: str, confirmation: str) -> Dict:
    if confirmation != "DELETE 26 DOCUMENTS 24 EMAILS 33 EXCEL":
        raise ValueError("confirmation text does not match")
    path = MANIFEST_DIR / f"{token}.json"
    if not path.is_file():
        raise ValueError("cleanup manifest not found")
    payload = json.loads(path.read_text(encoding="utf-8"))
    signed = {key: value for key, value in payload.items() if key != "token"}
    computed = hashlib.sha256(json.dumps(signed, sort_keys=True).encode()).hexdigest()
    if payload.get("token") != token or computed != token or payload.get("status") != "prepared":
        raise ValueError("cleanup manifest is not executable")
    if payload.get("actual") != EXPECTED:
        raise ValueError("cleanup manifest counts changed")
    from .document_registry import get_document_registry
    from .file_router import delete_document
    registry = get_document_registry(); results = []
    for item in payload["items"]:
        record = registry.get(item["doc_id"])
        if not record or record.file_hash != item["checksum"] or record.file_name != item["name"]:
            raise RuntimeError(f"record changed after prepare: {item['doc_id']}")
    for item in payload["items"]:
        results.append(delete_document(item["doc_id"]))
    payload["status"] = "completed"
    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    payload["results"] = results
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "deleted": len(results), "backup_dir": payload["backup_dir"]}


__all__ = ["EXPECTED", "execute_cleanup", "prepare_cleanup"]
