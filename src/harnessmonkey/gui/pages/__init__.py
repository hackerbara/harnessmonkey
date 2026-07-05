"""Settings window page widgets, split out of `settings_window.py`.

Each module here is a small `QWidget` subclass following the same pattern
as `settings_window.py`'s Overview/Logs pages: a `render(state)` method that
only renders `MenuState`/`window_model` view-models (never re-derives
business logic), a per-page `Banner` for dismissible inline errors, and a
page-local `action = Signal(str, dict)` that `SettingsWindow` bubbles into
its own `action` signal.
"""

from __future__ import annotations
