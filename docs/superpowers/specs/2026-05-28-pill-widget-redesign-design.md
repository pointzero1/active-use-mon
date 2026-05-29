# Pill Widget Redesign

**Date:** 2026-05-28
**Status:** Approved
**Supersedes:** triangle-corner widget (archived as `widget_triangle.py.bak`)

## Motivation

The triangle corner widget occupied a 150 x 150 px screen corner, intercepting
clicks on app close/minimize buttons, and its hour-tile + pie-minute drawing
was visually busy. Replace with a minimal edge-pinned pill that stays out of
the way of app content.

## Scope

Replace `widget.py` with a new top-edge pill widget. `activity_tracker.py`,
`active_time.json`, and the dependency set are unchanged.

## Design

### Shape & geometry

- Rounded rectangle, 140 W x 22 H px, corner radius 11 (full half-circles at ends)
- Frameless, translucent background, always-on-top, tool window (no taskbar entry)

### Content (left -> right inside the pill)

- 8 px circular indicator dot
  - Amber (`#FF6E28`) when active (input within last 60 s)
  - Dim grey (`#6E6E6E`) when idle
- 6 px gap
- Time text, Cascadia Mono 11pt, near-white at high alpha when active,
  ~50% alpha when idle
  - `< 1 h`: `24m`
  - `>= 1 h`: `3h 24m`
  - `>= 10 h`: `10h 24m` (fits in the 140 px width)

### Background

- Soft dark fill, RGBA `(20, 16, 14, 140)` (~55% alpha)
- 1 px inner border `(255, 110, 40, 60)` for definition

### Behavior

- 1 s poll loop (reuse the existing pattern)
- Drag freely; on mouse release, snap to nearest of 6 slots:
  `TL`, `TC`, `TR`, `BL`, `BC`, `BR`
- Default position on first launch: `TC`
- Right-click menu: six "Snap -> ..." actions + Quit

### What stays from the existing project

- `activity_tracker.py` reused verbatim (idle-aware counter, 60 s threshold,
  daily reset, JSON persistence)
- Same stack: PyQt6 + pynput + psutil
- `active_time.json` format unchanged - widget picks up today's accumulated
  seconds on launch

### What is removed

- All of `widget.py`: triangle mask, pentagon geometry, hour-tile grid,
  pie minute bars, punched-through hour numbers, centered minute digits,
  corner-snap geometry tables. Archived as `widget_triangle.py.bak`.

## Non-goals

- No network / CPU / RAM / disk metrics (the original `CLAUDE.md` mentioned
  these but the triangle widget never displayed them; the pill stays focused
  on active time)
- No multi-monitor screen selection UI (snaps to the screen the widget
  currently sits on, like before)
- No autostart-on-login config in this iteration

## Verification

- Launch via `pythonw widget.py`; widget appears at top-center of primary
  screen, flush with the work-area top edge
- After ~5 s of activity, time updates from `0m` / current persisted value
- After 60 s of no input, dot dims and text dims
- Drag to a different edge -> snaps to nearest of the 6 slots
- Right-click -> menu appears with snap options and Quit
- `widget.err.log` stays empty
