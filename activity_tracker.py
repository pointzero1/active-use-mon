"""Tracks active usage time using global mouse/keyboard listeners.

The timer increments only while input has occurred within IDLE_THRESHOLD_SECONDS.
Persists today's active seconds to a JSON file so the count survives restarts.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path

from pynput import keyboard, mouse

IDLE_THRESHOLD_SECONDS = 60
STATE_FILE = Path(__file__).parent / "active_time.json"


class ActivityTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_input_ts = time.monotonic()
        self._active_seconds = 0.0
        self._last_tick = time.monotonic()
        self._today = date.today().isoformat()
        self._load()

        self._mouse_listener = mouse.Listener(
            on_move=self._on_input,
            on_click=self._on_input,
            on_scroll=self._on_input,
        )
        self._kb_listener = keyboard.Listener(on_press=self._on_input)
        self._mouse_listener.daemon = True
        self._kb_listener.daemon = True
        self._mouse_listener.start()
        self._kb_listener.start()

    def _on_input(self, *_args, **_kwargs) -> None:
        with self._lock:
            self._last_input_ts = time.monotonic()

    def tick(self) -> None:
        """Call from the UI timer. Adds elapsed time when not idle."""
        now = time.monotonic()
        with self._lock:
            elapsed = now - self._last_tick
            self._last_tick = now
            idle_for = now - self._last_input_ts
            today = date.today().isoformat()
            if today != self._today:
                self._today = today
                self._active_seconds = 0.0
            if idle_for <= IDLE_THRESHOLD_SECONDS:
                self._active_seconds += elapsed
            self._save()

    @property
    def active_seconds(self) -> int:
        with self._lock:
            return int(self._active_seconds)

    @property
    def is_idle(self) -> bool:
        with self._lock:
            return (time.monotonic() - self._last_input_ts) > IDLE_THRESHOLD_SECONDS

    def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
            if data.get("date") == self._today:
                self._active_seconds = float(data.get("seconds", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            STATE_FILE.write_text(
                json.dumps({"date": self._today, "seconds": self._active_seconds})
            )
        except OSError:
            pass

    def stop(self) -> None:
        self._mouse_listener.stop()
        self._kb_listener.stop()


def format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}"
