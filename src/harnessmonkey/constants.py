"""Small shared constants with no internal dependencies.

This module exists solely to break an import cycle: `install.py` imports
from `source_discovery.py` (`meets_plausible_official_size`), so
`source_discovery.py` cannot import `OWNER_MARKER` back from `install.py`
without creating a circular import. Both modules import it from here
instead, so the literal is defined in exactly one place.
"""

from __future__ import annotations

OWNER_MARKER = "HarnessMonkey managed shim"
