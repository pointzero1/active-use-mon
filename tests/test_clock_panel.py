import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timezone

import pytest
from PyQt6.QtWidgets import QApplication

_WX = {"location": {"lat": 1, "lon": 2, "name": "Indianapolis, IN",
                    "tz": "America/Indiana/Indianapolis"},
       "weather": {"temp_f": 72, "condition": "Clear", "wind_mph": 5},
       "stale": False}


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


def _panel(fetcher=None):
    from clock_panel import ClockPanel
    return ClockPanel(fetcher=fetcher or (lambda: _WX))


def test_constructs_hidden_and_shows_all_zones(app):
    p = _panel()
    assert p.isHidden()
    p.refresh_clocks(datetime(2026, 7, 1, 16, 0, tzinfo=timezone.utc))
    texts = [(a.text(), c.text()) for a, _, c in p._zone_labels]
    assert texts[0] == ("Eastern", "12:00 PM")
    assert texts[3] == ("Pacific", "9:00 AM")
    assert len(texts) == 6
    p.close()


def test_render_weather_and_stale_marker(app):
    p = _panel()
    p.render_weather(_WX)
    assert p.temp_label.text() == "72°F"
    assert "Clear" in p.cond_label.text()
    assert p.loc_label.text() == "Indianapolis, IN"
    p.render_weather({**_WX, "stale": True})
    assert "stale" in p.loc_label.text()
    p.close()


def test_offline_with_no_cache_shows_unavailable(app):
    p = _panel(fetcher=lambda: None)
    p._on_weather(None)
    assert p.cond_label.text() == "Weather unavailable"
    p.close()


def test_open_starts_and_hide_stops_timers(app):
    p = _panel()
    p.open_panel()
    assert p._clock.isActive()
    p.hide()
    assert not p._clock.isActive()
    p.close()


def test_home_zone_highlighted_by_offset(app):
    p = _panel()
    p.render_weather(_WX)   # Indianapolis -> Eastern offset
    p.refresh_clocks(datetime(2026, 7, 1, 16, 0, tzinfo=timezone.utc))
    names = [n.objectName() for n, _, _ in p._zone_labels]
    assert names[0] == "zonehome" and names.count("zonehome") == 1
    p.close()
