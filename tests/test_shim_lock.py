from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from harnessmonkey import install as install_module
from harnessmonkey import repair as repair_module
from harnessmonkey import source_discovery
from harnessmonkey.config import load_config
from harnessmonkey.install import (
    current_target_is_installed_shim,
    install_shim_transaction,
    restore_install_transaction,
    shim_target_is_locked,
)
from harnessmonkey.paths import StatePaths
from harnessmonkey.repair import repair_shim_action
from harnessmonkey.status import status_payload

# Evidence (controlled experiment on the user's machine, 2026-07-03/04): the
# official Claude installer's own self-heal mechanism re-asserts its symlink
# over a bare HarnessMonkey shim within ~15s of any fresh official-claude
# launch -- its own code eats the resulting EPERM silently, so sessions keep
# working the whole time, but the shim keeps getting clobbered. With
# `chflags uchg` set on the shim, fresh sessions leave it untouched; without
# it, clobbered within ~15s. Their update downloads
# (~/.local/share/claude/versions/) are unaffected either way -- this only
# ever locks the shim's own target path. See
# .superpowers/sdd/shim-lock-report.md for the full trace.

requires_chflags = pytest.mark.skipif(
    not (sys.platform == "darwin" and hasattr(os, "chflags")),
    reason="user-immutable flag (chflags/UF_IMMUTABLE) is macOS/BSD-only",
)


@pytest.fixture(autouse=True)
def _tiny_plausible_official_size_floor(monkeypatch):
    """This file's fake "official"/pre-existing target binaries are tiny
    shell-script fixtures, not real ~230MB Claude binaries. Patch the
    CMux-incident size floor down to 0 so install-shim's plausibility gate
    doesn't refuse them (see tests/test_install.py's identical fixture).
    """
    monkeypatch.setattr(source_discovery, "MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES", 0)


