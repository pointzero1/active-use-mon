import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

import pytest
from PyQt6.QtCore import QPoint, QRect, QSize
from PyQt6.QtWidgets import QApplication

import calendar_widget as cwg

_WX = {"location": {"lat": 1, "lon": 2, "name": "Avon, IN", "tz": "America/Indiana/Indianapolis"},
       "weather": {"temp_f": 64, "condition": "Clear", "wind_mph": 7}, "stale": False}
AREA = QRect(0, 0, 1920, 1040)


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def _w(tmp_path, fetcher=None):
    return cwg.CalendarWidget(fetcher=fetcher or (lambda: _WX),
                              state_path=tmp_path / "state.json")


# ── content ─────────────────────────────────────────────────────────────────

def test_shows_four_zones_in_order(app, tmp_path):
    w = _w(tmp_path)
    w.refresh_clocks(datetime(2026, 7, 1, 16, 0, tzinfo=timezone.utc))
    shown = [(a.text(), t.text()) for a, t in w._zone_labels]
    assert shown == [("EDT", "12:00 PM"), ("CDT", "11:00 AM"),
                     ("MDT", "10:00 AM"), ("PDT", "9:00 AM")]
    w.close()


def test_today_highlight_moves_on_rollover(app, tmp_path):
    w = _w(tmp_path)
    w.refresh_clocks(datetime(2026, 7, 1, 16, 0, tzinfo=timezone.utc))
    first = w._marked
    w.refresh_clocks(datetime(2026, 7, 2, 16, 0, tzinfo=timezone.utc))
    assert w._marked != first
    assert w.calendar.monthShown() == 7
    w.close()


def test_weather_render_and_offline(app, tmp_path):
    w = _w(tmp_path)
    w._on_weather(None)
    assert w.cond_label.text() == "Weather unavailable"
    w._on_weather(_WX)
    assert w.temp_label.text() == "64°F" and "Clear" in w.cond_label.text()
    w._on_weather(None)                      # later failure keeps last good data
    assert w.temp_label.text() == "64°F"
    w.close()


