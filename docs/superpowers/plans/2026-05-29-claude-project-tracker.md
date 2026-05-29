# Claude Project Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-demand, glanceable "what have I worked on" project tracker to the existing `sysmon-widget` process, reading Claude Code/Cowork transcripts without adding any always-on cost.

**Architecture:** A pure-Python incremental indexer (`claude_index.py`) parses `~/.claude/projects/**/*.jsonl` into a tiny `claude_index.json`, attributing each session to a real `C:\dev\<project>` by what it touched. A hidden-by-default PyQt6 `ProjectsPanel` reads that JSON and renders it; it's toggled from the existing tray menu and a double-click on the triangle. The existing `TriangleTimer` is untouched.

**Tech Stack:** Python 3, PyQt6, pytest. Standard library only for the indexer (json, glob, os, re, datetime, collections).

---

## File Structure

- **Create** `claude_index.py` — indexer. Pure stdlib, no Qt. Public API: `extract_session`, `infer_project`, `build_index`, `refresh`, `load_index`, plus display helpers `format_relative`, `filter_index`.
- **Create** `projects_panel.py` — `ProjectsPanel(QWidget)`. Hidden by default; renders `claude_index.json`.
- **Modify** `widget.py` — instantiate the panel, add a tray toggle action, add double-click-to-toggle on the triangle.
- **Create** `tests/test_claude_index.py` — unit tests for the indexer + display helpers.
- **Create** `tests/test_projects_panel.py` — offscreen smoke test for the panel.
- **Create** `.gitignore` — ignore generated index/cache and Python caches.
- **Generated (not committed)** `claude_index.json`, `claude_index.cache.json`.

Module-level constants in `claude_index.py`:
```python
DEV_ROOT = r"C:\dev"
TRANSCRIPTS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")
INDEX_PATH = os.path.join(os.path.dirname(__file__), "claude_index.json")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "claude_index.cache.json")
```

---

## Task 0: Repo init + scaffolding

**Files:**
- Create: `.gitignore`
- Create: `tests/__init__.py` (empty)

- [ ] **Step 1: Initialize git and ignore generated/build files**

Run:
```bash
cd /c/dev/sysmon-widget && git init
```
Expected: `Initialized empty Git repository in C:/dev/sysmon-widget/.git/`

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.py[cod]
*.bak
widget.out.log
widget.err.log
claude_index.json
claude_index.cache.json
active_time.json
.pytest_cache/
```

- [ ] **Step 3: Create empty tests package**

Create `tests/__init__.py` with no content.

- [ ] **Step 4: Commit**

```bash
git add .gitignore tests/__init__.py docs
git commit -m "chore: git init, gitignore, tests scaffold, tracker spec+plan"
```

---

## Task 1: Indexer — single-session extraction

**Files:**
- Create: `claude_index.py`
- Test: `tests/test_claude_index.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_claude_index.py`:
```python
import json
import os
from claude_index import extract_session


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_extract_session_pulls_core_fields(tmp_path):
    p = tmp_path / "sess-abc.jsonl"
    _write_jsonl(p, [
        {"type": "user", "cwd": r"C:\Claude-AI", "timestamp": "2026-05-01T10:00:00Z",
         "message": {"content": "Fix the daios-portal vehicle links"}},
        {"type": "assistant", "timestamp": "2026-05-01T10:00:05Z",
         "message": {"content": [
             {"type": "tool_use", "name": "Read",
              "input": {"file_path": r"C:\dev\daios-portal\index.html"}},
             {"type": "tool_use", "name": "Skill", "input": {"skill": "daios-theme"}},
             {"type": "tool_use", "name": "mcp__imagegen__image_generate_openai",
              "input": {}},
         ]}},
        {"type": "user", "timestamp": "2026-05-01T10:01:00Z",
         "message": {"content": "thanks"}},
    ])
    s = extract_session(str(p))
    assert s["session_id"] == "sess-abc"
    assert s["cwd"] == r"C:\Claude-AI"
    assert s["title"] == "Fix the daios-portal vehicle links"
    assert s["started"] == "2026-05-01T10:00:00Z"
    assert s["last_active"] == "2026-05-01T10:01:00Z"
    assert s["skills"] == ["daios-theme"]
    assert s["mcp_tools"] == ["imagegen"]
    assert "Read" in s["tools"]
    assert r"C:\dev\daios-portal\index.html" in s["files"]
    assert s["dev_refs"].get("daios-portal", 0) >= 1


