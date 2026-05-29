import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication, QLabel


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


_SAMPLE = {"generated_at": "2026-05-03T12:00:00Z", "projects": [
    {"name": "daios-portal", "path": r"C:\dev\daios-portal", "session_count": 2,
     "last_active": "2026-05-03T11:00:00Z", "skills": ["stamp"], "mcp_tools": [],
     "sessions": [{"title": "fix links", "last_active": "2026-05-03T11:00:00Z",
                   "skills": ["stamp"], "files": []}]},
]}


def _panel(refresher=None):
    from projects_panel import ProjectsPanel
    return ProjectsPanel(refresher=refresher or (lambda: _SAMPLE))


def test_panel_constructs_hidden_and_renders(app):
    panel = _panel()
    assert panel.isHidden()
    panel.render_index(_SAMPLE)            # should not raise
    panel.search.setText("zzz-no-match")
    panel.apply_filter()                   # zero-match path, no crash
    panel.close()


def test_do_refresh_uses_refresher_and_renders(app):
    panel = _panel()
    panel.do_refresh()                     # pulls _SAMPLE via injected refresher
    assert panel._index == _SAMPLE
    panel.close()


def test_toggle_flips_visibility(app):
    panel = _panel()
    assert not panel.isVisible()
    panel.toggle()                         # open
    assert panel.isVisible()
    panel.toggle()                         # hide
    assert not panel.isVisible()
    panel.close()


def test_indexer_error_does_not_crash(app):
    def boom():
        raise RuntimeError("kaboom")
    panel = _panel(refresher=boom)
    panel.do_refresh()                     # must NOT raise
    labels = panel._list_host.findChildren(QLabel)
    assert any("Indexer error" in lbl.text() for lbl in labels)
    panel.close()
