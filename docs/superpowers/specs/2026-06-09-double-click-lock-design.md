# Double-click text ring → lock Windows

**Date:** 2026-06-09
**Status:** Approved, ready for implementation

## Goal

Let the user lock their Windows session by double-clicking the arc widget's
outer text ring (the gray band where the active-time-in-words curves).

## Behavior

- **Double-click on the outer text ring** → lock the Windows session.
- **Double-click on the inner hour/minute bands** → toggle the projects panel
  (unchanged from today).
- Single-click, drag/snap, right-click menu, and tray menu are all unchanged.

The text ring is the outer `TEXT_FRAC` (0.22) of the arc radius — i.e. radius
fraction `>= BAND_R_FRAC` (0.78). The window mask already clips clicks to the
arc shape, so a click inside the widget is guaranteed to be within the angular
span and within the outer radius `r`; only the inner radius bound needs testing.

## Changes (all in `widget.py`)

1. **`_lock_workstation() -> bool`** — module-level helper. On `win32`, calls
   `ctypes.windll.user32.LockWorkStation()`; wrapped in `try/except`; returns
   `False` off-Windows or on failure. Must never raise into the Qt event loop
   (same defensive style as `_win32_monitor_rects`). No new dependency — `ctypes`
   is already imported lazily elsewhere in the file.

2. **`_point_in_text_ring(cx, cy, r, x, y) -> bool`** — pure geometry helper.
   Returns `True` when `hypot(x - cx, y - cy) >= BAND_R_FRAC * r`. A thin
   `ArcWidget._in_text_ring(pos)` wrapper reads `POSITION_GEOMETRY[self.position]`
   and delegates to it. Pure function = unit-testable like `logical_work_area`.

3. **`ArcWidget.mouseDoubleClickEvent`** — branch on region:
   ```python
   if event.button() != Qt.MouseButton.LeftButton:
       return
   if self._in_text_ring(event.position().toPoint()):
       _lock_workstation()
   elif self.on_double_click:
       self.on_double_click()
   event.accept()
   ```

## Testing

New `tests/test_input.py` (offscreen, matching `test_geometry.py` style):

- `_point_in_text_ring`: outer-ring point → True, near-center point → False,
  boundary at `BAND_R_FRAC * r`.
- Dispatch: with `_lock_workstation` and `on_double_click` monkeypatched to
  record calls, a fake double-click event whose `position()` lands in the ring
  invokes lock (not panel); one in the inner bands invokes panel (not lock).
  The real `LockWorkStation` is never called.

## Out of scope (YAGNI)

- No confirmation dialog, no config toggle.
- No cross-platform lock — Windows only; a no-op (returns `False`) elsewhere.