def test_extract_session_skips_malformed_lines(tmp_path):
    p = tmp_path / "sess-bad.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"type": "user", "timestamp": "2026-05-01T10:00:00Z", '
                 '"message": {"content": "hi"}}\n')
        fh.write("this is not json\n")
        fh.write('{"type": "user", "timestamp": "2026-05-01T10:02:00Z", '
                 '"message": {"content": "bye"}}\n')
    s = extract_session(str(p))
    assert s["title"] == "hi"
    assert s["last_active"] == "2026-05-01T10:02:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_index'`

- [ ] **Step 3: Write minimal implementation**

Create `claude_index.py`:
```python
"""Incremental indexer for Claude Code / Cowork transcripts.

Pure stdlib (no Qt). Parses ~/.claude/projects/**/*.jsonl into a small
project-rolled-up index, attributing each session to a real C:\\dev\\<project>
by what it touched.
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

DEV_ROOT = r"C:\dev"
TRANSCRIPTS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")
INDEX_PATH = os.path.join(os.path.dirname(__file__), "claude_index.json")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "claude_index.cache.json")

# Matches C:\dev\<name> in raw transcript lines (backslashes are JSON-escaped,
# so allow one-or-more) and in parsed single-backslash strings.
_DEV_RE = re.compile(r"[Cc]:\\+dev\\+([A-Za-z0-9_.\-]+)")


def _first_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def extract_session(path: str) -> dict:
    """Parse one transcript file into a session dict."""
    session_id = os.path.splitext(os.path.basename(path))[0]
    cwd = None
    title = None
    started = None
    last_active = None
    skills, mcp_tools, tools, files = set(), set(), set(), set()
    dev_refs: Counter = Counter()

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            for m in _DEV_RE.finditer(line):
                dev_refs[m.group(1)] += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cwd is None and rec.get("cwd"):
                cwd = rec["cwd"]
            ts = rec.get("timestamp")
            if ts:
                if started is None:
                    started = ts
                last_active = ts
            rtype = rec.get("type")
            msg = rec.get("message")
            if rtype == "user" and title is None and isinstance(msg, dict):
                title = _first_text(msg.get("content"))
            if rtype == "assistant" and isinstance(msg, dict):
                for block in (msg.get("content") or []):
                    if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                        continue
                    name = block.get("name", "")
                    inp = block.get("input") or {}
                    if name == "Skill":
                        skill = inp.get("skill")
                        if skill:
                            skills.add(skill)
                    elif name.startswith("mcp__"):
                        parts = name.split("__")
                        if len(parts) >= 2 and parts[1]:
                            mcp_tools.add(parts[1])
                    elif name:
                        tools.add(name)
                    fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                    if isinstance(fp, str) and fp:
                        files.add(fp)

    return {
        "session_id": session_id,
        "cwd": cwd,
        "title": (title or "").strip()[:80],
        "started": started,
        "last_active": last_active,
        "skills": sorted(skills),
        "mcp_tools": sorted(mcp_tools),
        "tools": sorted(tools),
        "files": sorted(files),
        "dev_refs": dict(dev_refs),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add claude_index.py tests/test_claude_index.py
git commit -m "feat: transcript session extraction"
```

---

## Task 2: Indexer — project attribution

