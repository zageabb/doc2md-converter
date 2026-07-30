from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from .watcher import watch


COLORS = {
    "background": "#161a22",
    "panel": "#202633",
    "text": "#f2f5f9",
    "muted": "#9ca8b8",
    "pending": "#eab308",
    "waiting": "#f59e0b",
    "converting": "#38bdf8",
    "completed": "#34d399",
    "failed": "#fb7185",
    "skipped": "#94a3b8",
}


class ConverterDashboard:
    def __init__(self, roots: list[Path], settle_seconds: float, initial: bool):
        self.roots = roots
        self.settle_seconds = settle_seconds
        self.initial = initial
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.states: dict[str, str] = {}
        self.known_documents: set[str] = set()
        self.activity: deque[str] = deque(maxlen=6)
        self.completed = 0
        self.failed = 0
        self.skipped = 0
        self.total_documents = 0

        self.window = tk.Tk()
        self.window.title("Document Converter")
        self.window.attributes("-topmost", True)
        self.window.geometry("390x420")
        self.window.minsize(350, 330)
        self.window.configure(bg=COLORS["background"])
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._drag_origin: tuple[int, int] | None = None
        self._build()

    def run(self) -> None:
        thread = threading.Thread(
            target=watch,
            args=(self.roots, self.settle_seconds, self.initial),
            kwargs={"event_sink": self.events, "external_stop": self.stop_event},
            daemon=True,
        )
        thread.start()
        self.window.after(100, self._drain_events)
        self.window.mainloop()

    def close(self) -> None:
        self.stop_event.set()
        self.window.destroy()

    def _build(self) -> None:
        header = tk.Frame(self.window, bg=COLORS["background"], padx=18, pady=14)
        header.pack(fill="x")
        header.bind("<ButtonPress-1>", self._start_drag)
        header.bind("<B1-Motion>", self._drag)
        tk.Label(
            header,
            text="Document Converter",
            bg=COLORS["background"],
            fg=COLORS["text"],
            font=("TkDefaultFont", 15, "bold"),
        ).pack(side="left")
        self.health = tk.Label(
            header,
            text="● STARTING",
            bg=COLORS["background"],
            fg=COLORS["pending"],
            font=("TkDefaultFont", 9, "bold"),
        )
        self.health.pack(side="right")

        cards = tk.Frame(self.window, bg=COLORS["background"], padx=14)
        cards.pack(fill="x")
        self.values: dict[str, tk.Label] = {}
        for index, (key, label) in enumerate(
            [
                ("total", "Documents"),
                ("pending", "Pending"),
                ("waiting", "Waiting"),
                ("converting", "Converting"),
                ("completed", "Completed"),
                ("failed", "Failed"),
            ]
        ):
            card = tk.Frame(cards, bg=COLORS["panel"], padx=10, pady=9)
            card.grid(row=index // 3, column=index % 3, padx=3, pady=3, sticky="nsew")
            cards.grid_columnconfigure(index % 3, weight=1)
            value = tk.Label(
                card,
                text="0",
                bg=COLORS["panel"],
                fg=COLORS.get(key, COLORS["text"]),
                font=("TkDefaultFont", 17, "bold"),
            )
            value.pack()
            tk.Label(
                card,
                text=label,
                bg=COLORS["panel"],
                fg=COLORS["muted"],
                font=("TkDefaultFont", 9),
            ).pack()
            self.values[key] = value

        activity_frame = tk.Frame(
            self.window, bg=COLORS["panel"], padx=12, pady=10
        )
        activity_frame.pack(fill="both", expand=True, padx=17, pady=(12, 8))
        tk.Label(
            activity_frame,
            text="RECENT ACTIVITY",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("TkDefaultFont", 9, "bold"),
        ).pack(anchor="w")
        self.activity_label = tk.Label(
            activity_frame,
            text="Waiting for files…",
            justify="left",
            anchor="nw",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("TkFixedFont", 9),
        )
        self.activity_label.pack(fill="both", expand=True, pady=(8, 0))

        footer = tk.Frame(self.window, bg=COLORS["background"], padx=17, pady=8)
        footer.pack(fill="x")
        self.folder_label = tk.Label(
            footer,
            text=f"Watching {len(self.roots)} folder{'s' if len(self.roots) != 1 else ''}",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            anchor="w",
        )
        self.folder_label.pack(side="left")
        ttk.Button(footer, text="Hide", command=self.window.iconify).pack(side="right")

    def _drain_events(self) -> None:
        try:
            while True:
                self._handle_event(self.events.get_nowait())
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(100, self._drain_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        status = event["status"]
        path = event.get("path")
        if status == "inventory":
            self.total_documents = event["total"]
            self.known_documents.update(event.get("paths", []))
        elif status == "watching":
            self.health.configure(text="● WATCHING", fg=COLORS["completed"])
        elif path:
            if path not in self.known_documents and not Path(path).name.startswith("."):
                self.known_documents.add(path)
                self.total_documents += 1
            if status == "queued":
                status = "pending"
            prior = self.states.get(path)
            self.states[path] = status
            if status == "completed" and prior != "completed":
                self.completed += 1
            elif status == "failed" and prior != "failed":
                self.failed += 1
            elif status == "skipped" and prior != "skipped":
                self.skipped += 1
            if status in {"waiting", "converting", "completed", "failed", "skipped"}:
                symbol = {
                    "waiting": "◌",
                    "converting": "↻",
                    "completed": "✓",
                    "failed": "!",
                    "skipped": "–",
                }[status]
                self.activity.appendleft(f"{symbol} {status:<10} {event.get('name', '')}")
            elif event.get("restored"):
                self.activity.appendleft(f"↺ restored    {event.get('name', '')}")
        self._refresh()

    def _refresh(self) -> None:
        counts = {name: 0 for name in ("pending", "waiting", "converting")}
        for status in self.states.values():
            if status in counts:
                counts[status] += 1
        self.values["total"].configure(text=str(self.total_documents))
        self.values["pending"].configure(text=str(counts["pending"]))
        self.values["waiting"].configure(text=str(counts["waiting"]))
        self.values["converting"].configure(text=str(counts["converting"]))
        self.values["completed"].configure(text=str(self.completed))
        self.values["failed"].configure(text=str(self.failed))
        self.activity_label.configure(text="\n".join(self.activity) or "Waiting for files…")

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root - self.window.winfo_x(), event.y_root - self.window.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if self._drag_origin:
            self.window.geometry(
                f"+{event.x_root - self._drag_origin[0]}+{event.y_root - self._drag_origin[1]}"
            )


def run_dashboard(roots: list[Path], settle_seconds: float, initial: bool) -> None:
    ConverterDashboard(roots, settle_seconds, initial).run()


def choose_watch_folder() -> Path | None:
    chooser = tk.Tk()
    chooser.withdraw()
    chooser.attributes("-topmost", True)
    selected = filedialog.askdirectory(title="Choose a folder to watch", mustexist=True)
    chooser.destroy()
    return Path(selected) if selected else None
