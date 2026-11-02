"""Opt-in adapter for the shared conversion library.

Intentionally not an installed dependency until a reviewed release is pinned.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

SUPPORTED_PAIRS = frozenset({
    (".docx", ".md"), (".md", ".docx"), (".pdf", ".md"),
    (".pptx", ".md"), (".html", ".md"), (".htm", ".md"),
    (".csv", ".xlsx"), (".xlsx", ".csv"),
})


def shared_conversion_enabled() -> bool:
    return os.environ.get("DOC2MD_USE_SHARED_CONVERSION", "").strip().lower() in {"1", "true", "yes"}


def try_shared_conversion(source: Path, destination: Path) -> bool:
    """True if dispatched to shared converter; no silent fallback on shared errors."""
    if not shared_conversion_enabled():
        return False
    if (source.suffix.lower(), destination.suffix.lower()) not in SUPPORTED_PAIRS:
        return False
    if sys.version_info < (3, 11):
        raise RuntimeError("Shared conversion needs Python 3.11 or newer")
    try:
        from shared_document_conversion import convert
    except ImportError as exc:
        raise RuntimeError(
            "Shared conversion is enabled but zageabb-document-conversion is not installed"
        ) from exc
    # Destination revisions are unique by the watcher's own revision manager.
    # No overwrite is enabled; a shared conversion failure is reported, not ignored.
    convert(source, destination, overwrite=False)
    return True