**Files:**
- Modify: `claude_index.py`
- Test: `tests/test_claude_index.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_claude_index.py`:
```python
from collections import Counter

from claude_index import infer_project


def test_infer_project_from_cwd_in_dev():
    name, path = infer_project(r"C:\dev\lalatine", Counter())
    assert name == "lalatine"
    assert path == r"C:\dev\lalatine"


def test_infer_project_from_content_when_run_from_root():
    name, path = infer_project(r"C:\Claude-AI", Counter({"daios-portal": 9, "lalatine": 2}))
    assert name == "daios-portal"
    assert path == r"C:\dev\daios-portal"


def test_infer_project_catchall_workspace_root():
    name, path = infer_project(r"C:\Claude-AI", Counter())
    assert name == "workspace-root"
    assert path == r"C:\Claude-AI"


def test_infer_project_catchall_home():
    name, _ = infer_project(r"C:\Users\bencu", Counter())
    assert name == "home"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -k infer_project -v`
Expected: FAIL — `ImportError: cannot import name 'infer_project'`

- [ ] **Step 3: Write minimal implementation**

Add to `claude_index.py`:
```python
_CWD_DEV_RE = re.compile(r"(?i)^C:\\dev\\([^\\/]+)")


def _catchall(cwd: str | None) -> tuple[str, str]:
    if not cwd:
        return ("unknown", "")
    low = cwd.lower().rstrip("\\/")
    if low == r"c:\claude-ai":
        return ("workspace-root", cwd)
    if low == r"c:\users\bencu":
        return ("home", cwd)
    base = os.path.basename(cwd.rstrip("\\/")) or cwd
    return (base, cwd)


def infer_project(cwd: str | None, dev_refs: Counter) -> tuple[str, str]:
    """Attribute a session to a project: cwd-in-dev > most-referenced dev
    project > labeled catch-all from cwd."""
    if cwd:
        m = _CWD_DEV_RE.match(cwd.replace("/", "\\"))
        if m:
            name = m.group(1)
            return name, os.path.join(DEV_ROOT, name)
    if dev_refs:
        name = dev_refs.most_common(1)[0][0]
        return name, os.path.join(DEV_ROOT, name)
    return _catchall(cwd)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -k infer_project -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add claude_index.py tests/test_claude_index.py
git commit -m "feat: project attribution rule"
```

---

## Task 3: Indexer — incremental build_index with cache + subagent merge

**Files:**
- Modify: `claude_index.py`
- Test: `tests/test_claude_index.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_claude_index.py`:
```python
from claude_index import build_index


def test_build_index_rolls_up_and_merges_subagents(tmp_path):
    root = tmp_path / "projects"
    sess_dir = root / "C--Claude-AI"
    sub_dir = sess_dir / "uuid-1" / "subagents"
    sub_dir.mkdir(parents=True)

    _write_jsonl(sess_dir / "uuid-1.jsonl", [
        {"type": "user", "cwd": r"C:\Claude-AI", "timestamp": "2026-05-02T09:00:00Z",
         "message": {"content": "work on daios-portal"}},
        {"type": "assistant", "timestamp": "2026-05-02T09:00:01Z",
         "message": {"content": [
             {"type": "tool_use", "name": "Read",
              "input": {"file_path": r"C:\dev\daios-portal\a.html"}}]}},
    ])
    # subagent transcript that used a skill; must fold into uuid-1
    _write_jsonl(sub_dir / "agent-x.jsonl", [
        {"type": "assistant", "timestamp": "2026-05-02T09:00:02Z",
         "message": {"content": [
             {"type": "tool_use", "name": "Skill", "input": {"skill": "stamp"}}]}},
    ])

    cache = tmp_path / "cache.json"
    index = build_index(str(root), str(cache))

    assert len(index["projects"]) == 1
    proj = index["projects"][0]
    assert proj["name"] == "daios-portal"
    assert proj["session_count"] == 1
    assert "stamp" in proj["skills"]  # merged from subagent
    assert proj["last_active"] == "2026-05-02T09:00:00Z"
    assert os.path.exists(cache)


def test_build_index_reuses_cache_for_unchanged_files(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    d = root / "C--dev-lalatine"
    d.mkdir(parents=True)
    f = d / "s1.jsonl"
    _write_jsonl(f, [
        {"type": "user", "cwd": r"C:\dev\lalatine", "timestamp": "2026-05-03T08:00:00Z",
         "message": {"content": "x"}}])
    cache = tmp_path / "cache.json"
    build_index(str(root), str(cache))

    calls = {"n": 0}
    import claude_index
    real = claude_index.extract_session

    def spy(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(claude_index, "extract_session", spy)
    build_index(str(root), str(cache))  # nothing changed
    assert calls["n"] == 0  # cache hit, no re-parse
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -k build_index -v`
Expected: FAIL — `ImportError: cannot import name 'build_index'`

