"""Qt-free logic for the clock & weather panel.

US time-zone math (zoneinfo), date formatting, IP geolocation (ipwho.is) and
current weather (Open-Meteo, no API key). All network calls are best-effort and
never raise out of ``fetch_weather`` — the panel keeps working offline.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_HERE = Path(__file__).parent
CACHE_PATH = _HERE / "weather_cache.json"
OVERRIDE_PATH = _HERE / "location_override.json"  # optional {"lat","lon","name"}

US_ZONES = [
    ("Eastern",  "America/New_York"),
    ("Central",  "America/Chicago"),
    ("Mountain", "America/Denver"),
    ("Pacific",  "America/Los_Angeles"),
    ("Alaska",   "America/Anchorage"),
    ("Hawaii",   "Pacific/Honolulu"),
]

# The four continental zones, in the order the calendar widget shows them.
MAIN_ZONES = [z for z in US_ZONES if z[0] in ("Eastern", "Central", "Mountain", "Pacific")]

# WMO weather interpretation codes (Open-Meteo `weather_code`).
_WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}


def _fmt_time(dt: datetime) -> str:
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def us_zone_times(now_utc: datetime, zones: list | None = None) -> list[dict]:
    """Current time in each zone (default: all US zones). ``now_utc`` must be
    timezone-aware; ``zones`` is a list of (label, IANA key) pairs."""
    rows = []
    for label, key in (zones or US_ZONES):
        local = now_utc.astimezone(ZoneInfo(key))
        rows.append({"label": label, "tz": key,
                     "abbr": local.tzname(), "time": _fmt_time(local)})
    return rows


def format_date(dt: datetime) -> str:
    return f"{dt.strftime('%A, %B')} {dt.day}, {dt.year}"


def format_date_short(dt: datetime) -> str:
    """MM.DD.YY, e.g. 10.06.26 (used when the calendar widget is collapsed)."""
    return dt.strftime("%m.%d.%y")


def parse_location(data: dict) -> dict | None:
    """ipwho.is response -> {lat, lon, name, tz}, or None if unusable."""
    if not data or not data.get("success"):
        return None
    try:
        city = data.get("city") or "Unknown"
        region = data.get("region_code") or ""
        return {"lat": float(data["latitude"]), "lon": float(data["longitude"]),
                "name": f"{city}, {region}" if region else city,
                "tz": (data.get("timezone") or {}).get("id")}
    except (KeyError, TypeError, ValueError):
        return None


def parse_weather(data: dict) -> dict | None:
    """Open-Meteo response -> {temp_f, condition, wind_mph}, or None."""
    cur = (data or {}).get("current")
    if not cur:
        return None
    try:
        return {"temp_f": round(cur["temperature_2m"]),
                "condition": _WMO.get(cur["weather_code"], "Unknown"),
                "wind_mph": round(cur["wind_speed_10m"])}
    except (KeyError, TypeError, ValueError):
        return None


def _http_json(url: str, timeout: float = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "active-use-mon"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only
        return json.loads(resp.read().decode("utf-8"))


def resolve_location() -> dict | None:
    """Manual override file wins; otherwise approximate location from IP."""
    try:
        o = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
        return {"lat": float(o["lat"]), "lon": float(o["lon"]),
                "name": o.get("name", "Custom"), "tz": o.get("tz")}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return parse_location(_http_json("https://ipwho.is/"))


def _read_cache() -> dict | None:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(result: dict) -> None:
    tmp = CACHE_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(result), encoding="utf-8")
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass  # cache is a nicety; never break the panel


def fetch_weather() -> dict | None:
    """{location, weather, stale}. Falls back to the last cached result
    (stale=True) on any failure; None if there is nothing to show."""
    try:
        loc = resolve_location()
        if loc is None:
            raise ValueError("no location")
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={loc['lat']}&longitude={loc['lon']}"
               "&current=temperature_2m,weather_code,wind_speed_10m"
               "&temperature_unit=fahrenheit&wind_speed_unit=mph")
        weather = parse_weather(_http_json(url))
        if weather is None:
            raise ValueError("bad weather payload")
        result = {"location": loc, "weather": weather, "stale": False}
        _write_cache(result)
        return result
    except Exception:  # noqa: BLE001 - offline / API down: degrade, don't crash
        cached = _read_cache()
        if cached:
            cached["stale"] = True
        return cached
