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
