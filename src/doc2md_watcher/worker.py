from __future__ import annotations

import os
import queue
import time
import traceback
from pathlib import Path
from typing import Any

import portalocker

from .revisions import RevisionManager


def conversion_worker(
    roots: list[str],
    jobs: Any,
    events: Any,
    stop_event: Any,
    poll_seconds: float = 0.5,
    parent_pid: int | None = None,
) -> None:
    """Run conversions serially in a child process."""
    managers = {str(Path(root).resolve()): RevisionManager(Path(root)) for root in roots}
    while not stop_event.is_set():
        if parent_pid is not None and os.getppid() != parent_pid:
            break
        try:
            job = jobs.get(timeout=0.25)
        except queue.Empty:
            continue
        if job is None:
            break

        root_text, source_text = job
        source = Path(source_text)
        manager = managers[root_text]
        _emit(events, "waiting", source)
        if not wait_until_released(source, stop_event, poll_seconds):
            _emit(events, "skipped", source, message="file disappeared or shutdown requested")
            continue

        try:
            _emit(events, "converting", source)
            output = manager.process(source)
            if output is None:
                _emit(events, "skipped", source, message="generated or unsupported file")
            else:
                _emit(events, "completed", source, output=str(output))
        except Exception as exc:
            _emit(
                events,
                "failed",
                source,
                message=str(exc),
                detail=traceback.format_exc(),
            )
    events.put({"status": "worker_stopped", "timestamp": time.time()})


def wait_until_released(path: Path, stop_event: Any, poll_seconds: float = 0.5) -> bool:
    """Wait for two stable samples and an obtainable non-blocking file lock."""
    previous: tuple[int, int] | None = None
    stable_samples = 0
    while not stop_event.is_set():
        try:
            stat = path.stat()
            current = (stat.st_size, stat.st_mtime_ns)
        except FileNotFoundError:
            return False

        if _office_lock_exists(path):
            stable_samples = 0
        elif current == previous and _can_lock(path):
            stable_samples += 1
            if stable_samples >= 2:
                return True
        else:
            stable_samples = 0
        previous = current
        stop_event.wait(poll_seconds)
    return False


def _office_lock_exists(path: Path) -> bool:
    # Microsoft Office commonly leaves this owner file beside an open document.
    return (path.parent / f"~${path.name}").exists()


def _can_lock(path: Path) -> bool:
    try:
        # portalocker maps to flock on macOS and mandatory Win32 locking on
        # Windows. Opening read/write also catches Office sharing violations.
        handle = path.open("r+b")
    except (PermissionError, OSError):
        return False
    try:
        try:
            portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
            portalocker.unlock(handle)
        except (portalocker.LockException, OSError):
            return False
        return True
    finally:
        handle.close()


def _emit(events: Any, status: str, path: Path, **extra: Any) -> None:
    events.put(
        {
            "status": status,
            "path": str(path),
            "name": path.name,
            "timestamp": time.time(),
            **extra,
        }
    )