- [ ] **Step 3: Write minimal implementation**

Add to `claude_index.py`:
```python
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cache(cache_path: str) -> dict:
    try:
        with open(cache_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache_path: str, cache: dict) -> None:
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)


def _merge(base: dict, other: dict) -> None:
    base["skills"] = sorted(set(base["skills"]) | set(other["skills"]))
    base["mcp_tools"] = sorted(set(base["mcp_tools"]) | set(other["mcp_tools"]))
    base["tools"] = sorted(set(base["tools"]) | set(other["tools"]))
    base["files"] = sorted(set(base["files"]) | set(other["files"]))
    dr = Counter(base.get("dev_refs") or {})
    dr.update(other.get("dev_refs") or {})
    base["dev_refs"] = dict(dr)


def build_index(transcripts_root: str = TRANSCRIPTS_ROOT,
                cache_path: str = CACHE_PATH) -> dict:
    """Incrementally index all transcripts; return the project-rolled-up index."""
    cache = _load_cache(cache_path)
    new_cache: dict = {}
    primary: dict = {}          # session_id -> extraction
    subagents: list = []        # (parent_session_id, extraction)

    pattern = os.path.join(transcripts_root, "**", "*.jsonl")
    for path in glob.glob(pattern, recursive=True):
        try:
            st = os.stat(path)
        except OSError:
            continue
        cached = cache.get(path)
        if cached and cached.get("mtime") == st.st_mtime and cached.get("size") == st.st_size:
            ext = cached["extracted"]
        else:
            ext = extract_session(path)
        new_cache[path] = {"mtime": st.st_mtime, "size": st.st_size, "extracted": ext}

        if os.sep + "subagents" + os.sep in path:
            parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
            subagents.append((parent, ext))
        else:
            primary[ext["session_id"]] = ext

    for parent, ext in subagents:
        if parent in primary:
            _merge(primary[parent], ext)

    projects: dict = {}
    for ext in primary.values():
        dev_refs = Counter(ext.get("dev_refs") or {})
        name, ppath = infer_project(ext.get("cwd"), dev_refs)
        proj = projects.setdefault(name, {
            "name": name, "path": ppath, "session_count": 0,
            "last_active": None, "skills": set(), "mcp_tools": set(), "sessions": [],
        })
        proj["session_count"] += 1
        proj["skills"].update(ext["skills"])
        proj["mcp_tools"].update(ext["mcp_tools"])
        la = ext.get("last_active")
        if la and (proj["last_active"] is None or la > proj["last_active"]):
            proj["last_active"] = la
        proj["sessions"].append({k: ext[k] for k in
                                 ("session_id", "title", "started", "last_active",
                                  "skills", "files")})

    out = {"generated_at": _now_iso(), "projects": []}
    for proj in projects.values():
        proj["skills"] = sorted(proj["skills"])
        proj["mcp_tools"] = sorted(proj["mcp_tools"])
        proj["sessions"].sort(key=lambda s: s.get("last_active") or "", reverse=True)
        out["projects"].append(proj)
    out["projects"].sort(key=lambda p: p.get("last_active") or "", reverse=True)

    _save_cache(cache_path, new_cache)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -k build_index -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add claude_index.py tests/test_claude_index.py
git commit -m "feat: incremental build_index with cache and subagent merge"
```

---

## Task 4: Indexer — refresh/load + display helpers

