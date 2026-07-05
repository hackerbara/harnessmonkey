from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harnessmonkey.cli import main
from harnessmonkey.config import load_config
from harnessmonkey.install import (
    TargetNotPlausibleOfficial,
    _unlock_target,
    install_shim_transaction,
)
from harnessmonkey.paths import StatePaths
from harnessmonkey.repair import (
    CacheSourceRefused,
    RepairRefused,
    cache_source_action,
    repair_shim_action,
)
from harnessmonkey.source_discovery import (
    MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES,
    meets_plausible_official_size,
)
from harnessmonkey.status import classify_plausible_official_source, status_payload

# CMux incident fix (Fix 1): `classify_plausible_official_source` and every
# consumer that gates caching/repair/install-over behavior on it must refuse
# a candidate that is executable and not one of HarnessMonkey's own managed
# paths, but is too small to plausibly be the real ~230MB Claude binary --
# not just "any executable file that isn't ours" (which is exactly how an
# unrelated tool's 8KB bundled wrapper script got cached and swapped in as
# "official" on a real machine).
#
# Every other test file in this suite deliberately monkeypatches
# `source_discovery.MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES` down to 0 (see each
# file's `_tiny_plausible_official_size_floor` autouse fixture) so their
# pre-existing tiny fixture binaries don't have to become real ~50MB files.
# This file is the deliberate exception: every test here runs against the
# REAL, unpatched `MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES` constant, proving the
# actual production floor -- not a mocked-down stand-in -- really works,
# end-to-end, at every consumer.

CMUX_INCIDENT_WRAPPER_SIZE_BYTES = 8 * 1024  # the real incident's file was 8KB


