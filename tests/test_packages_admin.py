import json
import tempfile

import pytest

from harnessmonkey.packages_admin import add_package, remove_package, scaffold_prompt_package


def _write_pkg(tmp_path, folder, manifest):
    pkg = tmp_path / folder
    pkg.mkdir(parents=True)
    (pkg / "manifest.json").write_text(json.dumps(manifest))
    return pkg


PATCH_MANIFEST = {
    "schemaVersion": 1, "kind": "patch", "id": "demo-patch",
    "label": "Demo", "description": "d", "patch": {"engine": "bun_graph_repack", "targets": []},
}


def test_add_copies_to_manifest_id_dir(tmp_path):
    src = _write_pkg(tmp_path, "src-folder-name", PATCH_MANIFEST)
    home = tmp_path / "home"
    result = add_package(src, "patch", home)
    assert result["ok"] is True
    assert (home / "patches" / "demo-patch" / "manifest.json").exists()
    assert any("basename" in w for w in result["warnings"])  # renamed from src-folder-name


def test_add_rejects_id_collision(tmp_path):
    home = tmp_path / "home"
    src = _write_pkg(tmp_path, "demo-patch", PATCH_MANIFEST)
    assert add_package(src, "patch", home)["ok"] is True
    again = add_package(src, "patch", home)
    assert again["ok"] is False and again["error"]["code"] == "package_exists"


def test_add_rejects_kind_mismatch(tmp_path):
    src = _write_pkg(tmp_path, "demo-patch", PATCH_MANIFEST)
    result = add_package(src, "option", tmp_path / "home")
    assert result["ok"] is False and result["error"]["code"] == "kind_mismatch"


def test_add_rejects_invalid_manifest(tmp_path):
    pkg = tmp_path / "bad"
    pkg.mkdir()
    (pkg / "manifest.json").write_text("{not json")
    result = add_package(pkg, "patch", tmp_path / "home")
    assert result["ok"] is False and result["error"]["code"] == "invalid_package"


def test_scaffold_prompt_package(tmp_path):
    md = tmp_path / "my notes.md"
    md.write_text("be helpful")
    manifest = scaffold_prompt_package(md, "my-notes", None)
    assert manifest["kind"] == "prompt" and manifest["id"] == "my-notes"
    assert manifest["prompt"] == {"mode": "append", "source": {"path": "prompt.md"}}


# --- Attack reproductions (Task 5 review round) -----------------------------


def test_add_rejects_relative_path_traversal_id_with_no_stray_writes(monkeypatch, tmp_path):
    """Manifest id '../evil-traversal-dir' must never be used to build a staging path.

    Regression for Critical-1: pre-fix, `_load_manifest` peeked the RAW (unvalidated)
    id and built `Path(tmp) / peeked_id` before validating it, so this id escaped the
    tempdir via `..` and `shutil.copytree` planted a directory one level up — leaked
    forever since it sits outside the `with tempfile.TemporaryDirectory()` scope.
    """
    # Force the module's staging tempdir to live under tmp_path so the traversal
    # target (one directory above the tempdir) is a precise, assertable location.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    manifest = dict(PATCH_MANIFEST, id="../evil-traversal-dir")
    src = _write_pkg(tmp_path, "src-folder-name", manifest)
    home = tmp_path / "home"

    result = add_package(src, "patch", home)

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_package"
    # The traversal target (tmp_path/evil-traversal-dir, one level above whatever
    # tempdir got created under tmp_path) must never have been created.
    assert not (tmp_path / "evil-traversal-dir").exists()


def test_add_rejects_absolute_path_id_with_no_stray_writes(tmp_path):
    """Manifest id set to an absolute path must not be planted at that path.

    Regression for Critical-1: `Path(tmp) / "/abs/path"` discards `tmp` entirely
    (pathlib join semantics), so pre-fix the package tree was staged directly at
    the attacker-chosen absolute path.
    """
    traversal_target = tmp_path / "abs-traversal-target"
    manifest = dict(PATCH_MANIFEST, id=str(traversal_target))
    src = _write_pkg(tmp_path, "src-folder-name", manifest)
    home = tmp_path / "home"

    result = add_package(src, "patch", home)

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_package"
    assert not traversal_target.exists()