**Files:**
- Modify: `claude_index.py`
- Test: `tests/test_claude_index.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_claude_index.py`:
```python
from datetime import datetime, timezone

from claude_index import filter_index, format_relative, load_index, refresh


def test_refresh_writes_and_load_reads(tmp_path):
    root = tmp_path / "projects"
    d = root / "C--dev-lalatine"
    d.mkdir(parents=True)
    _write_jsonl(d / "s1.jsonl", [
        {"type": "user", "cwd": r"C:\dev\lalatine", "timestamp": "2026-05-03T08:00:00Z",
         "message": {"content": "ship it"}}])
    index_path = tmp_path / "index.json"
    cache_path = tmp_path / "cache.json"

    index = refresh(str(root), str(index_path), str(cache_path))
    assert index_path.exists()
    loaded = load_index(str(index_path))
    assert loaded["projects"][0]["name"] == "lalatine"


def test_load_index_missing_returns_empty(tmp_path):
    loaded = load_index(str(tmp_path / "nope.json"))
    assert loaded == {"generated_at": None, "projects": []}


def test_format_relative():
    now = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)
    assert format_relative("2026-05-03T12:00:00Z", now) == "just now"
    assert format_relative("2026-05-03T10:00:00Z", now) == "2h ago"
    assert format_relative("2026-05-01T12:00:00Z", now) == "2d ago"
    assert format_relative(None, now) == "—"


def test_filter_index_matches_project_and_session():
    index = {"projects": [
        {"name": "daios-portal", "skills": ["stamp"], "sessions": [
            {"title": "fix vehicle links"}]},
        {"name": "lalatine", "skills": ["docx"], "sessions": [
            {"title": "email setup"}]},
    ]}
    out = filter_index(index, "vehicle")
    assert len(out["projects"]) == 1 and out["projects"][0]["name"] == "daios-portal"
    out2 = filter_index(index, "lala")
    assert len(out2["projects"]) == 1 and out2["projects"][0]["name"] == "lalatine"
    assert filter_index(index, "")["projects"] == index["projects"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -k "refresh or load_index or format_relative or filter_index" -v`
Expected: FAIL — `ImportError: cannot import name 'refresh'`

- [ ] **Step 3: Write minimal implementation**