def write_sparse_executable(path: Path, text: str, size: int) -> Path:
    """Write an executable fixture whose logical size is exactly `size`
    bytes: `text` as the leading bytes, then a hole out to `size` (sparse on
    filesystems that support it, e.g. APFS/ext4) -- avoids materializing
    real ~50MB of on-disk content for every large fixture in this file.
    `classify_plausible_official_source`/`meets_plausible_official_size`
    only ever `stat()` a candidate (never read/hash it) to decide
    plausibility, so a sparse file is exactly as valid a fixture for that
    decision as a real, fully-written one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    with path.open("r+b") as handle:
        handle.truncate(size)
    path.chmod(path.stat().st_mode | 0o111)
    return path


def write_small_wrapper(path: Path, text: str = "#!/bin/sh\necho cmux-wrapper\n") -> Path:
    """A fixture matching the real CMux incident: a small (8KB), genuinely
    executable, non-HarnessMonkey-managed file -- exactly the shape that
    used to be misclassified as "plausible official".
    """
    return write_sparse_executable(path, text, CMUX_INCIDENT_WRAPPER_SIZE_BYTES)


def write_large_official(path: Path, text: str = "#!/bin/sh\necho official\n") -> Path:
    """A fixture comfortably above the real size floor -- big enough to
    plausibly be the real Claude binary, without materializing anywhere
    near the real ~230MB on disk.
    """
    return write_sparse_executable(path, text, MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES + 1024 * 1024)


# -- classify_plausible_official_source: exact boundary -----------------


def test_meets_plausible_official_size_boundary(tmp_path):
    at_floor = write_sparse_executable(
        tmp_path / "at-floor", "#!/bin/sh\n", MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES
    )
    below_floor = write_sparse_executable(
        tmp_path / "below-floor", "#!/bin/sh\n", MIN_PLAUSIBLE_OFFICIAL_SIZE_BYTES - 1
    )

    assert meets_plausible_official_size(at_floor) is True
    assert meets_plausible_official_size(below_floor) is False


def test_classify_refuses_cmux_sized_wrapper(tmp_path):
    paths = StatePaths(tmp_path / ".harnessmonkey")
    wrapper = write_small_wrapper(tmp_path / "cmux-app" / "bin" / "claude")

    assert classify_plausible_official_source(wrapper, paths) is None


def test_classify_accepts_realistic_large_binary(tmp_path):
    paths = StatePaths(tmp_path / ".harnessmonkey")
    official = write_large_official(tmp_path / "official" / "claude")

    assert classify_plausible_official_source(official, paths) == official.resolve()


# -- status detection: consequence of the floor --------------------------


def seed_real_shim_target(tmp_path: Path) -> tuple[Path, Path]:
    """Install a real managed shim over a realistically large pre-existing
    binary at an external target path, using the REAL (unpatched) size
    floor throughout -- since Fix 1, install-shim itself refuses to
    install over a target too small to plausibly be real Claude.
    """
    state = tmp_path / ".harnessmonkey"
    target = tmp_path / "local-bin" / "claude"
    write_large_official(target, "#!/bin/sh\necho '2.1.199 (Claude Code)'\n")
    install_shim_transaction(target, state, dry_run=False)
    # Shim lock feature: every caller of this helper immediately unlinks
    # `target` to simulate an external replacement -- a real locked shim
    # can't be replaced that way at all (see tests/test_shim_lock.py), so
    # lift the flag here to keep those simulations exercisable; this file's
    # own focus (the size-floor classification gate) is orthogonal to the
    # lock feature.
    _unlock_target(target)
    return state, target


def test_status_does_not_flag_small_wrapper_as_official_replacement(tmp_path):
    """Pinned behavior (Fix 1 requirement 5): a too-small replacement
    candidate must not count as evidence of an official update.
    `targetReplacedByOfficial`/`detectedOfficialSha256`/
    `detectedOfficialVersion`/`rolloutRequired` all stay at their "nothing
    detected" defaults. `shimRepairAvailable` is unaffected by this fix --
    it is `not shimInstalled`, independent of whether a replacement
    classifies (pre-existing, Fix-1-unrelated semantics; see
    `status._detect_official_replacement`'s own docstring).
    """
    state, target = seed_real_shim_target(tmp_path)
    target.unlink()
    write_small_wrapper(target)

    payload = status_payload(StatePaths(state), load_config(state / "config.json"))

    assert payload["shimInstalled"] is False
    assert payload["shimPreviouslyManaged"] is True
    assert payload["targetReplacedByOfficial"] is False
    assert payload["detectedOfficialSha256"] is None
    assert payload["detectedOfficialVersion"] is None
    assert payload["rolloutRequired"] is False
    assert payload["shimRepairAvailable"] is True


def test_status_detects_replacement_by_realistic_large_official(tmp_path):
    """End-to-end proof (not mocked down) that a real replacement above the
    real floor is still correctly detected.
    """
    state, target = seed_real_shim_target(tmp_path)
    official = write_large_official(
        tmp_path / "official-source" / "versions" / "2.1.201" / "claude",
        "#!/bin/sh\necho '2.1.201 (Claude Code)'\n",
    )
    target.unlink()
    target.symlink_to(official)
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()

    payload = status_payload(StatePaths(state), load_config(state / "config.json"))

    assert payload["targetReplacedByOfficial"] is True
    assert payload["detectedOfficialSha256"] == official_sha
    assert payload["detectedOfficialVersion"] == "2.1.201"
    assert payload["shimRepairAvailable"] is True
    assert payload["rolloutRequired"] is True


# -- repair.py: cache_source_action / repair_shim_action ------------------


def test_cache_source_action_refuses_cmux_sized_wrapper(tmp_path):
    state, target = seed_real_shim_target(tmp_path)
    target.unlink()
    write_small_wrapper(target)
    paths = StatePaths(state)

    with pytest.raises(CacheSourceRefused) as exc_info:
        cache_source_action(target, state, paths)

    assert exc_info.value.code == "target_too_small"


def test_cache_source_action_accepts_realistic_large_official(tmp_path):
    state, target = seed_real_shim_target(tmp_path)
    official = write_large_official(
        tmp_path / "official-source" / "versions" / "2.1.201" / "claude"
    )
    target.unlink()
    target.symlink_to(official)
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    paths = StatePaths(state)

    result = cache_source_action(target, state, paths)

    assert result["sha256"] == official_sha


def test_repair_shim_action_refuses_cmux_sized_wrapper(tmp_path):
    state, target = seed_real_shim_target(tmp_path)
    target.unlink()
    write_small_wrapper(target)
    paths = StatePaths(state)

    with pytest.raises(RepairRefused) as exc_info:
        repair_shim_action(target, state, paths)

    assert exc_info.value.code == "target_too_small"
    # No write attempted: target is exactly the small wrapper, untouched.
    assert "HarnessMonkey" not in target.read_text()


def test_repair_shim_action_accepts_realistic_large_official(tmp_path):
    state, target = seed_real_shim_target(tmp_path)
    official = write_large_official(
        tmp_path / "official-source" / "versions" / "2.1.201" / "claude"
    )
    target.unlink()
    target.symlink_to(official)
    official_sha = hashlib.sha256(official.read_bytes()).hexdigest()
    paths = StatePaths(state)

    result = repair_shim_action(target, state, paths)

    assert result["repaired"] is True
    assert result["newOfficialSha256"] == official_sha
    assert "HarnessMonkey" in target.read_text()


# -- install.py: install-shim refusal (requirement 4) ---------------------


def test_install_shim_refuses_target_that_looks_like_cmux_wrapper(tmp_path):
    """The CMux incident itself: install-shim pointed at an unrelated small
    wrapper script must refuse outright, not cache/swap it in.
    """
    target = write_small_wrapper(tmp_path / "cmux-app" / "bin" / "claude")
    state = tmp_path / "state"

    with pytest.raises(TargetNotPlausibleOfficial):
        install_shim_transaction(target, state, dry_run=False)

    # Refusal means untouched: the wrapper is still exactly the wrapper.
    assert "cmux-wrapper" in target.read_text()
    assert not (state / "install-record.json").exists()


def test_install_shim_accepts_missing_target(tmp_path):
    """Normal first-install bootstrap case: nothing exists at the target
    yet, so there is nothing to validate -- install-shim proceeds.
    """
    target = tmp_path / "local-bin" / "claude"
    state = tmp_path / "state"

    record = install_shim_transaction(target, state, dry_run=False)

    assert "HarnessMonkey" in target.read_text()
    assert json.loads(record.read_text())["targetPath"] == str(target)


def test_install_shim_accepts_realistic_large_target(tmp_path):
    """Install-over a target that genuinely looks like a real Claude binary
    still works exactly as before.
    """
    target = write_large_official(tmp_path / "local-bin" / "claude")
    state = tmp_path / "state"

    record = install_shim_transaction(target, state, dry_run=False)

    assert "HarnessMonkey" in target.read_text()
    assert json.loads(record.read_text())["targetPath"] == str(target)


def test_install_shim_cli_refuses_cmux_sized_wrapper_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = write_small_wrapper(tmp_path / "cmux-app" / "bin" / "claude")

    assert main(["install-shim", "--target", str(target), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert payload["error"]["code"] == "target_not_plausible_official"
    assert "cmux-wrapper" in target.read_text()


def test_install_shim_cli_dry_run_refuses_cmux_sized_wrapper_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = write_small_wrapper(tmp_path / "cmux-app" / "bin" / "claude")

    assert main(["install-shim", "--target", str(target), "--json", "--dry-run"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert payload["error"]["code"] == "target_not_plausible_official"
    assert payload["dryRun"] is True
    # Dry-run means untouched, exactly like the real refusal path.
    assert "cmux-wrapper" in target.read_text()
