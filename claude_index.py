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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cache(cache_path: str) -> dict:
    try:
        with open(cache_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache_path: str, cache: dict) -> None:
    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except OSError:
        pass


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


def refresh(transcripts_root: str = TRANSCRIPTS_ROOT,
            index_path: str = INDEX_PATH,
            cache_path: str = CACHE_PATH) -> dict:
    """Build the index and write it to index_path atomically. Returns the index.

    A write failure (locked file, full disk) is swallowed so it can never crash
    the host widget; the previous index file is left intact on failure.
    """
    index = build_index(transcripts_root, cache_path)
    tmp = index_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2)
        os.replace(tmp, index_path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
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
