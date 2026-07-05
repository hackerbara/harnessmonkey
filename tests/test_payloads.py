from __future__ import annotations

import hashlib

import pytest

from harnessmonkey.manifest_v2 import PayloadRefV2
from harnessmonkey.payloads import PayloadError, load_payload_bytes


def test_inline_payload_utf8():
    assert load_payload_bytes(PayloadRefV2(inline="hello", encoding="utf-8"), None) == b"hello"


def test_inline_payload_base64():
    assert load_payload_bytes(PayloadRefV2(inline="aGVsbG8=", encoding="base64"), None) == b"hello"


def test_external_payload_requires_matching_sha(tmp_path):
    payload = tmp_path / "payload.js"
    payload.write_bytes(b"replacement")
    sha = hashlib.sha256(b"replacement").hexdigest()
    ref = PayloadRefV2(path="payload.js", sha256=sha, encoding="utf-8")
    assert load_payload_bytes(ref, tmp_path) == b"replacement"


def test_external_payload_rejects_sha_mismatch(tmp_path):
    payload = tmp_path / "payload.js"
    payload.write_bytes(b"replacement")
    ref = PayloadRefV2(path="payload.js", sha256="0" * 64, encoding="utf-8")
    with pytest.raises(PayloadError, match="sha256 mismatch"):
        load_payload_bytes(ref, tmp_path)


def test_external_payload_rejects_path_escape(tmp_path):
    outside = tmp_path.parent / "outside-payload.js"
    outside.write_bytes(b"replacement")
    sha = hashlib.sha256(b"replacement").hexdigest()
    ref = PayloadRefV2(path="../outside-payload.js", sha256=sha, encoding="utf-8")
    with pytest.raises(PayloadError, match="escapes package directory"):
        load_payload_bytes(ref, tmp_path)
