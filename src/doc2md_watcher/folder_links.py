from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

from .revisions import ARCHIVE_NAME

PAIR_PATTERN = re.compile(
    r"^(?:\d+[_ -]+)?(?P<name>.+?)[_ -]+(?P<format>DOCX|MD)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FolderPair:
    key: str
    docx: Path
    md: Path


class FolderLinks:
    """Discover and route between sibling-style DOCX/MD folder pairs."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.pairs: list[FolderPair] = []
        self.refresh()

    def refresh(self) -> None:
        candidates: dict[str, dict[str, list[Path]]] = {}
        for folder in chain((self.root,), self.root.rglob("*")):
            if not folder.is_dir() or ARCHIVE_NAME in folder.parts:
                continue
            parsed = parse_linked_folder(folder.name)
            if parsed is None:
                continue
            key, format_name = parsed
            candidates.setdefault(key, {}).setdefault(format_name, []).append(folder.resolve())

        pairs: list[FolderPair] = []
        for key, formats in candidates.items():
            docx_folders = formats.get("docx", [])
            md_folders = formats.get("md", [])
            if len(docx_folders) == 1 and len(md_folders) == 1:
                pairs.append(FolderPair(key, docx_folders[0], md_folders[0]))
        self.pairs = pairs

    def destination_for(self, source: Path) -> Path | None:
        source = source.resolve()
        result = self._destination_for_known_pair(source)
        if result is None:
            self.refresh()
            result = self._destination_for_known_pair(source)
        return result

    def _destination_for_known_pair(self, source: Path) -> Path | None:
        matches: list[tuple[int, Path]] = []
        for pair in self.pairs:
            if source.suffix.lower() == ".docx":
                candidate = _route(source, pair.docx, pair.md)
                if candidate:
                    matches.append((len(pair.docx.parts), candidate))
            elif source.suffix.lower() == ".md":
                candidate = _route(source, pair.md, pair.docx)
                if candidate:
                    matches.append((len(pair.md.parts), candidate))
        return max(matches, default=(0, None), key=lambda item: item[0])[1]


def parse_linked_folder(name: str) -> tuple[str, str] | None:
    match = PAIR_PATTERN.match(name)
    if not match:
        return None
    key = re.sub(r"[^a-z0-9]+", "_", match.group("name").casefold()).strip("_")
    return (key, match.group("format").casefold()) if key else None


def _route(source: Path, source_root: Path, destination_root: Path) -> Path | None:
    try:
        relative_parent = source.parent.relative_to(source_root)
    except ValueError:
        return None
    return destination_root / relative_parent