def test_add_rejects_package_containing_symlink(tmp_path):
    """A package tree containing a symlink must be rejected, not silently ingested.

    Regression for Important-4: `shutil.copytree` dereferences symlinks by default,
    so a symlink to e.g. a secrets file would have its *content* copied into both
    the staging tempdir and the final installed package.
    """
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret-content")

    src = _write_pkg(tmp_path, "demo-patch", PATCH_MANIFEST)
    (src / "linked.txt").symlink_to(secret)
    home = tmp_path / "home"

    result = add_package(src, "patch", home)

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_package"
    installed = home / "patches" / "demo-patch"
    assert not installed.exists()
    # Belt-and-suspenders: the secret content must not have leaked anywhere under home.
    if home.exists():
        for path in home.rglob("*"):
            if path.is_file():
                assert "top-secret-content" not in path.read_text(errors="ignore")


def test_remove_refuses_profile_referenced_patch(tmp_path):
    home = tmp_path / "home"
    (home / "patches" / "p1").mkdir(parents=True)
    result = remove_package("p1", "patch", home, {"prompt": None, "patches": ["p1"], "options": []})
    assert result["ok"] is False and result["error"]["code"] == "package_in_use"
    assert (home / "patches" / "p1").exists()


def test_remove_allows_baked_in_but_not_desired(tmp_path):
    # active in the built binary but no longer in the profile -> removable
    home = tmp_path / "home"
    (home / "patches" / "p1").mkdir(parents=True)
    result = remove_package("p1", "patch", home, {"prompt": None, "patches": [], "options": []})
    assert result["ok"] is True and not (home / "patches" / "p1").exists()


def test_remove_refuses_active_prompt_and_enabled_option(tmp_path):
    home = tmp_path / "home"
    (home / "prompts" / "pr").mkdir(parents=True)
    (home / "options" / "op").mkdir(parents=True)
    profile = {"prompt": "pr", "patches": [], "options": ["op"]}
    assert remove_package("pr", "prompt", home, profile)["error"]["code"] == "package_in_use"
    assert remove_package("op", "option", home, profile)["error"]["code"] == "package_in_use"


def test_remove_missing_package(tmp_path):
    result = remove_package("nope", "patch", tmp_path / "home",
                            {"prompt": None, "patches": [], "options": []})
    assert result["ok"] is False and result["error"]["code"] == "package_missing"


