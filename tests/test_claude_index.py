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
    assert proj["last_active"] == "2026-05-02T09:00:01Z"
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
