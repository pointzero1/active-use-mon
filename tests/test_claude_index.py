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
