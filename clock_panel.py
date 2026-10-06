"""ClockPanel: hidden-by-default panel with the date, current weather and the
time in every US zone. Styled to match ProjectsPanel (neon-amber palette).

Clocks tick once a second, but only while the panel is visible. Weather is
fetched on a worker thread (open + every 15 min) so the UI never blocks.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

import clock_weather as cw

WEATHER_REFRESH_S = 15 * 60

_STYLE = """
QWidget#ClockPanel { background-color: #1a1612; border: 1px solid #46371c; }
QLabel { color: #ff8a40; }
QLabel#date { color: #ffb070; font-size: 15px; font-weight: bold; }
QLabel#temp { color: #ffb070; font-size: 26px; font-weight: bold; }
QLabel#meta { color: #b87a3c; }
QLabel#zone { color: #ff8a40; }
QLabel#zonehome { color: #ffb070; font-weight: bold; }
QLabel#ztime { color: #ffb070; font-size: 15px; }
"""


class ClockPanel(QWidget):
    _weather_ready = pyqtSignal(object)   # worker thread -> UI thread

    def __init__(self, fetcher: Callable[[], dict | None] | None = None) -> None:
        super().__init__()
        self._fetch = fetcher or cw.fetch_weather
        self._weather: dict | None = None
        self._fetched_at = 0.0
        self._fetching = False

        self.setObjectName("ClockPanel")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet(_STYLE)
        self.setFixedWidth(300)

        outer = QVBoxLayout(self)
        self.date_label = QLabel()
        self.date_label.setObjectName("date")
        self.temp_label = QLabel("…")
        self.temp_label.setObjectName("temp")
        self.cond_label = QLabel("Loading weather…")
        self.loc_label = QLabel("")
        self.loc_label.setObjectName("meta")
        outer.addWidget(self.date_label)
        outer.addWidget(self.temp_label)
        outer.addWidget(self.cond_label)
        outer.addWidget(self.loc_label)

        grid_host = QWidget()
        self._grid = QGridLayout(grid_host)
        self._grid.setContentsMargins(0, 8, 0, 0)
        self._zone_labels: list[tuple[QLabel, QLabel, QLabel]] = []
        for i in range(len(cw.US_ZONES)):
            row = (QLabel(), QLabel(), QLabel())
            row[0].setObjectName("zone")
            row[1].setObjectName("meta")
            row[2].setObjectName("ztime")
            for col, w in enumerate(row):
                self._grid.addWidget(w, i, col)
            self._zone_labels.append(row)
        self._grid.setColumnStretch(0, 1)
        outer.addWidget(grid_host)

        self._weather_ready.connect(self._on_weather)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self.refresh_clocks)
        self._weather_check = QTimer(self)   # re-checks staleness while visible
        self._weather_check.timeout.connect(self._maybe_refresh_weather)

        self.refresh_clocks()
        self.hide()

    # ── clocks ────────────────────────────────────────────────────────────

    def refresh_clocks(self, now_utc: datetime | None = None) -> None:
        now = now_utc or datetime.now(timezone.utc)
        local = now.astimezone()
        self.date_label.setText(cw.format_date(local))
        home_tz = (self._weather or {}).get("location", {}).get("tz")
        # Match on current UTC offset so e.g. America/Indiana/Indianapolis
        # highlights the Eastern row.
        home_off = now.astimezone(ZoneInfo(home_tz)).utcoffset() if home_tz else None
        for (name, abbr, tm), row in zip(self._zone_labels, cw.us_zone_times(now)):
            name.setText(row["label"])
            abbr.setText(row["abbr"])
            tm.setText(row["time"])
            is_home = home_off is not None and now.astimezone(ZoneInfo(row["tz"])).utcoffset() == home_off
            name.setObjectName("zonehome" if is_home else "zone")
            name.setStyle(name.style())   # re-polish after objectName change

    # ── weather ───────────────────────────────────────────────────────────

    def _start_fetch(self) -> None:
        if self._fetching:
            return
        self._fetching = True

        def work() -> None:
            try:
                result = self._fetch()
            except Exception:  # noqa: BLE001 - never kill the worker silently
                result = None
            self._weather_ready.emit(result)

        threading.Thread(target=work, daemon=True).start()

    def _on_weather(self, result: dict | None) -> None:
        self._fetching = False
        self._fetched_at = time.monotonic()
        if result is None:
            if self._weather is None:
                self.cond_label.setText("Weather unavailable")
            return
        self.render_weather(result)

    def render_weather(self, result: dict) -> None:
        self._weather = result
        w, loc = result["weather"], result["location"]
        self.temp_label.setText(f"{w['temp_f']}°F")
        self.cond_label.setText(f"{w['condition']}  ·  wind {w['wind_mph']} mph")
        self.loc_label.setText(loc["name"] + ("  ·  stale" if result.get("stale") else ""))
        self.refresh_clocks()

    def _maybe_refresh_weather(self) -> None:
        if time.monotonic() - self._fetched_at >= WEATHER_REFRESH_S or self._weather is None:
            self._start_fetch()

    # ── visibility ────────────────────────────────────────────────────────

    def open_panel(self) -> None:
        self.refresh_clocks()
        self._clock.start(1000)
        self._maybe_refresh_weather()
        self.show()
        self.raise_()
        self.activateWindow()
        self._weather_check.start(60_000)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._clock.stop()
        self._weather_check.stop()
        super().hideEvent(event)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.open_panel()
