"""active-use-mon — arc active-time widget.

Quarter-circle in screen corners, half-circle on screen edges.
Snaps to seven positions; click-through outside the arc shape.

Visual:
- 8 concentric bands fill from centre outward — one per completed hour
- Minutes fan clockwise across the current (innermost unfilled) band
- Active time in words curves along the outer text ring
- Dim / bright reflects idle vs. active input state
"""
from __future__ import annotations

import math
import sys

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygon,
    QRadialGradient,
    QRegion,
)
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from activity_tracker import ActivityTracker
from projects_panel import ProjectsPanel

POLL_MS  = 1_000
MAX_HOURS = 8
SIZE     = 150          # corner widget side-length / corner arc radius
EDGE_R   = 140          # half-circle radius for edge positions (T/B/L/R)
EDGE_D   = EDGE_R * 2  # wide dimension of edge widgets

TEXT_FRAC    = 0.22             # fraction of radius used by the outer text ring
BAND_R_FRAC  = 1.0 - TEXT_FRAC # bands live from 0 → this fraction of radius

NEON     = QColor(255, 110, 40)
NEON_DIM = QColor(80,  35,  10)

_PI = math.pi

SNAP_POSITIONS = [
    ("TL", "Top-left"),    ("T", "Top-center"),    ("TR", "Top-right"),
    ("L",  "Left"),        ("C", "Center"),         ("R",  "Right"),
    ("BL", "Bottom-left"), ("B", "Bottom-center"),  ("BR", "Bottom-right"),
]

MENU_STYLE = (
    "QMenu { background-color: #1a1612; color: #ff8a40; "
    "border: 1px solid #46371c; padding: 4px; }"
    "QMenu::item { padding: 4px 16px; }"
    "QMenu::item:selected { background-color: #46371c; color: #ffb070; }"
)

# cx, cy  – arc centre in widget-local coordinates
# start   – arc start angle (screen radians: 0 = east, positive = clockwise)
# end     – arc end angle (always > start)
# w, h    – widget pixel dimensions
# r       – arc radius
POSITION_GEOMETRY: dict[str, dict] = {
    # flip=True  → text sweeps CCW with rotation-90 so chars read upright from below
    # flip=False → text sweeps CW  with rotation+90 so chars read upright from above
    "TL": dict(cx=0,      cy=0,      start=0.0,      end=_PI/2,     w=SIZE,   h=SIZE,   r=SIZE,   flip=True),
    "TR": dict(cx=SIZE,   cy=0,      start=_PI/2,    end=_PI,       w=SIZE,   h=SIZE,   r=SIZE,   flip=True),
    "BL": dict(cx=0,      cy=SIZE,   start=3*_PI/2,  end=2*_PI,     w=SIZE,   h=SIZE,   r=SIZE,   flip=False),
    "BR": dict(cx=SIZE,   cy=SIZE,   start=_PI,      end=3*_PI/2,   w=SIZE,   h=SIZE,   r=SIZE,   flip=False),
    "T":  dict(cx=EDGE_R, cy=0,      start=0.0,      end=_PI,       w=EDGE_D, h=EDGE_R, r=EDGE_R, flip=True),
    "B":  dict(cx=EDGE_R, cy=EDGE_R, start=_PI,      end=2*_PI,     w=EDGE_D, h=EDGE_R, r=EDGE_R, flip=False),
    "L":  dict(cx=0,      cy=EDGE_R, start=-_PI/2,   end=_PI/2,     w=EDGE_R, h=EDGE_D, r=EDGE_R, flip=False),
    "R":  dict(cx=EDGE_R, cy=EDGE_R, start=_PI/2,    end=3*_PI/2,   w=EDGE_R, h=EDGE_D, r=EDGE_R, flip=False),
    "C":  dict(cx=EDGE_R, cy=0,      start=0.0,      end=_PI,       w=EDGE_D, h=EDGE_R, r=EDGE_R, flip=True),
}

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty"]


def _n2w(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] if n % 10 == 0 else f"{_TENS[n // 10]}-{_ONES[n % 10]}"


def _time_label(total_seconds: int) -> str:
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    hw = _n2w(h) + (" hour" if h == 1 else " hours")
    mw = _n2w(m) + (" minute" if m == 1 else " minutes")
    if h == 0:
        return mw
    if m == 0:
        return hw
    return f"{hw}  {mw}"


