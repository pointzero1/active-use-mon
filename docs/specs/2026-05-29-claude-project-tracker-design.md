# Claude Project Tracker — Design Spec

**Date:** 2026-05-29
**Status:** Approved design, pre-implementation
**Lives in:** `C:\dev\sysmon-widget` (folded into the existing widget process)

## Problem

The user runs a lot of work across Claude Code and Cowork and is losing track of
which projects exist, what each was for, and which skills/tools were used where.
They want a glanceable, always-available view — but they are already noticing PC
lag and cannot afford a second always-on process.

## Constraints

- **No new always-on process.** Must ride on the existing `sysmon-widget` process
  (single `app.exec`, single tray icon).
- **Must not touch the 69MB of transcripts continuously.** Heavy parsing runs only
  on demand; the visible surface reads only a tiny precomputed index.
- **No change to the user's workflow.** Sessions are often run from the workspace
  root (`C:\Claude-AI`) or home (`C:\Users\bencu`), not from inside project folders,
  so project identity cannot rely on `cwd` alone.
- **Leave the existing `TriangleTimer` behavior untouched.**

## Non-goals (YAGNI)

- Prose/LLM session summaries — deferred to a future optional `/track summarize`
  skill that writes summaries back into the index. Not in this build.
- Capturing claude.ai cloud chat directly — the user's existing cowork→code export
  skills already land that work in the local transcripts.
- A standalone widget or browser dashboard — explicitly rejected in favor of folding
  into the existing process (Option A).

## Architecture

One process, two widgets, plus an on-demand indexer:

```
sysmon-widget process (single app.exec, single QSystemTrayIcon)
├── TriangleTimer        ← existing triangle timer, UNCHANGED
├── ProjectsPanel  (NEW) ← frameless panel, hidden by default, toggled on demand
└── claude_index.py (NEW)← indexer; invoked only when the panel opens / refreshes
        reads  C:\Users\bencu\.claude\projects\**\*.jsonl
        writes C:\dev\sysmon-widget\claude_index.json   (a few KB)
```

**Performance model:** the panel is hidden by default — when hidden it paints
nothing and runs no timers, so the marginal idle cost over today's widget is ~0.
The 69MB is touched only when the user opens the panel or clicks Refresh, and even
then only changed sessions are re-parsed (see incremental indexing).

## Component: `claude_index.py` (indexer)

A plain Python module (no PyQt dependency, independently testable) exposing a
`build_index(transcripts_root, cache_path) -> dict` function.

### Incremental scan
- Walk all `*.jsonl` under the transcripts root, including `subagents/` subfolders.
- Keep a cache keyed by file path holding `{mtime, size, extracted}`.
- For each file: if `mtime` and `size` are unchanged vs. the cache, reuse the
  cached extraction. Otherwise re-parse the file.
- First run parses everything (~a few seconds for 69MB); later runs parse only the
  one or two sessions that changed.

### Per-session extraction (no LLM)
Parse each transcript line-by-line and pull:
- **`session_id`** — the filename stem.
- **`cwd`** — from the session's records (the directory the session ran in).
- **`title`** — first human/user message text, trimmed to ~80 chars.
- **`started` / `last_active`** — first and last record timestamps.
- **`skills`** — names from Skill tool invocations.
- **`mcp_tools`** — tool names matching `mcp__<server>__*`, reduced to server names.
- **`tools`** — built-in tool names used (Read/Write/Edit/Bash/etc.).
- **`files`** — file paths referenced by Read/Write/Edit/Bash operations.
- **`project`** — see attribution rule below.

`subagents/agent-*.jsonl` files are attributed to their parent session (parent
folder name) and merged into that session's extraction, not listed separately.

### Project attribution rule
A session's project is inferred, in priority order:
1. If the session's `cwd` is under `C:\dev\<name>`, project = `<name>`.
2. Else, scan referenced file paths and message content for `C:\dev\<name>`
   occurrences; project = the `<name>` with the most references in that session.
3. Else, project = a labeled catch-all derived from `cwd`
   (e.g. `workspace-root (C:\Claude-AI)`, `home (C:\Users\bencu)`).

