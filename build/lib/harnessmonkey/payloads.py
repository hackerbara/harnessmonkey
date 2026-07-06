from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from typing import Any


class PayloadError(ValueError):
    pass


def decode_payload_text(text: str, encoding: str) -> bytes:
    if encoding == "utf-8":
        return text.encode("utf-8")
    if encoding == "base64":
        return base64.b64decode(text.encode("ascii"), validate=True)
    raise PayloadError(f"unsupported payload encoding: {encoding}")


def load_payload_bytes(ref: Any, package_dir: Path | None) -> bytes:
    if ref.inline is not None:
        return decode_payload_text(ref.inline, ref.encoding)
    if ref.path is None or ref.sha256 is None:
        raise PayloadError("external payload requires path and sha256")
    if package_dir is None:
        raise PayloadError("external payload requires package_dir")
    path = (package_dir / ref.path).resolve()
    root = package_dir.resolve()
    if root not in path.parents and path != root:
        raise PayloadError(f"payload path escapes package directory: {ref.path}")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != ref.sha256:
        raise PayloadError(f"sha256 mismatch for {ref.path}: expected {ref.sha256}, got {actual}")
    return data
