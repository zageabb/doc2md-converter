import threading
import time
from pathlib import Path

from doc2md_watcher.worker import wait_until_released


def test_waits_for_stable_file(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("first", encoding="utf-8")
    stop = threading.Event()

    started = time.monotonic()
    assert wait_until_released(source, stop, poll_seconds=0.01)
    assert time.monotonic() - started >= 0.02


def test_office_owner_file_blocks_until_removed(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"content")
    owner = tmp_path / "~$report.docx"
    owner.write_bytes(b"lock")
    stop = threading.Event()

    timer = threading.Timer(0.04, owner.unlink)
    timer.start()
    try:
        assert wait_until_released(source, stop, poll_seconds=0.01)
    finally:
        timer.cancel()
