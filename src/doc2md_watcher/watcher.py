from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from .revisions import ARCHIVE_NAME, TARGET_EXTENSIONS, RevisionManager
from .persistent_queue import PersistentQueue
from .worker import conversion_worker

LOG = logging.getLogger(__name__)


class ConversionHandler(FileSystemEventHandler):
    def __init__(
        self,
        manager: RevisionManager,
        persistent_queue: PersistentQueue,
        jobs: Any,
        events: Any,
        settle_seconds: float = 1.0,
    ):
        self.manager = manager
        self.persistent_queue = persistent_queue
        self.jobs = jobs
        self.events = events
        self.settle_seconds = settle_seconds
        self._timers: dict[Path, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_created(self, event: FileSystemEvent) -> None:
        self._schedule(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._schedule(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule_path(Path(event.dest_path))

    def close(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    def _schedule(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule_path(Path(event.src_path))

    def _schedule_path(self, path: Path) -> None:
        if (
            ARCHIVE_NAME in path.parts
            or path.name.startswith((".", "~$"))
            or path.name.lower().endswith(".manifest.json")
            or path.suffix.lower() not in TARGET_EXTENSIONS
        ):
            return
        path = path.resolve()
        self.events.put(
            {"status": "pending", "path": str(path), "name": path.name, "timestamp": time.time()}
        )
        with self._lock:
            previous = self._timers.pop(path, None)
            if previous:
                previous.cancel()
            timer = threading.Timer(self.settle_seconds, self._process, args=(path,))
            timer.daemon = True
            self._timers[path] = timer
            timer.start()

    def _process(self, path: Path) -> None:
        with self._lock:
            self._timers.pop(path, None)
        if not self.persistent_queue.add(path):
            return
        self.jobs.put((str(self.manager.root), str(path)))
        self.events.put(
            {"status": "queued", "path": str(path), "name": path.name, "timestamp": time.time()}
        )


def watch(
    roots: list[Path],
    settle_seconds: float,
    initial: bool,
    event_sink: Any | None = None,
    external_stop: threading.Event | None = None,
) -> None:
    # Polling is dependable on local disks, network mounts, containers, and
    # macOS environments where an FSEvents stream may not be available.
    observer = PollingObserver(timeout=0.5)
    handlers: list[ConversionHandler] = []
    managers: list[RevisionManager] = []
    persistent_queues: dict[str, PersistentQueue] = {}
    context = mp.get_context("spawn")
    jobs = context.Queue()
    worker_events = context.Queue()
    worker_stop = context.Event()
    resolved_roots = [str(root.expanduser().resolve()) for root in roots]
    worker = context.Process(
        target=conversion_worker,
        args=(resolved_roots, jobs, worker_events, worker_stop, 0.5, os.getpid()),
        name="doc2md-converter",
        daemon=True,
    )
    worker.start()
    event_sink = event_sink or queue.Queue()
    relay_stop = threading.Event()
    relay = threading.Thread(
        target=_relay_events,
        args=(worker_events, event_sink, relay_stop, persistent_queues),
        daemon=True,
    )
    try:
        for root in roots:
            root.mkdir(parents=True, exist_ok=True)
            manager = RevisionManager(root)
            persistent_queue = PersistentQueue(manager.root)
            persistent_queues[str(manager.root)] = persistent_queue
            handler = ConversionHandler(
                manager, persistent_queue, jobs, event_sink, settle_seconds
            )
            managers.append(manager)
            handlers.append(handler)
            observer.schedule(handler, str(manager.root), recursive=True)
            LOG.info("watching %s", manager.root)

        relay.start()
        inventory = [
            str(path.resolve())
            for manager in managers
            for path in manager.root.rglob("*")
            if manager.supports(path)
        ]
        event_sink.put(
            {
                "status": "inventory",
                "total": len(inventory),
                "paths": inventory,
                "timestamp": time.time(),
            }
        )

        recovered_paths: set[str] = set()
        for root_text, persistent_queue in persistent_queues.items():
            for path in persistent_queue.recover():
                path_text = str(path.resolve())
                recovered_paths.add(path_text)
                jobs.put((root_text, path_text))
                event_sink.put(
                    {
                        "status": "queued",
                        "path": path_text,
                        "name": path.name,
                        "message": "restored from previous session",
                        "restored": True,
                        "timestamp": time.time(),
                    }
                )

        if initial:
            for manager in managers:
                for path in manager.root.rglob("*"):
                    if manager.supports(path):
                        path_text = str(path.resolve())
                        if path_text in recovered_paths:
                            continue
                        persistent_queue = persistent_queues[str(manager.root)]
                        if not persistent_queue.add(path):
                            continue
                        jobs.put((str(manager.root), path_text))
                        event_sink.put(
                            {
                                "status": "queued",
                                "path": str(path.resolve()),
                                "name": path.name,
                                "timestamp": time.time(),
                            }
                        )

        observer.start()
        event_sink.put({"status": "watching", "timestamp": time.time()})
        while observer.is_alive() and not (external_stop and external_stop.is_set()):
            observer.join(timeout=0.25)
    except KeyboardInterrupt:
        LOG.info("stopping")
    finally:
        observer.stop()
        if observer.is_alive():
            observer.join()
        for handler in handlers:
            handler.close()
        worker_stop.set()
        jobs.put(None)
        worker.join(timeout=5)
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=2)
        relay.join(timeout=2)
        if relay.is_alive():
            relay_stop.set()
            relay.join(timeout=1)


def _relay_events(
    source: Any,
    destination: Any,
    stop: threading.Event,
    persistent_queues: dict[str, PersistentQueue],
) -> None:
    while not stop.is_set():
        try:
            event = source.get(timeout=0.2)
        except queue.Empty:
            continue
        if event.get("status") == "worker_stopped":
            break
        destination.put(event)
        status = event.get("status")
        source_path = Path(event["path"]) if event.get("path") else None
        persistent_queue = _queue_for_path(source_path, persistent_queues) if source_path else None
        if persistent_queue:
            if status in {"completed", "skipped"}:
                persistent_queue.complete(source_path)
            elif status in {"waiting", "converting", "failed"}:
                persistent_queue.update(source_path, status, event.get("message"))
        if status == "completed":
            LOG.info("converted %s -> %s", event["path"], event["output"])
        elif status == "failed":
            LOG.error("conversion failed for %s: %s", event["path"], event.get("message", ""))


def _queue_for_path(
    path: Path, persistent_queues: dict[str, PersistentQueue]
) -> PersistentQueue | None:
    resolved = path.resolve()
    matches: list[tuple[int, PersistentQueue]] = []
    for root_text, persistent_queue in persistent_queues.items():
        try:
            resolved.relative_to(Path(root_text))
            matches.append((len(Path(root_text).parts), persistent_queue))
        except ValueError:
            continue
    return max(matches, default=(0, None), key=lambda item: item[0])[1]
