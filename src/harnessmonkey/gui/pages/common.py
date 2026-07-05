"""Small widgets/helpers shared by settings window pages."""

from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from harnessmonkey.gui.window_model import REBUILD_PENDING_MESSAGE

_SLUG_RUN = re.compile(r"[^a-z0-9]+")


class Banner(QWidget):
    """Dismissible inline error banner, one per settings page."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #a00; font-weight: bold;")
        layout.addWidget(self.label, 1)
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.clicked.connect(self.hide)
        layout.addWidget(self.dismiss_button)
        self.hide()

    def show_message(self, message: str) -> None:
        self.label.setText(message)
        self.show()


class PendingRebuildBanner(QWidget):
    """Plain-language strip: changes are saved but not active until rebuild.

    Shown on the Patches/Options pages whenever `MenuState.rebuild_required`
    is true (decided by `window_model.rebuild_pending_banner_visible`) --
    addresses the "no feedback that we need to rebuild to apply" complaint.
    `rebuild_requested` is wired straight to the same "rebuild" action id
    the Overview page's Rebuild button already emits -- there is no separate
    action for this, it's the identical command.
    """

    rebuild_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(REBUILD_PENDING_MESSAGE)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.rebuild_button = QPushButton("Rebuild")
        self.rebuild_button.clicked.connect(self.rebuild_requested.emit)
        layout.addWidget(self.rebuild_button)
        self.hide()

    def render(self, *, visible: bool, mutating_enabled: bool = True) -> None:
        self.setVisible(visible)
        self.rebuild_button.setEnabled(mutating_enabled)


def slugify(text: str) -> str:
    """Turn arbitrary text (typically a filename stem) into an id-safe slug.

    Lowercases, collapses any run of non `[a-z0-9]` characters into a single
    hyphen, and strips leading/trailing hyphens. Falls back to "prompt" for
    input that has no alphanumeric characters at all, so a slugged id is
    never empty.
    """
    slug = _SLUG_RUN.sub("-", text.strip().lower()).strip("-")
    return slug or "prompt"