Add to `claude_index.py`:
```python
def refresh(transcripts_root: str = TRANSCRIPTS_ROOT,
            index_path: str = INDEX_PATH,
            cache_path: str = CACHE_PATH) -> dict:
    """Build the index and write it to index_path. Returns the index."""
    index = build_index(transcripts_root, cache_path)
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2)
    return index


def load_index(index_path: str = INDEX_PATH) -> dict:
    try:
        with open(index_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"generated_at": None, "projects": []}


def format_relative(iso: str | None, now: datetime | None = None) -> str:
    if not iso:
        return "—"
    now = now or datetime.now(timezone.utc)
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    secs = (now - then).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def filter_index(index: dict, query: str) -> dict:
    q = (query or "").strip().lower()
    if not q:
        return index
    kept = []
    for proj in index.get("projects", []):
        hay = " ".join([
            proj.get("name", ""),
            " ".join(proj.get("skills", [])),
            " ".join(proj.get("mcp_tools", [])),
            " ".join(s.get("title", "") for s in proj.get("sessions", [])),
        ]).lower()
        if q in hay:
            kept.append(proj)
    return {**index, "projects": kept}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_claude_index.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Smoke-run against real transcripts (timing check)**

Run:
```bash
cd /c/dev/sysmon-widget && python -c "import time,claude_index as ci; t=time.time(); idx=ci.refresh(); print('projects:', len(idx['projects']), 'first-run sec:', round(time.time()-t,2)); t=time.time(); ci.refresh(); print('cached-run sec:', round(time.time()-t,2))"
```
Expected: prints a project count > 0; first-run a few seconds, cached-run well under 1 second. Confirms incremental cache works.

- [ ] **Step 6: Commit**

```bash
git add claude_index.py tests/test_claude_index.py
git commit -m "feat: refresh/load index and display helpers"
```

---

## Task 5: ProjectsPanel widget

**Files:**
- Create: `projects_panel.py`
- Test: `tests/test_projects_panel.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_projects_panel.py`:
```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def test_panel_constructs_hidden_and_renders_index(app, tmp_path):
    from projects_panel import ProjectsPanel

    index = {"generated_at": "2026-05-03T12:00:00Z", "projects": [
        {"name": "daios-portal", "path": r"C:\dev\daios-portal", "session_count": 2,
         "last_active": "2026-05-03T11:00:00Z", "skills": ["stamp"], "mcp_tools": [],
         "sessions": [{"title": "fix links", "last_active": "2026-05-03T11:00:00Z",
                       "skills": ["stamp"], "files": []}]},
    ]}
    panel = ProjectsPanel(index_loader=lambda: index)
    assert panel.isHidden()           # hidden by default
    panel.render_index(index)         # should not raise
    # search filter narrows to zero without crashing
    panel.search.setText("zzz-no-match")
    panel.apply_filter()
    panel.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_projects_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'projects_panel'`

- [ ] **Step 3: Write minimal implementation**

Create `projects_panel.py`:
```python
"""ProjectsPanel: hidden-by-default panel that shows the Claude project index.

Reads claude_index.json (via the indexer) and renders a searchable, scrollable
list of projects. Styled to match the sysmon neon-amber palette.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import claude_index as ci

_STYLE = """
QWidget#ProjectsPanel { background-color: #1a1612; border: 1px solid #46371c; }
QLabel { color: #ff8a40; }
QLabel#proj { color: #ffb070; font-weight: bold; }
QLabel#meta { color: #b87a3c; }
QLineEdit { background:#241c14; color:#ffb070; border:1px solid #46371c; padding:4px; }
QPushButton { background:#241c14; color:#ffb070; border:1px solid #46371c; padding:4px 10px; }
QPushButton:hover { background:#46371c; }
QScrollArea { border: none; }
"""


class ProjectsPanel(QWidget):
    def __init__(self, index_loader: Callable[[], dict] | None = None,
                 refresher: Callable[[], dict] | None = None) -> None:
        super().__init__()
        self._load = index_loader or ci.load_index
        self._refresh = refresher or ci.refresh
        self._index: dict = {"projects": []}

        self.setObjectName("ProjectsPanel")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet(_STYLE)
        self.resize(420, 520)

        outer = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects, skills, sessions…")
        self.search.textChanged.connect(self.apply_filter)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.do_refresh)
        outer.addWidget(self.search)
        outer.addWidget(refresh_btn)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._list_host)
        outer.addWidget(self._scroll)

        self.hide()

    def _clear_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def render_index(self, index: dict) -> None:
        self._clear_list()
        projects = index.get("projects", [])
        if not projects:
            self._list_layout.addWidget(QLabel("No projects found."))
            return
        for proj in projects:
            name = QLabel(f"{proj.get('name', '?')}")
            name.setObjectName("proj")
            self._list_layout.addWidget(name)
            used = ", ".join(proj.get("skills", []) + proj.get("mcp_tools", [])) or "—"
            meta = QLabel(
                f"{ci.format_relative(proj.get('last_active'))}  ·  "
                f"{proj.get('session_count', 0)} sessions  ·  {used}"
            )
            meta.setObjectName("meta")
            meta.setWordWrap(True)
            self._list_layout.addWidget(meta)
            for sess in proj.get("sessions", [])[:3]:
                title = sess.get("title") or "(untitled session)"
                row = QLabel(f"   · {ci.format_relative(sess.get('last_active'))}  {title}")
                row.setObjectName("meta")
                row.setWordWrap(True)
                self._list_layout.addWidget(row)

    def apply_filter(self) -> None:
        self.render_index(ci.filter_index(self._index, self.search.text()))

    def do_refresh(self) -> None:
        try:
            self._index = self._refresh()
        except Exception as exc:  # noqa: BLE001 - surface, never crash the widget
            self._clear_list()
            self._list_layout.addWidget(QLabel(f"Indexer error: {exc}"))
            return
        self.apply_filter()

    def open_panel(self) -> None:
        """Load (incrementally refresh) and show."""
        self.do_refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.open_panel()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/dev/sysmon-widget && python -m pytest tests/test_projects_panel.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add projects_panel.py tests/test_projects_panel.py
git commit -m "feat: ProjectsPanel widget (hidden by default, searchable)"
```

---

## Task 6: Integrate into widget.py (tray toggle + double-click)

**Files:**
- Modify: `widget.py:134-164` (add double-click handler to `TriangleTimer`)
- Modify: `widget.py:323-358` (instantiate panel, wire tray + double-click)

- [ ] **Step 1: Add a double-click callback hook to `TriangleTimer`**

In `widget.py`, inside `TriangleTimer.__init__` (after `self._drag_pos = None` on line 148), add:
```python
        self.on_double_click = None  # set by main(): callback to toggle panel
```

Then add this method to `TriangleTimer` (place it right after `mouseReleaseEvent`, around line 180):
```python
    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.on_double_click:
            self.on_double_click()
            event.accept()
```
(Drag uses single-press + move; double-click is a distinct event, so existing drag/snap behavior is preserved.)

- [ ] **Step 2: Import the panel and wire it in `main()`**

In `widget.py`, add to the imports near line 40:
```python
from projects_panel import ProjectsPanel
```

In `main()`, after `widget.show()` (line 329), add:
```python
    panel = ProjectsPanel()
    widget.on_double_click = panel.toggle
```

In the tray menu setup, immediately after `menu = QMenu()` styling block and before the snap-position loop (around line 340), add a projects toggle plus separator:
```python
    projects_action = QAction("Show / hide projects", menu)
    projects_action.triggered.connect(panel.toggle)
    menu.addAction(projects_action)
    menu.addSeparator()
```

In the `_quit` function (line 349-351), ensure the panel closes too:
```python
    def _quit() -> None:
        panel.close()
        widget.stop()
        app.quit()
```

- [ ] **Step 3: Verify the app imports and constructs without error (offscreen)**

Run:
```bash
cd /c/dev/sysmon-widget && QT_QPA_PLATFORM=offscreen python -c "import widget; from projects_panel import ProjectsPanel; print('imports OK')"
```
Expected: prints `imports OK` with no traceback.

- [ ] **Step 4: Run the full test suite**

Run: `cd /c/dev/sysmon-widget && python -m pytest -v`
Expected: PASS (all tests across both files)

- [ ] **Step 5: Manual verification (real desktop run)**

Run: `cd /c/dev/sysmon-widget && python widget.py`
Confirm:
- Triangle timer appears and behaves exactly as before (drag, snap, minute count).
- Double-clicking the triangle opens the projects panel; double-click again (or tray "Show / hide projects") hides it.
- Panel lists projects most-recent-first with last-active, session count, and skills/tools; `daios-portal`, `lalatine`, etc. appear under their real names (not just `workspace-root`).
- Search box filters the list.
- Refresh re-runs the indexer quickly (cached).
- Quit from the tray closes both windows.

- [ ] **Step 6: Commit**

```bash
git add widget.py
git commit -m "feat: wire ProjectsPanel into widget via tray toggle and double-click"
```

---

## Task 7: Docs

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the new feature**

Append to `CLAUDE.md`:
```markdown

## Claude Project Tracker

A second, hidden-by-default panel (`projects_panel.py`) rides on the same process
as the triangle timer. It shows what you've worked on across Claude Code/Cowork.

- `claude_index.py` — incremental indexer over `~/.claude/projects/**/*.jsonl`;
  writes `claude_index.json` (+ `claude_index.cache.json`). No LLM, no Qt.
- Attributes each session to a real `C:\dev\<project>` by what it touched, with
  `workspace-root` / `home` catch-all buckets otherwise.
- Open the panel: double-click the triangle, or tray → "Show / hide projects".
- The panel only does work when opened; hidden = idle.

Deferred (not built): LLM prose session summaries; direct claude.ai chat capture.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document Claude Project Tracker"
```

---

## Verification Checklist (whole feature)

- [ ] `python -m pytest -v` is green (indexer + panel).
- [ ] Smoke run reports projects > 0, cached re-run < 1s.
- [ ] `python widget.py` shows the triangle unchanged; double-click + tray toggle open/close the panel; real project names appear; search and refresh work; quit closes both.
- [ ] No second process, no second tray icon, no new always-on timer.