def _arc_sector(cx: float, cy: float, r1: float, r2: float,
                a0: float, a1: float, n: int = 64) -> QPainterPath:
    """Annular sector (pie slice when r1 == 0).  Screen-convention angles."""
    path = QPainterPath()
    da = (a1 - a0) / n

    if r1 <= 0:
        path.moveTo(cx, cy)
        path.lineTo(cx + r2 * math.cos(a0), cy + r2 * math.sin(a0))
    else:
        path.moveTo(cx + r1 * math.cos(a0), cy + r1 * math.sin(a0))
        path.lineTo(cx + r2 * math.cos(a0), cy + r2 * math.sin(a0))

    for i in range(1, n + 1):
        a = a0 + i * da
        path.lineTo(cx + r2 * math.cos(a), cy + r2 * math.sin(a))

    if r1 <= 0:
        path.lineTo(cx, cy)
    else:
        for i in range(n, -1, -1):
            a = a0 + i * da
            path.lineTo(cx + r1 * math.cos(a), cy + r1 * math.sin(a))

    path.closeSubpath()
    return path


def _draw_arc_text(painter: QPainter, text: str,
                   cx: float, cy: float, text_r: float,
                   start: float, span: float,
                   font_sz: int, color: QColor,
                   flip: bool = False) -> None:
    """Render text curved along an arc at radius text_r, centred in the span.

    flip=False (BL/BR/B): chars sweep CW, tops face outward — readable from above.
    flip=True  (TL/TR/T): chars sweep CCW, tops face inward — readable from below.
    """
    font = QFont("Segoe UI", font_sz)
    fm   = QFontMetricsF(font)
    painter.setFont(font)

    widths    = [fm.horizontalAdvance(ch) for ch in text]
    total_w   = sum(widths)
    text_span = total_w / text_r
    baseline  = (fm.ascent() - fm.descent()) / 2

    if flip:
        # Start from the far (end) side, advance toward start — CCW sweep.
        # rotation = angle - 90° keeps char tops pointing upward (screen-north).
        angle = start + (span + text_span) / 2
        for ch, cw in zip(text, widths):
            mid_a = angle - cw / (2 * text_r)
            px = cx + text_r * math.cos(mid_a)
            py = cy + text_r * math.sin(mid_a)
            painter.save()
            painter.translate(px, py)
            painter.rotate(math.degrees(mid_a) - 90)
            ch_path = QPainterPath()
            ch_path.addText(-cw / 2, baseline, font, ch)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(ch_path)
            painter.restore()
            angle -= cw / text_r
    else:
        # Normal CW sweep: rotation = angle + 90°, tops face outward.
        angle = start + (span - text_span) / 2
        for ch, cw in zip(text, widths):
            mid_a = angle + cw / (2 * text_r)
            px = cx + text_r * math.cos(mid_a)
            py = cy + text_r * math.sin(mid_a)
            painter.save()
            painter.translate(px, py)
            painter.rotate(math.degrees(mid_a) + 90)
            ch_path = QPainterPath()
            ch_path.addText(-cw / 2, baseline, font, ch)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(ch_path)
            painter.restore()
            angle += cw / text_r


class ArcWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.position       = "TR"
        self._seconds: int  = 0
        self._dim: bool     = False
        self._light_mode    = False
        self._drag_pos: QPoint | None = None
        self.on_double_click = None  # set by main(): callback to toggle panel

        self._tracker = ActivityTracker()
        self._apply_geometry()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(POLL_MS)

    # ── geometry ──────────────────────────────────────────────────────────

    def _apply_geometry(self) -> None:
        g = POSITION_GEOMETRY[self.position]
        self.setFixedSize(g["w"], g["h"])
        self._update_mask()

    def _update_mask(self) -> None:
        g  = POSITION_GEOMETRY[self.position]
        cx, cy, r = g["cx"], g["cy"], g["r"]
        start, end = g["start"], g["end"]
        n  = 120
        pts = [QPoint(int(cx), int(cy))]
        for i in range(n + 1):
            a = start + (end - start) * i / n
            pts.append(QPoint(int(cx + r * math.cos(a)), int(cy + r * math.sin(a))))
        self.setMask(QRegion(QPolygon(pts)))

    def _target_topleft(self, pos_id: str) -> tuple[int, int]:
        scr = self.screen().availableGeometry()
        cx  = scr.center().x()
        cy  = scr.center().y()
        return {
            "TL": (scr.left(),                   scr.top()),
            "TR": (scr.right()  - SIZE   + 1,    scr.top()),
            "BL": (scr.left(),                   scr.bottom() - SIZE   + 1),
            "BR": (scr.right()  - SIZE   + 1,    scr.bottom() - SIZE   + 1),
            "T":  (cx - EDGE_R,                  scr.top()),
            "B":  (cx - EDGE_R,                  scr.bottom() - EDGE_R + 1),
            "L":  (scr.left(),                   cy - EDGE_R),
            "R":  (scr.right()  - EDGE_R + 1,    cy - EDGE_R),
            "C":  (cx - EDGE_R,                  cy - EDGE_R // 2),
        }[pos_id]

    # ── timer ─────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._tracker.tick()
        s, d = self._tracker.active_seconds, self._tracker.is_idle
        if s != self._seconds or d != self._dim:
            self._seconds, self._dim = s, d
            self.update()

    # ── input events ──────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        if self._drag_pos is None:
            return
        self._drag_pos = None
        self._snap_to_nearest()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.on_double_click:
            self.on_double_click()
            event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        if self.on_double_click:
            projects_act = QAction("Show / hide projects", menu)
            projects_act.triggered.connect(self.on_double_click)
            menu.addAction(projects_act)
            menu.addSeparator()
        for pos_id, label in SNAP_POSITIONS:
            act = QAction(f"Snap → {label}", menu)
            act.triggered.connect(lambda _=False, c=pos_id: self.snap_to(c))
            menu.addAction(act)
        menu.addSeparator()
        theme_act = QAction("Dark mode" if self._light_mode else "Light mode", menu)
        theme_act.triggered.connect(self._toggle_theme)
        menu.addAction(theme_act)
        menu.addSeparator()
        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self._quit_app)
        menu.addAction(quit_act)
        menu.exec(event.globalPos())

    def _snap_to_nearest(self) -> None:
        center = self.frameGeometry().center()
        def dist2(pos_id: str) -> float:
            x, y = self._target_topleft(pos_id)
            g = POSITION_GEOMETRY[pos_id]
            return (x + g["w"] // 2 - center.x()) ** 2 + (y + g["h"] // 2 - center.y()) ** 2
        self.snap_to(min(POSITION_GEOMETRY, key=dist2))

    def snap_to(self, pos_id: str) -> None:
        self.position = pos_id
        x, y = self._target_topleft(pos_id)
        self._apply_geometry()
        self.move(x, y)
        self.update()

    # ── theme ─────────────────────────────────────────────────────────────

    def _toggle_theme(self) -> None:
        self._light_mode = not self._light_mode
        self.update()

    def _quit_app(self) -> None:
        self.stop()
        QApplication.instance().quit()

    # ── paint ─────────────────────────────────────────────────────────────

    def _neon(self, alpha: int) -> QColor:
        c = QColor(NEON_DIM if self._dim else NEON)
        c.setAlpha(int(alpha * (0.4 if self._dim else 1.0)))
        return c

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        g  = POSITION_GEOMETRY[self.position]
        cx, cy   = float(g["cx"]), float(g["cy"])
        start, end, r = g["start"], g["end"], float(g["r"])
        span = end - start

        band_max_r = r * BAND_R_FRAC
        band_w     = band_max_r / MAX_HOURS
        text_r     = r * (1.0 - TEXT_FRAC * 0.5)
        font_sz    = max(7, int(r * TEXT_FRAC * 0.40))

        hours_done = int(min(self._seconds // 3600, MAX_HOURS))
        min_frac   = ((self._seconds // 60) % 60) / 60.0

        # Background
        grad = QRadialGradient(cx, cy, r)
        if self._light_mode:
            grad.setColorAt(0.0, QColor(240, 220, 200, 110))
            grad.setColorAt(1.0, QColor(200, 180, 160, 65))
        else:
            grad.setColorAt(0.0, QColor(28, 20, 18, 110))
            grad.setColorAt(1.0, QColor(10,  7,  6,  60))
        p.fillPath(_arc_sector(cx, cy, 0, r, start, end), grad)

        # Hour bands (inside-out: band 0 = innermost = first hour)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(MAX_HOURS):
            r1 = i * band_w
            r2 = (i + 1) * band_w

            if i < hours_done:
                p.setBrush(self._neon(215))
                p.drawPath(_arc_sector(cx, cy, r1, r2, start, end))
                # separator line at outer edge of completed band
                sep = QPainterPath()
                sep.moveTo(cx + r2 * math.cos(start), cy + r2 * math.sin(start))
                for j in range(1, 33):
                    a = start + span * j / 32
                    sep.lineTo(cx + r2 * math.cos(a), cy + r2 * math.sin(a))
                p.setPen(QPen(QColor(0, 0, 0, 45 if not self._dim else 22), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(sep)
                p.setPen(Qt.PenStyle.NoPen)

            elif i == hours_done:
                # Dim background of the current band
                ghost = QColor(NEON)
                ghost.setAlpha(15 if not self._dim else 7)
                p.setBrush(ghost)
                p.drawPath(_arc_sector(cx, cy, r1, r2, start, end))

                # Minute sweep
                if min_frac > 0:
                    sweep_end = start + span * min_frac
                    p.setBrush(self._neon(165))
                    p.drawPath(_arc_sector(cx, cy, r1, r2, start, sweep_end))

                # Outline of current band outer edge
                outline_c = QColor(NEON)
                outline_c.setAlpha(55 if not self._dim else 22)
                arc_line = QPainterPath()
                arc_line.moveTo(cx + r2 * math.cos(start), cy + r2 * math.sin(start))
                for j in range(1, 65):
                    a = start + span * j / 64
                    arc_line.lineTo(cx + r2 * math.cos(a), cy + r2 * math.sin(a))
                p.setPen(QPen(outline_c, 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(arc_line)
                p.setPen(Qt.PenStyle.NoPen)

            else:
                # Future band — faint outline only
                faint = QColor(NEON)
                faint.setAlpha(18 if not self._dim else 7)
                p.setPen(QPen(faint, 0.8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(_arc_sector(cx, cy, r1, r2, start, end))
                p.setPen(Qt.PenStyle.NoPen)

        # Text ring separator arc
        sep_c = QColor(NEON)
        sep_c.setAlpha(50 if not self._dim else 20)
        sep_arc = QPainterPath()
        sep_arc.moveTo(cx + band_max_r * math.cos(start), cy + band_max_r * math.sin(start))
        for j in range(1, 65):
            a = start + span * j / 64
            sep_arc.lineTo(cx + band_max_r * math.cos(a), cy + band_max_r * math.sin(a))
        p.setPen(QPen(sep_c, 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(sep_arc)

        # Radial edge lines
        edge_c = QColor(NEON)
        edge_c.setAlpha(65 if not self._dim else 25)
        p.setPen(QPen(edge_c, 0.8))
        p.drawLine(int(cx), int(cy),
                   int(cx + r * math.cos(start)), int(cy + r * math.sin(start)))
        p.drawLine(int(cx), int(cy),
                   int(cx + r * math.cos(end)),   int(cy + r * math.sin(end)))

        # Word text (curved for arc positions; straight-rotated for L/R)
        label = _time_label(self._seconds)
        alpha = 0.68 if not self._dim else 0.30
        if self._light_mode:
            txt_c = QColor(45, 25, 8, int(220 * alpha))
        else:
            txt_c = QColor(255, 205, 155, int(215 * alpha))
        _draw_arc_text(p, label, cx, cy, text_r, start, span, font_sz, txt_c,
                       flip=g["flip"])

    # ── lifecycle ─────────────────────────────────────────────────────────

    def stop(self) -> None:
        self._tracker.stop()


# ── tray icon ─────────────────────────────────────────────────────────────

def _make_tray_icon() -> QIcon:
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(NEON)
    p.setPen(Qt.PenStyle.NoPen)
    path = QPainterPath()
    cx, cy, r = 28.0, 4.0, 26.0
    path.moveTo(cx, cy)
    for i in range(33):
        a = _PI / 2 + _PI / 2 * i / 32
        path.lineTo(cx + r * math.cos(a), cy + r * math.sin(a))
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pix)


# ── main ──────────────────────────────────────────────────────────────────

def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    widget = ArcWidget()
    widget.snap_to("TR")
    widget.show()

    panel = ProjectsPanel()
    widget.on_double_click = panel.toggle

    tray = QSystemTrayIcon(_make_tray_icon())
    tray.setToolTip("active-use-mon — active time")

    menu = QMenu()
    menu.setStyleSheet(MENU_STYLE)

    projects_action = QAction("Show / hide projects", menu)
    projects_action.triggered.connect(panel.toggle)
    menu.addAction(projects_action)
    menu.addSeparator()

    for pos_id, label in SNAP_POSITIONS:
        act = QAction(f"Snap → {label}", menu)
        act.triggered.connect(lambda _checked=False, c=pos_id: widget.snap_to(c))
        menu.addAction(act)
    menu.addSeparator()

    theme_act = QAction("Light mode", menu)
    def _toggle_tray() -> None:
        widget._toggle_theme()
        theme_act.setText("Dark mode" if widget._light_mode else "Light mode")
    theme_act.triggered.connect(_toggle_tray)
    menu.addAction(theme_act)
    menu.addSeparator()

    quit_act = QAction("Quit", menu)
    def _quit() -> None:
        panel.close()
        widget.stop()
        app.quit()
    quit_act.triggered.connect(_quit)
    menu.addAction(quit_act)

    tray.setContextMenu(menu)
    tray.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
