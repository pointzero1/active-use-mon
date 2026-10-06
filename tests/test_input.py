"""Double-click dispatch: outer text ring locks Windows, inner bands toggle panel.

The text ring is the outer TEXT_FRAC of the arc radius; a click whose distance
from the arc centre is >= BAND_R_FRAC * r lands in the ring. The window mask
already clips clicks to the arc, so only the inner radius bound is tested.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtCore import QPointF, Qt

import widget as widget_mod
from widget import BAND_R_FRAC, _point_in_text_ring


# ── pure geometry helper ────────────────────────────────────────────────────

def test_point_in_outer_ring_is_true():
    # r=100 → ring threshold at BAND_R_FRAC*100. A point past it is in the ring.
    assert _point_in_text_ring(0, 0, 100, BAND_R_FRAC * 100 + 5, 0) is True


def test_point_near_centre_is_false():
    assert _point_in_text_ring(0, 0, 100, 10, 0) is False


def test_ring_boundary_is_inclusive():
    thr = BAND_R_FRAC * 100
    assert _point_in_text_ring(0, 0, 100, thr, 0) is True
    assert _point_in_text_ring(0, 0, 100, thr - 0.5, 0) is False


# ── double-click dispatch ───────────────────────────────────────────────────

class _FakeTracker:
    """Stands in for ActivityTracker so the test never starts pynput hooks."""
    active_seconds = 0
    is_idle = False

    def tick(self):
        pass

    def stop(self):
        pass


class _FakeEvent:
    def __init__(self, pos, button=Qt.MouseButton.LeftButton):
        self._pos = pos
        self._button = button
        self.accepted = False

    def button(self):
        return self._button

    def position(self):
        return self._pos

    def accept(self):
        self.accepted = True


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def arc(app, monkeypatch):
    monkeypatch.setattr(widget_mod, "ActivityTracker", lambda: _FakeTracker())
    w = widget_mod.ArcWidget()        # default position "TR": cx=150, cy=0, r=150
    yield w
    w.stop()


def _point_at(cx, cy, r, frac, angle_deg=135):
    import math
    a = math.radians(angle_deg)
    d = frac * r
    return QPointF(cx + d * math.cos(a), cy + d * math.sin(a))


def test_double_click_on_text_ring_locks(arc, monkeypatch):
    calls = []
    monkeypatch.setattr(widget_mod, "_lock_workstation",
                        lambda: calls.append("lock") or True)
    arc.on_double_click = lambda: calls.append("panel")

    ring_pt = _point_at(150, 0, 150, BAND_R_FRAC + 0.1)  # outer ring
    arc.mouseDoubleClickEvent(_FakeEvent(ring_pt))

    assert calls == ["lock"]


def test_double_click_on_inner_bands_toggles_panel(arc, monkeypatch):
    calls = []
    monkeypatch.setattr(widget_mod, "_lock_workstation",
                        lambda: calls.append("lock") or True)
    arc.on_double_click = lambda: calls.append("panel")

    inner_pt = _point_at(150, 0, 150, 0.4)  # well inside the bands
    arc.mouseDoubleClickEvent(_FakeEvent(inner_pt))

    assert calls == ["panel"]


def test_right_button_double_click_does_nothing(arc, monkeypatch):
    calls = []
    monkeypatch.setattr(widget_mod, "_lock_workstation",
                        lambda: calls.append("lock") or True)
    arc.on_double_click = lambda: calls.append("panel")

    ring_pt = _point_at(150, 0, 150, BAND_R_FRAC + 0.1)
    arc.mouseDoubleClickEvent(_FakeEvent(ring_pt, button=Qt.MouseButton.RightButton))

    assert calls == []