def make_executable(path: Path, text: str = "#!/bin/sh\necho '2.1.199 (Claude Code)'\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def seed_shim_target(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / ".harnessmonkey"
    target = tmp_path / "local-bin" / "claude"
    make_executable(target, "#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    install_shim_transaction(target, state, dry_run=False)
    return state, target


def replace_target_with_official(
    target: Path, tmp_path: Path, *, version: str = "2.1.201", name: str = "official-source"
) -> Path:
    official = make_executable(
        tmp_path / name / "versions" / version / "claude",
        f"#!/bin/sh\necho '{version} (Claude Code)'\n",
    )
    # A real locked shim can't be replaced by an external actor at all --
    # that's this whole feature's point (see test_shim_lock.py's other
    # tests). This helper simulates the "already replaced" state some tests
    # need directly, so it must lift the flag first if the seed install set
    # it, exactly like a real unattended clobber never manages to.
    install_module._unlock_target(target)
    target.unlink()
    target.symlink_to(official)
    return official


# -- install-shim: lock after write (requirement 1) --------------------------


@requires_chflags
def test_install_shim_locks_target_after_successful_swap(tmp_path):
    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    state = tmp_path / "state"

    record_path = install_shim_transaction(target, state, dry_run=False)

    assert target.stat().st_flags & stat.UF_IMMUTABLE
    record = json.loads(record_path.read_text())
    assert record["targetLocked"] is True
    assert shim_target_is_locked(target) is True


@requires_chflags
def test_reinstall_over_locked_shim_unlocks_before_write_and_relocks(tmp_path):
    """Requirement 2: install_shim_transaction must lift the flag before its
    own swap when re-installing over an existing locked shim -- otherwise the
    swap's `.replace()` raises PermissionError (UF_IMMUTABLE blocks rename()
    unconditionally until the flag is explicitly cleared, verified directly
    against this filesystem).
    """
    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    state = tmp_path / "state"

    install_shim_transaction(target, state, dry_run=False)
    assert target.stat().st_flags & stat.UF_IMMUTABLE

    record_path = install_shim_transaction(target, state, dry_run=False)

    assert "HarnessMonkey" in target.read_text()
    assert target.stat().st_flags & stat.UF_IMMUTABLE
    record = json.loads(record_path.read_text())
    assert record["targetLocked"] is True


@requires_chflags
def test_reinstall_over_locked_shim_stays_locked_while_tmp_is_written(tmp_path, monkeypatch):
    """Finding 2 (fix round): `_write_shim_to_target` must unlock
    `target_path` immediately before the swap, not before `write_shim`
    builds the replacement at its own (different) tmp path -- narrowing the
    window during which the real target sits unprotected, matching
    `repair.py`'s tighter unlock-just-before-swap placement.
    """
    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    state = tmp_path / "state"

    install_shim_transaction(target, state, dry_run=False)
    assert target.stat().st_flags & stat.UF_IMMUTABLE

    real_write_shim = install_module.write_shim
    observed: dict[str, bool] = {}

    def observing_write_shim(path, state_dir):
        observed["locked_during_write"] = install_module.shim_target_is_locked(target)
        return real_write_shim(path, state_dir)

    monkeypatch.setattr(install_module, "write_shim", observing_write_shim)

    install_shim_transaction(target, state, dry_run=False)

    assert observed["locked_during_write"] is True
    assert target.stat().st_flags & stat.UF_IMMUTABLE


def test_lock_target_is_noop_and_returns_false_on_non_mac_platform(tmp_path, monkeypatch):
    target = tmp_path / "claude"
    target.write_text("shim")

    monkeypatch.setattr(install_module.sys, "platform", "linux")

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("chflags must not be called on a non-mac platform")

    monkeypatch.setattr(install_module.os, "chflags", must_not_be_called, raising=False)

    assert install_module._lock_target(target) is False
    assert install_module._unlock_target(target) is False
    assert install_module.shim_target_is_locked(target) is False


@requires_chflags
def test_reinstall_over_locked_shim_relocks_if_swap_fails_after_unlock(tmp_path, monkeypatch):
    """Abort-path decision (requirement 2): if a re-install unlocks an
    existing HarnessMonkey-locked shim and then the swap itself fails, the
    target still holds the OLD (still ours, still intact) shim bytes --
    `Path.replace` is atomic all-or-nothing -- so it must be re-locked
    rather than left unlocked.
    """
    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    state = tmp_path / "state"

    install_shim_transaction(target, state, dry_run=False)
    assert target.stat().st_flags & stat.UF_IMMUTABLE

    real_replace = Path.replace

    def failing_replace(self, dest):
        if self.name.endswith(".harnessmonkey.tmp"):
            raise OSError("simulated swap failure")
        return real_replace(self, dest)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="simulated swap failure"):
        install_shim_transaction(target, state, dry_run=False)

    # The old shim is still there (the failed swap never touched it) and,
    # since it was ours, it's re-locked rather than left unlocked.
    assert "HarnessMonkey" in target.read_text()
    assert target.stat().st_flags & stat.UF_IMMUTABLE


def test_install_shim_reports_target_locked_false_when_chflags_fails(tmp_path, monkeypatch):
    """Requirement 4: a chflags failure must never fail the transaction --
    the shim keeps working unlocked, and the failure is reported honestly.
    """
    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    state = tmp_path / "state"

    def failing_chflags(*args, **kwargs):
        raise OSError("simulated chflags failure")

    monkeypatch.setattr(install_module.os, "chflags", failing_chflags)

    record_path = install_shim_transaction(target, state, dry_run=False)

    assert "HarnessMonkey" in target.read_text()
    record = json.loads(record_path.read_text())
    assert record["targetLocked"] is False


# -- repair-shim: lock after write, never on a reverted target ---------------


@requires_chflags
def test_repair_shim_locks_target_after_successful_swap(tmp_path, monkeypatch):
    state, target = seed_shim_target(tmp_path)
    replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)
    monkeypatch.setattr(repair_module, "REPAIR_REVERT_RECHECK_DELAY_SECONDS", 0)

    result = repair_shim_action(target, state, paths)

    assert result["repaired"] is True
    assert result["revertedImmediately"] is False
    assert result["targetLocked"] is True
    assert target.stat().st_flags & stat.UF_IMMUTABLE


