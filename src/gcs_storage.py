"""
GCS Storage - Persistent storage for Parquet files and catalog.
Syncs table data to/from Google Cloud Storage so it survives Cloud Run redeploys.
Disabled gracefully if GCS_BUCKET_NAME env var is not set.
"""
import os
from pathlib import Path
from typing import List, Optional

from .logger import logger
from .config import BASE_DIR

# GCS config - disabled if not set
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

# Local paths (must match catalog.py)
PARQUET_DIR = BASE_DIR / "storage" / "parquet"
CATALOG_FILE = PARQUET_DIR / "catalog.json"

# GCS prefixes
_PARQUET_PREFIX = "tables/"
_CATALOG_BLOB = "catalog/catalog.json"


def is_enabled() -> bool:
    """Check if GCS storage is configured."""
    return bool(GCS_BUCKET_NAME)


def _get_bucket():
    """Get GCS bucket client. Returns None if not available."""
    if not GCS_BUCKET_NAME:
        return None
    try:
        from google.cloud import storage
        client = storage.Client()
        return client.bucket(GCS_BUCKET_NAME)
    except Exception as e:
        logger.warning(f"[GCS] Cannot connect to bucket: {e}")
        return None


def upload_file(local_path: str, blob_name: str) -> bool:
    """Upload a local file to GCS."""
    bucket = _get_bucket()
    if not bucket:
        return False
    try:
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path)
        logger.info(f"[GCS] Uploaded: {blob_name}")
        return True
    except Exception as e:
        logger.warning(f"[GCS] Upload failed for {blob_name}: {e}")
        return False


def download_file(blob_name: str, local_path: str) -> bool:
    """Download a file from GCS to local path."""
    bucket = _get_bucket()
    if not bucket:
        return False
    try:
        blob = bucket.blob(blob_name)
        if not blob.exists():
            return False
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(local_path)
        logger.info(f"[GCS] Downloaded: {blob_name}")
        return True
    except Exception as e:
        logger.warning(f"[GCS] Download failed for {blob_name}: {e}")
        return False


def list_blobs(prefix: str) -> List[str]:
    """List blob names under a prefix."""
    bucket = _get_bucket()
    if not bucket:
        return []
    try:
        return [b.name for b in bucket.list_blobs(prefix=prefix)]
    except Exception as e:
        logger.warning(f"[GCS] List failed for {prefix}: {e}")
        return []


def delete_blob(blob_name: str) -> bool:
    """Delete a single blob from GCS."""
    bucket = _get_bucket()
    if not bucket:
        return False
    try:
        blob = bucket.blob(blob_name)
        blob.delete()
        logger.info(f"[GCS] Deleted: {blob_name}")
        return True
    except Exception as e:
        logger.warning(f"[GCS] Delete failed for {blob_name}: {e}")
        return False


# ── High-level sync functions ────────────────────────────────


def sync_catalog_to_gcs():
    """Upload catalog.json to GCS."""
    if not is_enabled() or not CATALOG_FILE.exists():
        return
    upload_file(str(CATALOG_FILE), _CATALOG_BLOB)


def sync_catalog_from_gcs():
    """Download catalog.json from GCS if local is missing."""
    if not is_enabled():
        return
    if not CATALOG_FILE.exists():
        PARQUET_DIR.mkdir(parents=True, exist_ok=True)
        download_file(_CATALOG_BLOB, str(CATALOG_FILE))


def sync_parquet_to_gcs(parquet_path: str):
    """Upload a single parquet file to GCS."""
    if not is_enabled():
        return
    name = Path(parquet_path).name
    upload_file(parquet_path, f"{_PARQUET_PREFIX}{name}")


def sync_all_parquets_from_gcs():
    """Download all parquet files from GCS to local."""
    if not is_enabled():
        return
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    blobs = list_blobs(_PARQUET_PREFIX)
    count = 0
    for blob_name in blobs:
        filename = blob_name.replace(_PARQUET_PREFIX, "")
        if not filename or not filename.endswith(".parquet"):
            continue
        local_path = PARQUET_DIR / filename
        if not local_path.exists():
            if download_file(blob_name, str(local_path)):
                count += 1
    if count > 0:
        logger.info(f"[GCS] Downloaded {count} parquet files")


# ── Conversation sync ─────────────────────────────────────

_CONVERSATIONS_PREFIX = "conversations/"


def sync_user_conversations_to_gcs(username: str):
    """Upload all conversation JSON files for a user to GCS."""
    if not is_enabled():
        return
    from .config import CONVERSATIONS_DIR
    user_dir = CONVERSATIONS_DIR / username
    if not user_dir.exists():
        return
    count = 0
    for json_file in user_dir.glob("*.json"):
        blob_name = f"{_CONVERSATIONS_PREFIX}{username}/{json_file.name}"
        if upload_file(str(json_file), blob_name):
            count += 1
    if count > 0:
        logger.info(f"[GCS] Uploaded {count} conversation files for {username}")


def sync_user_conversations_from_gcs(username: str):
    """Download conversation JSON files for a user from GCS (if local missing)."""
    if not is_enabled():
        return
    from .config import CONVERSATIONS_DIR
    user_dir = CONVERSATIONS_DIR / username
    user_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{_CONVERSATIONS_PREFIX}{username}/"
    blobs = list_blobs(prefix)
    count = 0
    for blob_name in blobs:
        filename = blob_name.replace(prefix, "")
        if not filename or not filename.endswith(".json"):
            continue
        local_path = user_dir / filename
        if not local_path.exists():
            if download_file(blob_name, str(local_path)):
                count += 1
    if count > 0:
        logger.info(f"[GCS] Downloaded {count} conversation files for {username}")


# ── Converter registry sync ──────────────────────────────

_CONVERTER_REGISTRY_BLOB = "converters/registry.json"


def sync_converter_registry_to_gcs():
    """Upload converter registry.json to GCS."""
    if not is_enabled():
        return
    from .config import CONVERTER_REGISTRY_FILE
    if CONVERTER_REGISTRY_FILE.exists():
        upload_file(str(CONVERTER_REGISTRY_FILE), _CONVERTER_REGISTRY_BLOB)


def sync_converter_registry_from_gcs():
    """Download converter registry.json from GCS if local is missing."""
    if not is_enabled():
        return
    from .config import CONVERTER_REGISTRY_FILE
    if not CONVERTER_REGISTRY_FILE.exists():
        CONVERTER_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        download_file(_CONVERTER_REGISTRY_BLOB, str(CONVERTER_REGISTRY_FILE))


def clear_gcs_tables():
    """Delete all table data from GCS (parquets + catalog)."""
    if not is_enabled():
        return
    bucket = _get_bucket()
    if not bucket:
        return
    try:
        count = 0
        for blob in bucket.list_blobs(prefix=_PARQUET_PREFIX):
            blob.delete()
            count += 1
        # Also delete catalog
        delete_blob(_CATALOG_BLOB)
        logger.info(f"[GCS] Cleared {count} parquets + catalog")
    except Exception as e:
        logger.warning(f"[GCS] Clear failed: {e}")
