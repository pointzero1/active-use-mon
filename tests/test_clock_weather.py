import json
from datetime import datetime, timezone

import clock_weather as cw


def test_us_zone_times_dst_and_standard():
    summer = datetime(2026, 7, 1, 16, 0, tzinfo=timezone.utc)
    rows = {r["label"]: r for r in cw.us_zone_times(summer)}
    assert rows["Eastern"]["abbr"] == "EDT" and rows["Eastern"]["time"] == "12:00 PM"
    assert rows["Pacific"]["abbr"] == "PDT" and rows["Pacific"]["time"] == "9:00 AM"
    assert rows["Hawaii"]["abbr"] == "HST" and rows["Hawaii"]["time"] == "6:00 AM"

    winter = datetime(2026, 1, 15, 16, 0, tzinfo=timezone.utc)
    rows = {r["label"]: r for r in cw.us_zone_times(winter)}
    assert rows["Central"]["abbr"] == "CST" and rows["Central"]["time"] == "10:00 AM"
    assert rows["Alaska"]["abbr"] == "AKST" and rows["Alaska"]["time"] == "7:00 AM"


def test_us_zone_times_order_and_count():
    rows = cw.us_zone_times(datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert [r["label"] for r in rows] == [
        "Eastern", "Central", "Mountain", "Pacific", "Alaska", "Hawaii"]


def test_format_date():
    assert cw.format_date(datetime(2026, 10, 6, 12, 0)) == "Tuesday, October 6, 2026"


def test_parse_location_ok_and_failure():
    ok = cw.parse_location({"success": True, "latitude": 39.77, "longitude": -86.16,
                            "city": "Indianapolis", "region_code": "IN",
                            "timezone": {"id": "America/Indiana/Indianapolis"}})
    assert ok == {"lat": 39.77, "lon": -86.16, "name": "Indianapolis, IN",
                  "tz": "America/Indiana/Indianapolis"}
    assert cw.parse_location({"success": False}) is None
    assert cw.parse_location({}) is None


def test_parse_weather_and_codes():
    w = cw.parse_weather({"current": {"temperature_2m": 71.6, "weather_code": 2,
                                      "wind_speed_10m": 8.4}})
    assert w == {"temp_f": 72, "condition": "Partly cloudy", "wind_mph": 8}
    unknown = cw.parse_weather({"current": {"temperature_2m": 50, "weather_code": 999,
                                            "wind_speed_10m": 0}})
    assert unknown["condition"] == "Unknown"
    assert cw.parse_weather({}) is None


def test_fetch_weather_stale_fallback_when_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(cw, "CACHE_PATH", tmp_path / "c.json")
    monkeypatch.setattr(cw, "OVERRIDE_PATH", tmp_path / "no-override.json")

    def route(url, timeout=8):
        if "ipwho.is" in url:
            return {"success": True, "latitude": 1, "longitude": 2, "city": "X",
                    "region_code": "", "timezone": {"id": "UTC"}}
        return {"current": {"temperature_2m": 70, "weather_code": 0,
                            "wind_speed_10m": 3}}

    monkeypatch.setattr(cw, "_http_json", route)
    r = cw.fetch_weather()
    assert r["stale"] is False and r["weather"]["temp_f"] == 70

    def boom(url, timeout=8):
        raise OSError("offline")

    monkeypatch.setattr(cw, "_http_json", boom)
    r = cw.fetch_weather()
    assert r["stale"] is True and r["weather"]["temp_f"] == 70

    monkeypatch.setattr(cw, "CACHE_PATH", tmp_path / "none.json")
    assert cw.fetch_weather() is None


def test_location_override(monkeypatch, tmp_path):
    p = tmp_path / "o.json"
    p.write_text(json.dumps({"lat": 40.0, "lon": -75.0, "name": "Philly"}))
    monkeypatch.setattr(cw, "OVERRIDE_PATH", p)
    loc = cw.resolve_location()
    assert loc["name"] == "Philly" and loc["lat"] == 40.0


def test_format_date_short():
    assert cw.format_date_short(datetime(2026, 10, 6, 12, 0)) == "10.06.26"
    assert cw.format_date_short(datetime(2027, 1, 5)) == "01.05.27"