def test_repair_shim_does_not_lock_target_reverted_during_recheck(tmp_path, monkeypatch):
    """Requirement 1: if the post-swap revert-recheck (commit 7d2100d) finds
    the target already reverted, there is nothing of ours left to lock --
    locking it would flag someone else's file.
    """
    state, target = seed_shim_target(tmp_path)
    replace_target_with_official(target, tmp_path)
    paths = StatePaths(state)
    monkeypatch.setattr(repair_module, "REPAIR_REVERT_RECHECK_DELAY_SECONDS", 0)

    clobber_bytes = b"#!/bin/sh\necho reclobbered-by-official-updater\n"

    def fake_sleep(seconds: float) -> None:
        target.unlink()
        target.write_bytes(clobber_bytes)
        target.chmod(target.stat().st_mode | 0o111)

    monkeypatch.setattr(repair_module, "sleep", fake_sleep)

    result = repair_shim_action(target, state, paths)

    assert result["revertedImmediately"] is True
    assert result["targetLocked"] is False
    if sys.platform == "darwin" and hasattr(os, "chflags"):
        assert not (target.stat().st_flags & stat.UF_IMMUTABLE)


# -- uninstall: lift + restore, no re-lock (requirement 6) -------------------


@requires_chflags
def test_uninstall_locked_shim_lifts_flag_and_restores_original(tmp_path):
    target = tmp_path / "claude"
    original = b"\xff\xfeoriginal-official-binary"
    target.write_bytes(original)
    target.chmod(0o755)
    state = tmp_path / "state"

    record_path = install_shim_transaction(target, state, dry_run=False)
    assert target.stat().st_flags & stat.UF_IMMUTABLE

    restored = restore_install_transaction(target, record_path, force=False)

    assert restored is True
    assert target.read_bytes() == original
    # Uninstall restores the ORIGINAL target -- it is never re-locked, since
    # that content was never ours to flag.
    assert not (target.stat().st_flags & stat.UF_IMMUTABLE)


@requires_chflags
def test_uninstall_missing_previous_type_locked_shim_removes_target(tmp_path):
    """previousType == "missing": nothing existed at target before the
    first install. Uninstalling a locked shim here must unlink cleanly
    instead of raising PermissionError.
    """
    target = tmp_path / "local-bin" / "claude"
    state = tmp_path / "state"

    record_path = install_shim_transaction(target, state, dry_run=False)
    assert target.stat().st_flags & stat.UF_IMMUTABLE

    restored = restore_install_transaction(target, record_path, force=False)

    assert restored is True
    assert not target.exists()


# -- read paths unaffected by the lock (requirement 3) -----------------------


@requires_chflags
def test_read_paths_unaffected_by_lock(tmp_path):
    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    state = tmp_path / "state"

    record_path = install_shim_transaction(target, state, dry_run=False)
    record = json.loads(record_path.read_text())
    assert target.stat().st_flags & stat.UF_IMMUTABLE

    assert current_target_is_installed_shim(target, record) is True

    paths = StatePaths(state)
    payload = status_payload(paths, load_config(paths.config_path))
    assert payload["shimInstalled"] is True
    assert payload["shimLocked"] is True


def test_status_shim_locked_false_when_not_installed(tmp_path):
    paths = StatePaths(tmp_path / "state")
    payload = status_payload(paths, load_config(paths.config_path))
    assert payload["shimInstalled"] is False
    assert payload["shimLocked"] is False


def test_shim_target_is_locked_false_on_non_mac_platform(tmp_path, monkeypatch):
    target = tmp_path / "claude"
    target.write_text("shim")
    monkeypatch.setattr(install_module.sys, "platform", "linux")
    assert install_module.shim_target_is_locked(target) is False


# -- symlink guard (finding 1, fix round): never follow a link to flag or --
# -- unflag someone else's file -----------------------------------------------


