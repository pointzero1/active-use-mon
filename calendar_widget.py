"""calendar_widget — standalone translucent always-on-top card.

Expanded (top → bottom): date + EST/CST/MST/PST times, month calendar, weather.
Click it (without dragging) to collapse to just the local time and date; click
again to expand. Double-click to switch between a fully transparent background
(default) and an opaque one. Drag to move; releasing near an edge or corner
nests it there.

Run:  pythonw calendar_widget.py   (independent of the arc widget)
Reuses clock_weather.py for zone math and weather, and widget.py's Win32
work-area helpers so nesting respects the taskbar on HiDPI. Right-click for the
menu (snap positions, refresh weather, quit).
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPalette, QPen, QTextCharFormat
from PyQt6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QGridLayout,
    QLabel,
    QLayout,
    QMenu,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import clock_weather as cw
from widget import _win32_monitor_rects, logical_work_area

STATE_PATH = Path(__file__).parent / "calendar_widget_pos.json"
WEATHER_REFRESH_MS = 15 * 60 * 1000
SNAP_MARGIN = 8        # gap left between a nested widget and the screen edge
SNAP_THRESHOLD = 60    # releasing within this many px of an edge nests the widget
CLICK_SLOP = 4         # press→release movement (px) still counted as a click
BG_OPAQUE = QColor(26, 22, 18, 255)
# "Fully transparent" is painted at alpha 2, not 0: Windows lets mouse clicks fall
# through zero-alpha pixels of a layered window, so alpha 0 would make the card
# un-clickable/un-draggable anywhere except on the text itself.
BG_CLEAR = QColor(0, 0, 0, 2)

SNAP_MENU = [("TL", "Top-left"), ("T", "Top"), ("TR", "Top-right"),
             ("L", "Left"), ("R", "Right"),
             ("BL", "Bottom-left"), ("B", "Bottom"), ("BR", "Bottom-right")]

_STYLE = """
QLabel { color: #ff8a40; background: transparent; }
QLabel#date { color: #ffb070; font-size: 16px; font-weight: bold; }
QLabel#bigtime { color: #ffb070; font-size: 34px; font-weight: bold; }
QLabel#temp { color: #ffb070; font-size: 24px; font-weight: bold; }
QLabel#meta { color: #c8924f; }
QLabel#ztime { color: #ffb070; font-size: 14px; font-weight: bold; }
QCalendarWidget QWidget { background: transparent; color: #ff8a40; }
QCalendarWidget QToolButton { color: #ffb070; font-size: 16px; font-weight: bold; background: rgba(36,28,20,160); border: none; padding: 3px 8px; }
QCalendarWidget QToolButton:hover { background: rgba(70,55,28,200); }
QCalendarWidget QMenu { background: #1a1612; color: #ff8a40; }
QCalendarWidget QSpinBox { background: rgba(36,28,20,200); color: #ffb070; border: none; }
QCalendarWidget QAbstractItemView { background: transparent; color: #ff8a40; outline: 0; }
QCalendarWidget QAbstractItemView:disabled { color: #8a6a45; }
"""


# ── pure helpers (unit-tested) ───────────────────────────────────────────────

def clamp_to_screens(pos: QPoint, size, screens: list[QRect]) -> QPoint:
    """Keep a saved position on-screen: if the top-left isn't inside any screen
    (monitor unplugged / resolution change) fall back near the primary's
    top-left; otherwise nudge so the whole window fits its screen."""
    for g in screens:
        if g.contains(pos):
            x = min(max(pos.x(), g.left()), g.right() - size.width() + 1)
            y = min(max(pos.y(), g.top()), g.bottom() - size.height() + 1)
            return QPoint(x, y)
    g = screens[0]
    return QPoint(g.left() + 40, g.top() + 40)


def detect_anchor(rect: QRect, area: QRect, threshold: int = SNAP_THRESHOLD) -> str:
    """Which edges of ``area`` the window ``rect`` is within ``threshold`` of,
    as a string over "TBLR" ("" = free, "TL" = top-left corner, "T" = top edge)."""
    a = ""
    if rect.top() - area.top() <= threshold:
        a += "T"
    elif area.bottom() - rect.bottom() <= threshold:
        a += "B"
    if rect.left() - area.left() <= threshold:
        a += "L"
    elif area.right() - rect.right() <= threshold:
        a += "R"
    return a


def anchored_pos(anchor: str, current: QPoint, size, area: QRect,
                 margin: int = SNAP_MARGIN, center_free_axis: bool = False) -> QPoint:
    """Top-left for a window nested at ``anchor``. Axes the anchor doesn't pin
    keep their current coordinate (clamped on-screen), or are centred when
    ``center_free_axis`` is set (used by the menu's side snaps)."""
    w, h = size.width(), size.height()
    if "L" in anchor:
        x = area.left() + margin
    elif "R" in anchor:
        x = area.right() - w + 1 - margin
    elif center_free_axis:
        x = area.left() + (area.width() - w) // 2
    else:
        x = current.x()
    if "T" in anchor:
        y = area.top() + margin
    elif "B" in anchor:
        y = area.bottom() - h + 1 - margin
    elif center_free_axis:
        y = area.top() + (area.height() - h) // 2
    else:
        y = current.y()
    x = min(max(x, area.left()), area.right() - w + 1)
    y = min(max(y, area.top()), area.bottom() - h + 1)
    return QPoint(x, y)


def load_state(path: Path = STATE_PATH) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return {"x": int(d["x"]), "y": int(d["y"]),
                "anchor": str(d.get("anchor", "")),
                "expanded": bool(d.get("expanded", True)),
                "opaque": bool(d.get("opaque", False))}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass  # position memory is a nicety


# ── widget ───────────────────────────────────────────────────────────────────

class CalendarWidget(QWidget):
    _weather_ready = pyqtSignal(object)   # worker thread -> UI thread

    def __init__(self, fetcher=None, state_path: Path = STATE_PATH) -> None:
        super().__init__()
        self._fetch = fetcher or cw.fetch_weather
        self._state_path = state_path
        self._weather: dict | None = None
        self._fetching = False
        self._marked = None             # date currently highlighted as "today"
        self.expanded = True
        self.opaque = False             # False = fully transparent background
        self.anchor = ""                # nested edges, "" = free-floating
        self._drag: QPoint | None = None
        self._press: QPoint | None = None
        self._moved = False
        # A click waits out the double-click interval: a second click inside it
        # means "toggle opacity" instead of "expand/collapse".
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._single_click)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_STYLE)

        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)  # window hugs content

        # Collapsed-only: big local time.
        self.bigtime_label = QLabel()
        self.bigtime_label.setObjectName("bigtime")
        self.date_label = QLabel()
        self.date_label.setObjectName("date")
        outer.addWidget(self.bigtime_label)
        outer.addWidget(self.date_label)

        # Top (expanded): the four zone times, under the date.
        self.zones_host = QWidget()
        grid = QGridLayout(self.zones_host)
        grid.setContentsMargins(0, 2, 0, 4)
        self._zone_labels: list[tuple[QLabel, QLabel]] = []
        for col, _zone in enumerate(cw.MAIN_ZONES):
            abbr = QLabel()
            abbr.setObjectName("meta")
            abbr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tm = QLabel()
            tm.setObjectName("ztime")
            tm.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(abbr, 0, col)
            grid.addWidget(tm, 1, col)
            self._zone_labels.append((abbr, tm))
        outer.addWidget(self.zones_host)

        # Middle: month calendar.
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
        self.calendar.setSelectionMode(QCalendarWidget.SelectionMode.NoSelection)
        # Qt's calendar paints its own opaque palette-based backgrounds (stylesheets
        # don't reach them), so make the palette transparent and recolour the text.
        pal = self.calendar.palette()
        clear = QColor(0, 0, 0, 0)
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                     QPalette.ColorRole.AlternateBase, QPalette.ColorRole.Button):
            pal.setColor(role, clear)
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                     QPalette.ColorRole.ButtonText):
            pal.setColor(role, QColor("#ff8a40"))
        self.calendar.setPalette(pal)
        for day in (Qt.DayOfWeek.Monday, Qt.DayOfWeek.Tuesday, Qt.DayOfWeek.Wednesday,
                    Qt.DayOfWeek.Thursday, Qt.DayOfWeek.Friday,
                    Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            fmt = QTextCharFormat()      # header cells: clear bg; weekends dimmer than Qt's red
            fmt.setBackground(QBrush(clear))
            weekend = day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday)
            fmt.setForeground(QBrush(QColor("#c8924f" if weekend else "#ff8a40")))
            self.calendar.setWeekdayTextFormat(day, fmt)
        # The stock arrow icons are dark and vanish on the dark buttons; use text arrows.
        for name, glyph in (("qt_calendar_prevmonth", "‹"), ("qt_calendar_nextmonth", "›")):
            btn = self.calendar.findChild(QToolButton, name)
            if btn is not None:
                btn.setIcon(QIcon())
                btn.setText(glyph)
        self.calendar.setMinimumWidth(290)
        outer.addWidget(self.calendar)
        # The date grid would swallow mouse presses; route them to the drag/click logic.
        for view in self.calendar.findChildren(QTableView):
            view.viewport().installEventFilter(self)
            view.viewport().setAutoFillBackground(False)

        # Bottom: weather.
        self.weather_host = QWidget()
        wl = QVBoxLayout(self.weather_host)
        wl.setContentsMargins(0, 4, 0, 0)
        self.temp_label = QLabel("…")
        self.temp_label.setObjectName("temp")
        self.cond_label = QLabel("Loading weather…")
        self.loc_label = QLabel("")
        self.loc_label.setObjectName("meta")
        for w in (self.temp_label, self.cond_label, self.loc_label):
            wl.addWidget(w)
        outer.addWidget(self.weather_host)

        self._weather_ready.connect(self._on_weather)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self.refresh_clocks)
        self._clock.start(1000)
        self._wx_timer = QTimer(self)
        self._wx_timer.timeout.connect(self.start_fetch)
        self._wx_timer.start(WEATHER_REFRESH_MS)

        self._apply_mode()
        self.refresh_clocks()

    # ── painting (translucent rounded backdrop) ───────────────────────────

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(BG_OPAQUE if self.opaque else BG_CLEAR)
        p.setPen(QPen(QColor(255, 138, 64, 70), 1) if self.opaque else Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

    # ── content ───────────────────────────────────────────────────────────

    def refresh_clocks(self, now_utc: datetime | None = None) -> None:
        now = now_utc or datetime.now(timezone.utc)
        local = now.astimezone()
        self.date_label.setText(cw.format_date(local) if self.expanded
                                else cw.format_date_short(local))
        self.bigtime_label.setText(cw._fmt_time(local))
        today = local.date()
        if self._marked != today:
            # First paint / midnight rollover: move the highlight and the month.
            if self._marked is not None:
                self.calendar.setDateTextFormat(self._marked, QTextCharFormat())
            fmt = QTextCharFormat()
            fmt.setBackground(QBrush(QColor("#ff8a40")))
            fmt.setForeground(QBrush(QColor("#1a1612")))
            fmt.setFontWeight(700)
            self.calendar.setDateTextFormat(today, fmt)
            self.calendar.setCurrentPage(today.year, today.month)
            self._marked = today
        for (abbr, tm), row in zip(self._zone_labels, cw.us_zone_times(now, cw.MAIN_ZONES)):
            abbr.setText(row["abbr"])
            tm.setText(row["time"])

    def start_fetch(self) -> None:
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

    # ── expand / collapse ─────────────────────────────────────────────────

    def _apply_mode(self) -> None:
        self.bigtime_label.setVisible(not self.expanded)
        # Collapsed: the date matches the time's size; expanded: back to the header size.
        self.date_label.setObjectName("date" if self.expanded else "bigtime")
        self.date_label.style().unpolish(self.date_label)
        self.date_label.style().polish(self.date_label)
        for w in (self.zones_host, self.calendar, self.weather_host):
            w.setVisible(self.expanded)

    def toggle_opaque(self) -> None:
        self.opaque = not self.opaque
        self.update()
        self._save()

    def _single_click(self) -> None:
        self.toggle_expanded()

    def toggle_expanded(self) -> None:
        self.expanded = not self.expanded
        self._apply_mode()
        self.refresh_clocks()      # date format differs between modes
        self.layout().activate()   # settle the new size now so re-anchoring uses it
        self.adjustSize()
        self._reanchor()
        self._save()

    # ── placement ─────────────────────────────────────────────────────────

    def _work_area(self) -> QRect:
        """Logical work area of this window's screen (taskbar-aware; HiDPI-safe)."""
        screen = self.screen()
        try:
            hwnd = int(self.winId())
        except Exception:
            hwnd = 0
        rects = _win32_monitor_rects(hwnd)
        if rects is None:
            return screen.availableGeometry()
        mon_phys, work_phys = rects
        return logical_work_area(screen.geometry(), mon_phys, work_phys,
                                 screen.devicePixelRatio())

    def _reanchor(self, center_free_axis: bool = False) -> None:
        area = self._work_area()
        self.move(anchored_pos(self.anchor, self.pos(), self.size(), area,
                               center_free_axis=center_free_axis))

    def snap_to(self, anchor: str) -> None:
        self.anchor = anchor
        self._reanchor(center_free_axis=True)
        self._save()

    def place(self) -> None:
        """Restore the saved state (clamped on-screen), else near the top-left."""
        st = load_state(self._state_path)
        if st is not None:
            self.expanded = st["expanded"]
            self.opaque = st["opaque"]
            self._apply_mode()
        self.adjustSize()
        screens = [s.availableGeometry() for s in QApplication.screens()]
        if st is None:
            g = screens[0]
            self.move(QPoint(g.left() + 40, g.top() + 40))
            return
        self.anchor = st["anchor"]
        self.move(clamp_to_screens(QPoint(st["x"], st["y"]), self.size(), screens))
        if self.anchor:
            self._reanchor()

    def _save(self) -> None:
        save_state({"x": self.x(), "y": self.y(),
                    "anchor": self.anchor, "expanded": self.expanded,
                    "opaque": self.opaque}, self._state_path)

    # ── mouse: drag to move, click to toggle ──────────────────────────────

    def _mouse_press(self, global_pt: QPoint) -> None:
        self._press = global_pt
        self._moved = False
        self._drag = global_pt - self.frameGeometry().topLeft()

    def _mouse_move(self, global_pt: QPoint) -> None:
        if self._drag is None or self._press is None:
            return
        if (global_pt - self._press).manhattanLength() > CLICK_SLOP:
            self._moved = True
        if self._moved:
            self.move(global_pt - self._drag)

    def _mouse_release(self) -> None:
        if self._drag is None:
            return
        moved, self._drag, self._press = self._moved, None, None
        if not moved:
            if self._click_timer.isActive():     # second click in time → double-click
                self._click_timer.stop()
                self.toggle_opaque()
            else:
                self._click_timer.start(QApplication.doubleClickInterval())
            return
        self._click_timer.stop()
        self.anchor = detect_anchor(self.frameGeometry(), self._work_area())
        self._reanchor()
        self._save()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._mouse_press(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._mouse_move(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._mouse_release()

    def eventFilter(self, obj, e) -> bool:  # noqa: N802
        t = e.type()
        if t == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
            self._mouse_press(e.globalPosition().toPoint())
            return True
        if t == QEvent.Type.MouseMove and e.buttons() & Qt.MouseButton.LeftButton:
            self._mouse_move(e.globalPosition().toPoint())
            return True
        if t == QEvent.Type.MouseButtonRelease and e.button() == Qt.MouseButton.LeftButton:
            self._mouse_release()
            return True
        return super().eventFilter(obj, e)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #1a1612; color: #ff8a40; border: 1px solid #46371c; }"
            "QMenu::item:selected { background-color: #46371c; color: #ffb070; }")
        for anchor, label in SNAP_MENU:
            act = QAction(f"Snap → {label}", menu)
            act.triggered.connect(lambda _=False, a=anchor: self.snap_to(a))
            menu.addAction(act)
        menu.addSeparator()
        bg_act = QAction("Transparent background" if self.opaque else "Opaque background", menu)
        bg_act.triggered.connect(self.toggle_opaque)
        menu.addAction(bg_act)
        refresh = QAction("Refresh weather", menu)
        refresh.triggered.connect(self.start_fetch)
        menu.addAction(refresh)
        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_act)
        menu.exec(e.globalPos())


def main() -> int:
    app = QApplication(sys.argv)
    w = CalendarWidget()
    w.place()
    w.show()
    w.start_fetch()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
