from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harnessmonkey import source_discovery
from harnessmonkey.install import (
    _unlock_target,
    install_shim_transaction,
    restore_install_transaction,
    use_official,
)
from harnessmonkey.shim import render_shim_script


@pytest.fixture(autouse=True)
def _tiny_plausible_official_size_floor(monkeypatch):
    """This file's fake "previous"/pre-existing target binaries are tiny
    fixtures, not real ~230MB Claude binaries. Patch the CMux-incident size
    floor (`source_discovery.MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES`) down to 0
    (no floor) so install-shim's new plausibility gate (Fix 1, requirement
    4) doesn't refuse those fixtures here -- the real, unpatched 50MB floor
    is exercised end-to-end by tests/test_plausible_official_size_floor.py.
    """
    monkeypatch.setattr(source_discovery, "MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES", 0)


def test_install_records_previous_symlink_and_owner(tmp_path):
    target = tmp_path / "claude"
    previous = tmp_path / "official"
    previous.write_text("official")
    target.symlink_to(previous)
    record = install_shim_transaction(target, tmp_path / "state", dry_run=False)
    assert target.exists()
    assert "HarnessMonkey" in target.read_text()
    raw = json.loads(record.read_text())
    assert raw["targetPath"] == str(target)
    assert raw["previousType"] == "symlink"


def test_install_caches_previous_resolved_source_binary(tmp_path):
    target = tmp_path / "bin" / "claude"
    official = tmp_path / "versions" / "2.1.199"
    official.parent.mkdir(parents=True)
    official.write_bytes(b"official binary")
    official.chmod(0o755)
    target.parent.mkdir()
    target.symlink_to(official)
    state = tmp_path / "state"

    record = install_shim_transaction(target, state, dry_run=False)

    raw = json.loads(record.read_text())
    assert raw["sourcePath"] == str(official.resolve())
    cache_path = Path(raw["previousSourceCachePath"])
    assert cache_path.is_file()
    assert cache_path.read_bytes() == b"official binary"
    assert cache_path.stat().st_mode & 0o111
    assert raw["previousSourceSha256"] == hashlib.sha256(b"official binary").hexdigest()
    assert raw["previousSourceSizeBytes"] == len(b"official binary")


def test_restore_refuses_without_record(tmp_path):
    target = tmp_path / "claude"
    target.write_text(render_shim_script(str(tmp_path / "state")))
    assert restore_install_transaction(target, tmp_path / "missing.json", force=False) is False


def test_use_official_points_current_symlink(tmp_path):
    current = tmp_path / "current"
    official = tmp_path / "official"
    official.write_text("official")
    use_official(current, official)
    assert current.resolve() == official.resolve()


def test_restore_preserves_binary_file_bytes_and_mode(tmp_path):
    target = tmp_path / "claude"
    original = b"\xff\xfe\x00binary"
    target.write_bytes(original)
    target.chmod(0o755)
    record = install_shim_transaction(target, tmp_path / "state", dry_run=False)
    assert restore_install_transaction(target, record, force=False) is True
    assert target.read_bytes() == original
    assert target.stat().st_mode & 0o777 == 0o755


def test_restore_refuses_if_current_target_is_not_managed_shim(tmp_path):
    target = tmp_path / "claude"
    target.write_text("official")
    record = install_shim_transaction(target, tmp_path / "state", dry_run=False)
    # Shim lock feature: lift the flag before directly overwriting the
    # installed shim to simulate "someone else changed this" -- a real
    # locked shim can't be clobbered this way at all (see
    # tests/test_shim_lock.py); this keeps the pre-existing scenario here
    # exercisable.
    _unlock_target(target)
    target.write_text("someone else changed this")
    assert restore_install_transaction(target, record, force=False) is False
    assert target.read_text() == "someone else changed this"


def test_restore_file_record_does_not_follow_current_symlink(tmp_path):
    target = tmp_path / "claude"
    linked = tmp_path / "official"
    linked.write_bytes(b"official")
    target.write_bytes(b"previous")
    record = install_shim_transaction(target, tmp_path / "state", dry_run=False)
    # Shim lock feature: lift the flag before directly manipulating the
    # installed shim to simulate "someone else changed this" -- a real
    # locked shim can't be clobbered this way at all (see
    # tests/test_shim_lock.py); this keeps the pre-existing scenario here
    # exercisable.
    _unlock_target(target)
    target.unlink()
    target.symlink_to(linked)
    assert restore_install_transaction(target, record, force=True) is True
    assert linked.read_bytes() == b"official"
    assert target.read_bytes() == b"previous"
    assert not target.is_symlink()


def test_restore_refuses_record_for_different_target(tmp_path):
    target = tmp_path / "claude"
    other = tmp_path / "other-claude"
    target.write_text("official")
    record = install_shim_transaction(target, tmp_path / "state", dry_run=False)
    assert restore_install_transaction(other, record, force=False) is False


def test_dry_run_does_not_write_record_or_state(tmp_path):
    target = tmp_path / "claude"
    target.write_text("official")
    record = install_shim_transaction(target, tmp_path / "state", dry_run=True)
    assert record == tmp_path / "state" / "install-record.json"
    assert not record.exists()
    assert not (tmp_path / "state").exists()
    assert target.read_text() == "official"


def test_install_writes_record_before_replacing_target(tmp_path, monkeypatch):
    target = tmp_path / "claude"
    target.write_text("official")
    calls = []
    real_replace = Path.replace

    def tracking_replace(self, target_path):
        calls.append((self, target_path, (tmp_path / "state" / "install-record.json").exists()))
        return real_replace(self, target_path)

    monkeypatch.setattr(Path, "replace", tracking_replace)
    install_shim_transaction(target, tmp_path / "state", dry_run=False)
    assert calls
    assert calls[0][2] is True


def test_reinstall_preserves_source_path_from_existing_managed_record(tmp_path):
    target = tmp_path / "bin" / "claude"
    official = tmp_path / "versions" / "2.1.199"
    official.parent.mkdir(parents=True)
    official.write_bytes(b"official binary")
    official.chmod(0o755)
    target.parent.mkdir()
    target.symlink_to(official)
    state = tmp_path / "state"

    record = install_shim_transaction(target, state, dry_run=False)
    first = json.loads(record.read_text())
    assert first["sourcePath"] == str(official.resolve())

    second_record = install_shim_transaction(target, state, dry_run=False)
    second = json.loads(second_record.read_text())

    assert second["sourcePath"] == str(official.resolve())