@requires_chflags
def test_lock_target_is_noop_on_symlink_to_unflagged_file(tmp_path):
    """A symlink is never our shim (we only ever write regular files), so
    `_lock_target` must bail out before ever chflags-ing through the link --
    otherwise it would set UF_IMMUTABLE on whatever the link resolves to.
    """
    destination = tmp_path / "someone-elses-file"
    destination.write_text("not ours")
    link = tmp_path / "claude"
    link.symlink_to(destination)

    assert install_module._lock_target(link) is False
    assert not (destination.stat().st_flags & stat.UF_IMMUTABLE)


@requires_chflags
def test_lock_target_is_noop_on_symlink_to_flagged_file(tmp_path):
    destination = tmp_path / "someone-elses-file"
    destination.write_text("not ours")
    os.chflags(str(destination), stat.UF_IMMUTABLE)
    link = tmp_path / "claude"
    link.symlink_to(destination)

    try:
        assert install_module._lock_target(link) is False
        assert destination.stat().st_flags & stat.UF_IMMUTABLE
    finally:
        os.chflags(str(destination), 0)


@requires_chflags
def test_shim_target_is_locked_false_on_symlink_to_unflagged_file(tmp_path):
    destination = tmp_path / "someone-elses-file"
    destination.write_text("not ours")
    link = tmp_path / "claude"
    link.symlink_to(destination)

    assert install_module.shim_target_is_locked(link) is False


@requires_chflags
def test_shim_target_is_locked_false_on_symlink_to_flagged_file(tmp_path):
    """Even though the destination genuinely carries UF_IMMUTABLE, a
    symlink can never be reported as "our shim, locked" -- our shim is
    always a regular file.
    """
    destination = tmp_path / "someone-elses-file"
    destination.write_text("not ours")
    os.chflags(str(destination), stat.UF_IMMUTABLE)
    link = tmp_path / "claude"
    link.symlink_to(destination)

    try:
        assert install_module.shim_target_is_locked(link) is False
    finally:
        os.chflags(str(destination), 0)


@requires_chflags
def test_unlock_target_is_noop_on_symlink_to_unflagged_file(tmp_path):
    destination = tmp_path / "someone-elses-file"
    destination.write_text("not ours")
    link = tmp_path / "claude"
    link.symlink_to(destination)

    assert install_module._unlock_target(link) is False
    assert not (destination.stat().st_flags & stat.UF_IMMUTABLE)


@requires_chflags
def test_unlock_target_is_noop_on_symlink_to_flagged_file(tmp_path):
    """The destination carries UF_IMMUTABLE, but the link is never ours to
    unlock -- `_unlock_target` must leave the destination's flag untouched.
    """
    destination = tmp_path / "someone-elses-file"
    destination.write_text("not ours")
    os.chflags(str(destination), stat.UF_IMMUTABLE)
    link = tmp_path / "claude"
    link.symlink_to(destination)

    try:
        assert install_module._unlock_target(link) is False
        assert destination.stat().st_flags & stat.UF_IMMUTABLE
    finally:
        os.chflags(str(destination), 0)


# -- status.py record re-read guard (finding 3, fix round) --------------------


@requires_chflags
def test_status_shim_locked_false_when_record_vanishes_between_reads(tmp_path, monkeypatch):
    """Guard: if the install record disappears (or is read as empty) between
    `_shim_is_installed`'s own read and `status_payload`'s subsequent
    `install_record_data` read -- a real, if narrow, race -- the `shimLocked`
    computation must not raise `TypeError` from `Path(None)`; it must simply
    report False.
    """
    from harnessmonkey import status as status_module

    target = tmp_path / "local-bin" / "claude"
    make_executable(target)
    state = tmp_path / "state"
    install_shim_transaction(target, state, dry_run=False)

    paths = StatePaths(state)
    install_record_path = state / "install-record.json"

    real_read_json_file = status_module._read_json_file
    calls = {"n": 0}

    def flaky_read_json_file(path):
        if path == install_record_path:
            calls["n"] += 1
            if calls["n"] > 1:
                return None
        return real_read_json_file(path)

    monkeypatch.setattr(status_module, "_read_json_file", flaky_read_json_file)

    payload = status_payload(paths, load_config(paths.config_path))

    assert payload["shimInstalled"] is True
    assert payload["shimLocked"] is False
    assert calls["n"] >= 2
