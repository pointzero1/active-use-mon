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
- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest -v` (60 tests).

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

## Calendar widget (separate program)

`calendar_widget.py` — its own always-on-top card, independent of the arc. Run:
`pythonw calendar_widget.py`. Reuses `clock_weather.py` (zones, weather) and imports
`widget.py`'s Win32 work-area helpers, so it still needs the arc's deps installed.

- Expanded, top → bottom: date + EDT/CDT/MDT/PDT times, month calendar, weather.
- **Click** collapses to just the local time and date (`MM.DD.YY`, same size as the
  time); click again expands. A click waits out the double-click interval.
- **Double-click** toggles fully transparent (default) ↔ opaque background. Transparent
  paints alpha 2, not 0, because Windows passes clicks through zero-alpha pixels.
- **Drag** to move; releasing within 60px of an edge/corner nests it there (and it stays
  nested across expand/collapse). Right-click → Snap → corner/side, opacity, quit.
- State (position, nested edges, expanded, opaque) persists in the gitignored
  `calendar_widget_pos.json`.

Deferred (not built): LLM prose session summaries; direct claude.ai chat capture.
