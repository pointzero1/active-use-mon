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
