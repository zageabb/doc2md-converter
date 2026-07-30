from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .revisions import ARCHIVE_NAME

QUEUE_NAME = ".doc2md-watcher-queue.json"
INCOMPLETE_STATUSES = {"queued", "waiting", "converting"}


class PersistentQueue:
    """Small crash-safe queue journal stored below a watch root's archive."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.path = self.root / ARCHIVE_NAME / QUEUE_NAME
        self._lock = threading.RLock()
        self._entries = self._load()

    def add(self, source: Path) -> bool:
        key = str(source.resolve())
        with self._lock:
            existing = self._entries.get(key)
            if existing and existing.get("status") in INCOMPLETE_STATUSES:
                return False
            self._entries[key] = {
                "path": key,
                "status": "queued",
                "queued_at": time.time(),
                "updated_at": time.time(),
            }
            self._save()
            return True

    def update(self, source: Path, status: str, message: str | None = None) -> None:
        key = str(source.resolve())
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return
            entry["status"] = status
            entry["updated_at"] = time.time()
            if message:
                entry["message"] = message
            self._save()

    def complete(self, source: Path) -> None:
        key = str(source.resolve())
        with self._lock:
            if self._entries.pop(key, None) is not None:
                self._save()

    def recover(self) -> list[Path]:
        with self._lock:
            recovered = [
                Path(entry["path"])
                for entry in self._entries.values()
                if entry.get("status") in INCOMPLETE_STATUSES
            ]
            for source in recovered:
                self._entries[str(source)]["status"] = "queued"
                self._entries[str(source)]["updated_at"] = time.time()
            if recovered:
                self._save()
            return recovered

    def _load(self) -> dict[str, dict]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._entries, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)