def test_vertical_order_zones_calendar_weather(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    app.processEvents()
    ys = [w.date_label.y(), w.zones_host.y(), w.calendar.y(), w.weather_host.y()]
    assert ys == sorted(ys) and len(set(ys)) == 4
    w.close()


# ── collapse / expand ───────────────────────────────────────────────────────

def test_collapse_shows_only_time_and_date(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    full_h = w.height()
    w.toggle_expanded()
    app.processEvents()
    assert not w.expanded
    assert w.bigtime_label.isVisible() and w.date_label.isVisible()
    assert not (w.zones_host.isVisible() or w.calendar.isVisible() or w.weather_host.isVisible())
    assert w.height() < full_h
    w.toggle_expanded()
    app.processEvents()
    assert w.expanded and w.calendar.isVisible() and not w.bigtime_label.isVisible()
    w.close()


def _click(w, at=QPoint(400, 400)):
    w._mouse_press(at)
    w._mouse_release()


def test_single_click_expands_collapses_after_double_click_interval(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    _click(w)
    assert w.expanded and w._click_timer.isActive()   # waiting to see if it's a double
    w._click_timer.stop()
    w._single_click()                                  # the timer firing
    assert not w.expanded
    w.close()


def test_double_click_toggles_opacity_only(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    assert not w.opaque
    _click(w)
    _click(w)                                          # second click inside the interval
    assert w.opaque and w.expanded                     # opacity flipped, no expand/collapse
    assert not w._click_timer.isActive()               # pending single-click was cancelled
    _click(w)
    _click(w)
    assert not w.opaque
    w.close()


def test_jitter_within_slop_is_a_click_but_real_drag_is_not(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    w.move(300, 300)
    w._mouse_press(QPoint(400, 400))
    w._mouse_move(QPoint(402, 401))
    w._mouse_release()
    assert w._click_timer.isActive()                   # counted as a click
    w._click_timer.stop()
    w._mouse_press(QPoint(400, 400))
    w._mouse_move(QPoint(500, 450))                    # real drag
    w._mouse_release()
    assert not w._click_timer.isActive() and w.expanded
    w.close()


def test_background_alpha_never_zero(app):
    # Alpha 0 would let Windows pass clicks through the card; keep it hit-testable.
    assert 0 < cwg.BG_CLEAR.alpha() < 10
    assert cwg.BG_OPAQUE.alpha() == 255


def test_opaque_state_persists(app, tmp_path):
    w = _w(tmp_path)
    w.toggle_opaque()
    assert cwg.load_state(tmp_path / "state.json")["opaque"] is True
    w2 = _w(tmp_path)
    w2.place()
    assert w2.opaque
    w.close(); w2.close()


def test_drag_moves_window_and_persists_state(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    w.move(500, 400)
    w._mouse_press(QPoint(550, 450))
    w._mouse_move(QPoint(650, 490))
    assert w.pos() == QPoint(600, 440)
    w._mouse_release()
    st = cwg.load_state(tmp_path / "state.json")
    assert st["expanded"] is True and "x" in st
    w.close()


def test_state_roundtrip_restores_collapsed(app, tmp_path):
    cwg.save_state({"x": 50, "y": 60, "anchor": "", "expanded": False}, tmp_path / "state.json")
    w = _w(tmp_path)
    w.place()
    assert not w.expanded
    w.close()


# ── pure helpers ────────────────────────────────────────────────────────────

def test_detect_anchor():
    size = (300, 500)
    far = QRect(800, 300, *size)
    assert cwg.detect_anchor(far, AREA) == ""
    assert cwg.detect_anchor(QRect(10, 10, *size), AREA) == "TL"
    assert cwg.detect_anchor(QRect(AREA.right() - 310, 10, *size), AREA) == "TR"
    assert cwg.detect_anchor(QRect(10, AREA.bottom() - 510, *size), AREA) == "BL"
    assert cwg.detect_anchor(QRect(AREA.right() - 310, AREA.bottom() - 510, *size), AREA) == "BR"
    assert cwg.detect_anchor(QRect(800, 20, *size), AREA) == "T"       # top edge only
    assert cwg.detect_anchor(QRect(15, 300, *size), AREA) == "L"


def test_anchored_pos_corners_sides_and_free_axis():
    size = QSize(300, 500)
    m = cwg.SNAP_MARGIN
    assert cwg.anchored_pos("TL", QPoint(99, 99), size, AREA) == QPoint(m, m)
    assert cwg.anchored_pos("BR", QPoint(0, 0), size, AREA) == QPoint(
        AREA.right() - 300 + 1 - m, AREA.bottom() - 500 + 1 - m)
    # side snap keeps the along-edge coordinate when dragged…
    assert cwg.anchored_pos("T", QPoint(777, 99), size, AREA) == QPoint(777, m)
    # …but is centred when chosen from the menu.
    assert cwg.anchored_pos("T", QPoint(777, 99), size, AREA, center_free_axis=True) == QPoint(
        (1920 - 300) // 2, m)
    assert cwg.anchored_pos("L", QPoint(99, 33), size, AREA, center_free_axis=True) == QPoint(
        m, (1040 - 500) // 2)
    # free stays put but is clamped on-screen
    assert cwg.anchored_pos("", QPoint(5000, 5000), size, AREA) == QPoint(
        AREA.right() - 299, AREA.bottom() - 499)


def test_nested_widget_stays_nested_when_it_resizes(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    w.snap_to("BR")
    app.processEvents()
    area = w._work_area()
    assert w.frameGeometry().right() == area.right() - cwg.SNAP_MARGIN
    w.toggle_expanded()
    app.processEvents()
    assert w.frameGeometry().right() == area.right() - cwg.SNAP_MARGIN
    assert w.frameGeometry().bottom() == area.bottom() - cwg.SNAP_MARGIN
    w.close()


def test_clamp_to_screens():
    screens = [QRect(0, 0, 1920, 1080)]
    size = QSize(300, 500)
    assert cwg.clamp_to_screens(QPoint(100, 100), size, screens) == QPoint(100, 100)
    assert cwg.clamp_to_screens(QPoint(1900, 1000), size, screens) == QPoint(1620, 580)
    assert cwg.clamp_to_screens(QPoint(5000, 5000), size, screens) == QPoint(40, 40)


def test_load_state_missing_or_corrupt(tmp_path):
    assert cwg.load_state(tmp_path / "nope.json") is None
    (tmp_path / "bad.json").write_text("{not json")
    assert cwg.load_state(tmp_path / "bad.json") is None


def test_collapsed_date_is_mm_dd_yy_and_expanded_is_full(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    now = datetime.now(timezone.utc).astimezone()
    assert w.date_label.text() == cwg.cw.format_date(now)
    w.toggle_expanded()                                 # updates immediately, no tick wait
    assert w.date_label.text() == now.strftime("%m.%d.%y")
    w.toggle_expanded()
    assert w.date_label.text() == cwg.cw.format_date(now)
    w.close()


def test_collapsed_date_uses_same_style_as_time(app, tmp_path):
    w = _w(tmp_path)
    w.show()
    assert w.date_label.objectName() == "date"
    w.toggle_expanded()
    app.processEvents()
    assert w.date_label.objectName() == w.bigtime_label.objectName() == "bigtime"
    assert w.date_label.font().pixelSize() == w.bigtime_label.font().pixelSize() or         w.date_label.fontMetrics().height() == w.bigtime_label.fontMetrics().height()
    w.toggle_expanded()
    assert w.date_label.objectName() == "date"
    w.close()
