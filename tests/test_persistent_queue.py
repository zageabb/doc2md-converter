from pathlib import Path

from doc2md_watcher.persistent_queue import PersistentQueue


def test_incomplete_jobs_are_recovered_after_restart(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"document")
    queue = PersistentQueue(tmp_path)
    assert queue.add(source)
    queue.update(source, "converting")

    restarted = PersistentQueue(tmp_path)
    assert restarted.recover() == [source]
    assert not restarted.add(source)


def test_completed_jobs_are_removed(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"document")
    queue = PersistentQueue(tmp_path)
    queue.add(source)
    queue.complete(source)

    assert PersistentQueue(tmp_path).recover() == []


def test_failed_jobs_are_retained_but_not_auto_retried(tmp_path: Path) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"not a pdf")
    queue = PersistentQueue(tmp_path)
    queue.add(source)
    queue.update(source, "failed", "invalid PDF")

    assert PersistentQueue(tmp_path).recover() == []
