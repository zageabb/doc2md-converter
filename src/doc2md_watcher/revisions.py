from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .converters import convert

ARCHIVE_NAME = "98_archive"
STATE_NAME = ".doc2md-watcher-state.json"
TARGET_EXTENSIONS = {
    ".docx": ".md",
    ".xlsx": ".csv",
    ".md": ".docx",
    ".csv": ".xlsx",
    ".pdf": ".md",
    ".json": ".md",
    ".yaml": ".md",
    ".yml": ".md",
    ".xml": ".md",
    ".html": ".md",
    ".htm": ".md",
    ".txt": ".md",
    ".log": ".md",
    ".rtf": ".md",
    ".pptx": ".md",
    ".odt": ".md",
    ".ods": ".csv",
    ".tsv": ".csv",
    ".jsonl": ".csv",
    ".ndjson": ".csv",
    ".eml": ".md",
    ".msg": ".md",
    ".ipynb": ".md",
}


class RevisionManager:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.archive = self.root / ARCHIVE_NAME
        self.state_path = self.archive / STATE_NAME
        self._lock = threading.RLock()
        self._generated = self._load_state()

    def supports(self, path: Path) -> bool:
        path = path.resolve()
        return (
            path.is_file()
            and path.suffix.lower() in TARGET_EXTENSIONS
            and not path.name.lower().endswith(".manifest.json")
            and not self._is_in_archive(path)
        )

    def is_generated_unchanged(self, path: Path) -> bool:
        key = self._relative_key(path)
        expected = self._generated.get(key)
        return expected is not None and expected == _fingerprint(path)

    def process(self, source: Path, destination_folder: Path | None = None) -> Path | None:
        source = source.resolve()
        with self._lock:
            if not self.supports(source) or self.is_generated_unchanged(source):
                return None

            target_suffix = TARGET_EXTENSIONS[source.suffix.lower()]
            logical_stem = _logical_stem(source.stem)
            destination_folder = (destination_folder or source.parent).resolve()
            try:
                destination_folder.relative_to(self.root)
            except ValueError as exc:
                raise ValueError(f"destination is outside watch root: {destination_folder}") from exc
            destination_folder.mkdir(parents=True, exist_ok=True)
            revision = self._next_revision(destination_folder, logical_stem, target_suffix)
            destination = destination_folder / f"{logical_stem}_r{revision:03d}{target_suffix}"
            self._archive_old_revisions(destination_folder, logical_stem, target_suffix)
            self._atomic_convert(source, destination)
            self._write_manifest(source, destination, revision)
            self._generated[self._relative_key(destination)] = _fingerprint(destination)
            self._save_state()
            return destination

    def _next_revision(self, folder: Path, stem: str, suffix: str) -> int:
        pattern = re.compile(rf"^{re.escape(stem)}_r(\d+){re.escape(suffix)}$", re.IGNORECASE)
        numbers: list[int] = []
        relative = folder.relative_to(self.root)
        for candidate_folder in (folder, self.archive / relative):
            if candidate_folder.exists():
                for path in candidate_folder.iterdir():
                    match = pattern.match(path.name)
                    if match:
                        numbers.append(int(match.group(1)))
        return max(numbers, default=0) + 1

    def _archive_old_revisions(self, folder: Path, stem: str, suffix: str) -> None:
        pattern = re.compile(rf"^{re.escape(stem)}_r\d+{re.escape(suffix)}$", re.IGNORECASE)
        archive_folder = self.archive / folder.relative_to(self.root)
        for path in folder.iterdir():
            if path.is_file() and pattern.match(path.name):
                archive_folder.mkdir(parents=True, exist_ok=True)
                target = archive_folder / path.name
                if target.exists():
                    raise FileExistsError(f"archive destination already exists: {target}")
                shutil.move(str(path), target)
                manifest = _manifest_path(path)
                if manifest.exists():
                    manifest_target = archive_folder / manifest.name
                    if manifest_target.exists():
                        raise FileExistsError(
                            f"archive manifest destination already exists: {manifest_target}"
                        )
                    shutil.move(str(manifest), manifest_target)
                self._generated.pop(self._relative_key(path), None)

    def _atomic_convert(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}-", suffix=destination.suffix, dir=destination.parent
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            convert(source, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_state(self) -> dict[str, str]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _write_manifest(self, source: Path, destination: Path, revision: int) -> None:
        manifest = {
            "manifest_version": 1,
            "converter": "doc2md-watcher",
            "converter_version": __version__,
            "converted_at": datetime.now(timezone.utc).isoformat(),
            "revision": revision,
            "source": {
                "path": source.relative_to(self.root).as_posix(),
                "format": source.suffix.lower(),
                "sha256": _fingerprint(source),
                "size_bytes": source.stat().st_size,
            },
            "output": {
                "path": destination.relative_to(self.root).as_posix(),
                "format": destination.suffix.lower(),
                "sha256": _fingerprint(destination),
                "size_bytes": destination.stat().st_size,
            },
            "warnings": [],
        }
        path = _manifest_path(destination)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _save_state(self) -> None:
        self.archive.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._generated, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

    def _relative_key(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _is_in_archive(self, path: Path) -> bool:
        try:
            path.relative_to(self.archive)
            return True
        except ValueError:
            return False


def _logical_stem(stem: str) -> str:
    return re.sub(r"_r\d+$", "", stem, flags=re.IGNORECASE)


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(output: Path) -> Path:
    return output.with_name(output.name + ".manifest.json")