def test_remove_rejects_path_traversal_id_with_no_filesystem_changes(tmp_path):
    """Regression: `remove_package` joins `package_id` into a path and then
    `shutil.rmtree`s it — an unvalidated traversal id here is worse than
    `add_package`'s known traversal bug (arbitrary directory deletion, not just
    an unwanted copy). Must gate `package_id` through phase-1's
    `validate_package_id` before any filesystem use, matching the add-* side.
    """
    home = tmp_path / "home"
    (home / "patches").mkdir(parents=True)
    outside_target = tmp_path / "evil-target"
    outside_target.mkdir()
    (outside_target / "keepme.txt").write_text("do not delete")

    result = remove_package(
        "../../evil-target",
        "patch",
        home,
        {"prompt": None, "patches": [], "options": []},
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_package"
    assert outside_target.exists()
    assert (outside_target / "keepme.txt").exists()


# --- Overwrite / refresh semantics (BUG 1: install must refresh stale packages) ----


def test_add_package_default_overwrite_false_still_refuses_clobber(tmp_path):
    """Bare add-patch (overwrite defaults False) must keep no-clobber behavior,
    even when the existing dest is stale/different content, not just identical."""
    home = tmp_path / "home"
    src = _write_pkg(tmp_path, "demo-patch", PATCH_MANIFEST)
    assert add_package(src, "patch", home)["ok"] is True

    stale_manifest = dict(PATCH_MANIFEST, label="New Label")
    src2 = _write_pkg(tmp_path, "demo-patch-v2", stale_manifest)
    result = add_package(src2, "patch", home)  # overwrite not passed -> default False

    assert result["ok"] is False
    assert result["error"]["code"] == "package_exists"
    installed = json.loads((home / "patches" / "demo-patch" / "manifest.json").read_text())
    assert installed["label"] == "Demo"  # untouched, old content intact


def test_add_package_overwrite_updates_stale_copy(tmp_path):
    home = tmp_path / "home"
    src = _write_pkg(tmp_path, "demo-patch", PATCH_MANIFEST)
    assert add_package(src, "patch", home)["ok"] is True

    new_manifest = dict(PATCH_MANIFEST, label="Refreshed Label")
    src2 = _write_pkg(tmp_path, "demo-patch-new", new_manifest)
    result = add_package(src2, "patch", home, overwrite=True)

    assert result["ok"] is True
    assert result["summary"] == "updated patch package demo-patch"
    installed = json.loads((home / "patches" / "demo-patch" / "manifest.json").read_text())
    assert installed["label"] == "Refreshed Label"


def test_add_package_overwrite_reports_unchanged_for_identical_copy(tmp_path):
    home = tmp_path / "home"
    src = _write_pkg(tmp_path, "demo-patch", PATCH_MANIFEST)
    assert add_package(src, "patch", home)["ok"] is True

    src2 = _write_pkg(tmp_path, "demo-patch-again", PATCH_MANIFEST)
    result = add_package(src2, "patch", home, overwrite=True)

    assert result["ok"] is True
    assert result["summary"] == "unchanged demo-patch"


def test_add_package_overwrite_failure_mid_update_leaves_old_intact(tmp_path, monkeypatch):
    home = tmp_path / "home"
    src = _write_pkg(tmp_path, "demo-patch", PATCH_MANIFEST)
    assert add_package(src, "patch", home)["ok"] is True

    # Folder basename must match the manifest id here so `_load_manifest` takes
    # its no-staging path -- otherwise the staging copytree (an unrelated,
    # pre-existing code path) would eat our monkeypatched failure first.
    new_manifest = dict(PATCH_MANIFEST, label="Should Not Land")
    src2 = _write_pkg(tmp_path, "src2/demo-patch", new_manifest)

    import harnessmonkey.packages_admin as packages_admin_mod

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure mid-copy")

    monkeypatch.setattr(packages_admin_mod.shutil, "copytree", _boom)

    with pytest.raises(OSError):
        add_package(src2, "patch", home, overwrite=True)

    installed = json.loads((home / "patches" / "demo-patch" / "manifest.json").read_text())
    assert installed["label"] == "Demo"  # old content still intact after failed update
    # No stray temp siblings left behind under the bucket dir.
    leftovers = [p.name for p in (home / "patches").iterdir() if p.name != "demo-patch"]
    assert leftovers == []


def test_add_renames_with_warning_when_multiple_json_files_present(tmp_path):
    """`_peek_kind_and_id` should align with `load_package_manifest`'s multi-file scan.

    `load_package_manifest` globs all `*.json` files and accepts a folder with more
    than one, provided exactly one parses+validates. The rename-with-warning path
    (source folder name != manifest id) should still work in that case rather than
    bailing out to a folder-slug mismatch.
    """
    src = tmp_path / "src-folder-name"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps(PATCH_MANIFEST))
    (src / "notes.json").write_text(json.dumps({"unrelated": True}))
    home = tmp_path / "home"

    result = add_package(src, "patch", home)

    assert result["ok"] is True
    assert (home / "patches" / "demo-patch" / "manifest.json").exists()
    assert any("basename" in w for w in result["warnings"])
