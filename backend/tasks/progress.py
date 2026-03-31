"""Thread-safe in-memory indexing progress store."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class FileIndexingStatus:
    file_id: str
    filename: str
    status: str = "pending"
    progress: float = 0.0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    details: Dict = field(default_factory=dict)


class IndexingProgress:
    def __init__(self):
        self._store: Dict[str, FileIndexingStatus] = {}
        self._lock = threading.Lock()

    def start(self, file_id: str, filename: str) -> FileIndexingStatus:
        status = FileIndexingStatus(
            file_id=file_id,
            filename=filename,
            status="indexing",
            started_at=datetime.now().isoformat(),
        )
        with self._lock:
            self._store[file_id] = status
        return status

    def update(self, file_id: str, progress: float, **details):
        with self._lock:
            if file_id in self._store:
                self._store[file_id].progress = progress
                self._store[file_id].details.update(details)

    def complete(self, file_id: str, details: dict = None):
        with self._lock:
            if file_id in self._store:
                self._store[file_id].status = "completed"
                self._store[file_id].progress = 1.0
                self._store[file_id].completed_at = datetime.now().isoformat()
                if details:
                    self._store[file_id].details.update(details)

    def fail(self, file_id: str, error: str):
        with self._lock:
            if file_id in self._store:
                self._store[file_id].status = "error"
                self._store[file_id].error = error

    def get(self, file_id: str) -> Optional[FileIndexingStatus]:
        return self._store.get(file_id)

    def all(self) -> List[FileIndexingStatus]:
        return list(self._store.values())


indexing_progress = IndexingProgress()
