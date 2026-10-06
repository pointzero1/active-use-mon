# active-use-mon

Always-on-top desktop widget for Windows: a small corner/edge arc showing **active
time** — a usage timer that pauses when there is no mouse/keyboard input (vs. raw
uptime). Two hidden-by-default panels ride on the same process: the Claude Project
Tracker and the Clock & Weather panel (below).

## Stack

- Python 3.14
- PyQt6 — frameless, translucent, draggable widget
- psutil — system counters (dependency only; no CPU/RAM/network display currently)
- tzdata — IANA timezone database for `zoneinfo` on Windows
- pynput — global mouse/keyboard activity detection

## Run

```powershell
pip install -r requirements.txt
python widget.py
```

## Files

- `widget.py` — entry point, PyQt6 UI, polling loop
- `activity_tracker.py` — pynput listeners, idle-aware active-time counter
- `requirements.txt` — pinned-ish deps

## Behavior

- Polls the activity tracker every 1 second
- Activity timer increments only when input occurred within the last `IDLE_THRESHOLD_SECONDS` (default 60s)
- Window is frameless + always on top; drag from anywhere on the widget body
- Right-click → menu (panels, snap position, theme, quit)
- Double-click inner bands → projects panel; outer words band → lock Windows

## Claude Project Tracker

A second, hidden-by-default panel (`projects_panel.py`) rides on the same process
as the arc widget. It shows what you've worked on across Claude Code/Cowork.

- `claude_index.py` — incremental indexer over `~/.claude/projects/**/*.jsonl`;
  writes `claude_index.json` (+ `claude_index.cache.json`). No LLM, no Qt.
  Index/cache writes are atomic and crash-safe so they can never break the widget.
- Attributes each session to a real `C:\dev\<project>` by what it touched (cwd in
  dev > most-referenced dev project in content > `workspace-root` / `home` catch-all).
- Subagent transcripts (`<uuid>/subagents/agent-*.jsonl`) merge into their parent session.
- Open the panel three ways: double-click the arc, the arc's right-click menu, or the
  tray menu → "Show / hide projects".
- The panel only does work when opened (incremental refresh on open); hidden = idle.
- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest -v` (39 tests).

## Clock & Weather panel

Hidden-by-default (`clock_panel.py`, logic in Qt-free `clock_weather.py`). Open it from
the arc's right-click menu or the tray menu → "Show / hide clock & weather".

- Date, current weather (°F, condition, wind) and live time in the six US zones
  (Eastern, Central, Mountain, Pacific, Alaska, Hawaii); your own zone is highlighted.
- Location: approximate, from your public IP via `ipwho.is` (that IP is the only thing
  sent). Override with `location_override.json` → `{"lat": .., "lon": .., "name": ".."}`.
- Weather: Open-Meteo (no API key), fetched on a worker thread on open and every 15 min.
  Offline → last cached result (`weather_cache.json`) marked "stale"; clocks keep running.
- Clocks tick only while the panel is visible.

Deferred (not built): LLM prose session summaries; direct claude.ai chat capture.
