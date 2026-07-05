from __future__ import annotations

from pathlib import Path

from harnessmonkey.source_discovery import MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES


def tiny_binary() -> bytes:
    return b"HEAD case\"a\":{OLD_A_BODY} case\"b\":{OLD_B_BODY} TAIL"


def utf8(value: str) -> bytes:
    return value.encode("utf-8")


def plausible_official_bytes(
    marker: bytes = b"official binary", size: int = MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES
) -> bytes:
    """Bytes for a fake "real Claude binary" test fixture: `marker` followed
    by zero-padding out to `size` (default: the real, unpatched
    `MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES` floor -- see `source_discovery.py`).

    Used anywhere a test needs a fake official-source/managed-shim
    replacement/install-over target big enough to actually pass
    `classify_plausible_official_source`'s size floor (CMux-incident fix),
    without caring about the file's real content beyond `marker`.
    """
    if size < len(marker):
        raise ValueError("size must be >= len(marker)")
    return marker + b"\0" * (size - len(marker))


def write_plausible_official_executable(
    path: Path, text: str = "#!/bin/sh\necho '2.1.199 (Claude Code)'\n", *, size: int | None = None
) -> Path:
    """Write an executable fixture at `path` that is at least
    `MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES` (or `size`, if given) -- i.e. one
    that passes the CMux-incident size-floor check -- with `text` as its
    leading (never-executed, path/size-only classified) bytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = plausible_official_bytes(
        text.encode(), size if size is not None else MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES
    )
    path.write_bytes(data)
    path.chmod(path.stat().st_mode | 0o111)
    return path
