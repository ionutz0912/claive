#!/usr/bin/env python3
"""claive/lib/mesh.py — EventMesh: filesystem event-driven agent communication.

Replaces sleep-based polling with watchdog filesystem events.
Falls back to 2-second polling if watchdog is not installed.

Phase 3 implementation.
"""

import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLAIVE_ROOT = os.path.dirname(SCRIPT_DIR)
MESH_DIR = os.path.join(CLAIVE_ROOT, ".claive", os.environ.get("CLAIVE_SESSION", "claive"))

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


class EventMesh:
    """Watches .claive/outbox/ and .claive/signals/ for agent events."""

    def __init__(self, claive_dir=None):
        self.claive_dir = claive_dir or MESH_DIR
        self.callbacks = {"status": {}, "done": {}, "any": []}
        self._observer = None

    def on_status(self, agent, callback):
        """Register callback for agent status changes."""
        self.callbacks["status"][agent] = callback

    def on_done(self, agent, callback):
        """Register callback for agent completion."""
        self.callbacks["done"][agent] = callback

    def on_any(self, callback):
        """Register callback for any event."""
        self.callbacks["any"].append(callback)

    def start(self):
        """Start watching for events."""
        outbox = os.path.join(self.claive_dir, "outbox")
        signals = os.path.join(self.claive_dir, "signals")
        os.makedirs(outbox, exist_ok=True)
        os.makedirs(signals, exist_ok=True)

        if HAS_WATCHDOG:
            self._start_watchdog(outbox, signals)
        else:
            print("[mesh] watchdog not installed, using 2s polling fallback")
            print("[mesh] Install with: pip install watchdog")
            self._start_polling(outbox, signals)

    def stop(self):
        """Stop watching."""
        if self._observer:
            self._observer.stop()
            self._observer.join()

    def _start_watchdog(self, outbox, signals):
        """Start watchdog-based event watching."""
        handler = _MeshHandler(self.callbacks, self.claive_dir)
        self._observer = Observer()
        self._observer.schedule(handler, outbox, recursive=True)
        self._observer.schedule(handler, signals, recursive=False)
        self._observer.start()
        print(f"[mesh] Watching {outbox} and {signals} (watchdog)")

    def _start_polling(self, outbox, signals):
        """Fallback: poll for .done signal files every 2 seconds."""
        known_signals = set()
        try:
            while True:
                for f in os.listdir(signals):
                    if f.endswith(".done") and f not in known_signals:
                        known_signals.add(f)
                        agent = f.replace(".done", "")
                        if agent in self.callbacks["done"]:
                            self.callbacks["done"][agent](agent)
                        for cb in self.callbacks["any"]:
                            cb("done", agent)
                time.sleep(2)
        except KeyboardInterrupt:
            pass


if HAS_WATCHDOG:
    class _MeshHandler(FileSystemEventHandler):
        """Handles filesystem events from watchdog."""

        def __init__(self, callbacks, claive_dir):
            self.callbacks = callbacks
            self.claive_dir = claive_dir

        def on_created(self, event):
            self._handle(event)

        def on_modified(self, event):
            self._handle(event)

        def _handle(self, event):
            if event.is_directory:
                return

            path = event.src_path
            signals_dir = os.path.join(self.claive_dir, "signals")
            outbox_dir = os.path.join(self.claive_dir, "outbox")

            # Check for completion signals
            if path.startswith(signals_dir) and path.endswith(".done"):
                agent = os.path.basename(path).replace(".done", "")
                if agent in self.callbacks["done"]:
                    self.callbacks["done"][agent](agent)
                for cb in self.callbacks["any"]:
                    cb("done", agent)

            # Check for status updates
            elif path.startswith(outbox_dir) and path.endswith("status.json"):
                parts = Path(path).relative_to(outbox_dir).parts
                if parts:
                    agent = parts[0]
                    if agent in self.callbacks["status"]:
                        self.callbacks["status"][agent](agent)
                    for cb in self.callbacks["any"]:
                        cb("status", agent)


if __name__ == "__main__":
    mesh = EventMesh()

    def on_event(event_type, agent):
        print(f"[mesh] {event_type}: {agent}")

    mesh.on_any(on_event)
    print("[mesh] Starting EventMesh watcher... (Ctrl+C to stop)")
    mesh.start()

    if HAS_WATCHDOG:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            mesh.stop()
            print("\n[mesh] Stopped.")