This is what makes the tracker useful despite most sessions running from the root —
content attribution was validated to have 6,500+ project-name references.

### Output: `claude_index.json`
Sessions rolled up by project:
```json
{
  "generated_at": "<iso timestamp>",
  "projects": [
    {
      "name": "daios-portal",
      "path": "C:\\dev\\daios-portal",
      "session_count": 4,
      "last_active": "<iso timestamp>",
      "skills": ["stamp", "daios-theme"],
      "mcp_tools": ["imagegen"],
      "sessions": [
        {"session_id": "...", "title": "...", "started": "...",
         "last_active": "...", "skills": [...], "files": [...]}
      ]
    }
  ]
}
```
Projects sorted by `last_active` descending. The incremental cache
(per-file mtime/size/extracted) is persisted in a separate sibling file,
`claude_index.cache.json`, so the human-facing `claude_index.json` stays clean.

## Component: `ProjectsPanel` (PyQt6 widget)

A `QWidget` constructed at startup but **hidden**. Lives in `projects_panel.py`.

- **Window flags:** `FramelessWindowHint | WindowStaysOnTopHint | Tool`, translucent
  background, styled to match the neon-amber sysmon palette (`#1a1612` bg, amber text).
- **On `show()`:** call `build_index(...)` (incremental, fast), load
  `claude_index.json`, render the list. On `hide()`: nothing runs.
- **Layout:** a search box at top; below it a scrollable list, most-recent project
  first. Each project row shows: **name · last active (relative) · N sessions ·
  skills/tools used**. Expanding a row (or a detail line) shows its recent session
  titles. A **Refresh** button re-runs the indexer. Draggable by the panel body;
  closeable back to hidden.
- **Search:** filters the rendered project/session list client-side (operates on the
  already-loaded index — no re-parsing).

## Integration into `widget.py`

- Construct one `ProjectsPanel` instance in `main()` alongside `TriangleTimer`,
  sharing the same `QApplication` and tray icon. Start hidden.
- **Open method 1 — tray menu:** add a `Show projects` / `Hide projects` toggle
  action above the snap items.
- **Open method 2 — double-click the triangle:** add a `mouseDoubleClickEvent` to
  `TriangleTimer` that emits a signal / calls a callback to toggle the panel.
  (Single-click drag behavior in `mousePressEvent`/`mouseMoveEvent` is preserved;
  double-click is distinct from drag.)
- No changes to the triangle's paint loop, timer, mask, or snapping.

## Data flow

```
open panel (tray or double-click)
   → build_index()  [incremental: only changed sessions re-parsed]
   → write claude_index.json
   → panel reads json → renders project list
close panel → idle (no timers, no parsing)
```

## Error handling

- Transcripts root missing / unreadable → panel shows "No transcripts found at
  <path>"; no crash.
- A malformed `.jsonl` line → skipped; parsing continues (best-effort per line).
- A transcript with no derivable `cwd` or project → bucketed into the `home` /
  `workspace-root` catch-all rather than dropped.
- Indexer exception → panel shows a one-line error and keeps the last good
  `claude_index.json` if present.

## Testing

- `claude_index.py` is pure (no Qt) and unit-testable:
  - Attribution rule: cwd-in-dev, content-inferred, catch-all fallback.
  - Incremental cache: unchanged mtime/size reuses cache; changed file re-parses.
  - Malformed-line resilience: bad lines skipped, file still indexed.
  - Subagent merge: `subagents/*.jsonl` folded into parent session.
- Run against a small fixture directory of synthetic `.jsonl` files plus a smoke
  run over the real transcripts to confirm timing (first run vs. incremental).
- Manual: launch widget, double-click triangle and use tray toggle to open/close,
  confirm triangle behavior unchanged and idle cost unchanged.

## Files added/changed

- `claude_index.py` (new) — indexer, no Qt deps.
- `projects_panel.py` (new) — `ProjectsPanel` QWidget.
- `widget.py` (changed) — instantiate panel, add tray toggle, add double-click.
- `claude_index.json` / `claude_index.cache.json` (generated, gitignore-able).
- `docs/specs/2026-05-29-claude-project-tracker-design.md` (this file).
