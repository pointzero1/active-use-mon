# active-use-mon

Always-on-top desktop widget for Windows that displays:

- **Network**: real-time download/upload speed (bytes/sec from `psutil.net_io_counters`)
- **System**: CPU %, RAM %, primary disk %
- **Active time**: actual usage timer that pauses when there is no mouse/keyboard input (vs. raw uptime)

## Stack

- Python 3.14
- PyQt6 — frameless, translucent, draggable widget
- psutil — system + network counters
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

- Polls metrics every 1 second
- Activity timer increments only when input occurred within the last `IDLE_THRESHOLD_SECONDS` (default 60s)
- Window is frameless + always on top; drag from anywhere on the widget body
- Right-click → quit (or close via taskbar context)

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
- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest -v` (18 tests).

Deferred (not built): LLM prose session summaries; direct claude.ai chat capture.
