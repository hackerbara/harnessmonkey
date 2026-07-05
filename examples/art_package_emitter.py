from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harnessmonkey.binary_inspect import inspect_binary_bytes  # noqa: E402
from harnessmonkey.bun_graph import parse_bun_section  # noqa: E402
from harnessmonkey.macho import find_macho_layout  # noqa: E402

MODULE = "/$bunfs/root/src/entrypoints/cli.js"
VERSIONS_DIR = Path.home() / ".local/share/claude/versions"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_key(path: Path) -> tuple[Any, ...]:
    parts: list[Any] = []
    for part in re.split(r"([0-9]+)", path.name):
        if part.isdigit():
            parts.append(int(part))
        elif part:
            parts.append(part)
    return tuple(parts)


def newest_local_source() -> Path:
    candidates = [path for path in VERSIONS_DIR.iterdir() if path.is_file()]
    if not candidates:
        raise SystemExit(f"no Claude Code binaries found under {VERSIONS_DIR}")
    return sorted(candidates, key=version_key)[-1]


def version_slug(version: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", version).strip("-").lower()
    if not slug:
        raise SystemExit(f"cannot derive version slug from {version!r}")
    return slug


def version_output(source: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    result = subprocess.run(
        [str(source), "--version"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    output = (result.stdout.strip() or result.stderr.strip()) if result.returncode == 0 else ""
    if not output:
        raise SystemExit("source version output unavailable; pass --source-version-output")
    return output


def source_version(explicit: str | None, output: str) -> str:
    if explicit:
        return explicit
    first = output.split(maxsplit=1)[0]
    if not first:
        raise SystemExit("source version unavailable; pass --source-version")
    return first


def platform_name() -> str:
    system = platform.system().lower()
    return "darwin" if system == "darwin" else system


def arch_name() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in {"arm64", "aarch64"} else machine


def source_from_args(args: argparse.Namespace) -> tuple[Path, str, str]:
    source_arg = args.source or os.environ.get("HM_GENERATE_SOURCE")
    source = Path(source_arg).expanduser() if source_arg else newest_local_source()
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")
    output = version_output(
        source,
        args.source_version_output or os.environ.get("HM_GENERATE_SOURCE_VERSION_OUTPUT"),
    )
    version = source_version(args.source_version or os.environ.get("HM_GENERATE_SOURCE_VERSION"), output)
    return source, version, output


def module_content(raw: bytes) -> bytes:
    layout = find_macho_layout(raw)
    start = layout.bun_section.offset
    end = layout.bun_section.offset + layout.bun_section.size
    graph = parse_bun_section(raw[start:end])
    return graph.module_by_path(MODULE).content


def ensure_data_file(script_dir: Path, data_file: str, compile_script: str) -> tuple[Path, bool]:
    data_path = script_dir / data_file
    if data_path.exists():
        return data_path, False
    subprocess.run([sys.executable, compile_script], cwd=script_dir, check=True)
    if not data_path.exists():
        raise SystemExit(f"compile script did not produce {data_file}")
    return data_path, True


def build_helper(data_path: Path, helper_template: str) -> str:
    data = json.loads(data_path.read_text())
    helper = helper_template.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    if "▀" in helper or "\x1b" in helper:
        raise SystemExit("helper template must encode half-block/escape through String.fromCharCode")
    return helper


def operation_payload(spec: dict[str, Any], helper: str) -> str:
    if spec["replacement"] == "__HELPER_PLUS_EXACT__":
        return helper + spec["exact"]
    return spec["replacement"]


def generated_package_manifest(
    *,
    config: dict[str, Any],
    source: Path,
    version: str,
    version_out: str,
    source_bytes: bytes,
    module_info: dict[str, Any],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "kind": "patch",
        "id": config["package_id"],
        "label": config["label"],
        "description": config["description"],
        "packageVersion": config["package_version"],
        "compatibility": {"claudeVersions": [version]},
        "patch": {
            "engine": "bun_graph_repack",
            "targets": [
                {
                    "sourceIdentity": {
                        "claudeVersion": version,
                        "versionOutput": version_out,
                        "sha256": sha(source_bytes),
                        "sizeBytes": len(source_bytes),
                        "platform": platform_name(),
                        "arch": arch_name(),
                    },
                    "requiredEngine": "bun_graph_repack",
                    "requiredBinaryFormat": "bun_standalone_macho64",
                    "modules": [
                        {
                            "path": MODULE,
                            "contentSha256": module_info["contentSha256"],
                            "contentLength": module_info["contentLength"],
                            "operations": operations,
                        }
                    ],
                    "preconditions": [
                        {"type": "module_must_contain", "modulePath": MODULE, "value": item["exact"]}
                        for item in config["anchors"]
                    ],
                    "postconditions": config["postconditions"],
                    "manualSmoke": {"required": True, "reason": config["manual_smoke_reason"]},
                }
            ],
        },
    }


def write_output_package(
    destination: Path, manifest: dict[str, Any], payloads: dict[str, str], extra_files: dict[str, str]
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    payload_dir = destination / "payloads"
    payload_dir.mkdir(parents=True, exist_ok=True)

    expected_files = (
        {Path("patch.json")} | {Path(rel_path) for rel_path in payloads} | {Path(rel_path) for rel_path in extra_files}
    )
    for path in sorted(destination.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
            continue
        rel = path.relative_to(destination)
        if rel.name == "preview.png":
            continue
        if rel not in expected_files:
            path.unlink()

    (destination / "patch.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for rel_path, payload in payloads.items():
        path = destination / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
    for rel_path, content in extra_files.items():
        path = destination / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def emit_package(config: dict[str, Any], script_dir: Path, argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source")
    parser.add_argument("--source-version")
    parser.add_argument("--source-version-output")
    args = parser.parse_args(argv)

    source, version, version_out = source_from_args(args)
    source_bytes = source.read_bytes()
    inspect = inspect_binary_bytes(source_bytes, source_path=str(source))
    if not inspect["ok"] or inspect["validationErrors"]:
        raise SystemExit(f"unsupported source binary: {inspect['validationErrors']}")
    module_info = next((item for item in inspect["modules"] if item["path"] == MODULE), None)
    if module_info is None:
        raise SystemExit(f"module not found: {MODULE}")
    source_module = module_content(source_bytes).decode("utf-8")

    data_path, generated_data = ensure_data_file(script_dir, config["data_file"], config["compile_script"])
    try:
        helper = build_helper(data_path, config["helper_template"])
    finally:
        if generated_data:
            data_path.unlink(missing_ok=True)
    slug = version_slug(version)
    operations: list[dict[str, Any]] = []
    payloads: dict[str, str] = {}
    patched = source_module
    for index, spec in enumerate(config["anchors"], start=1):
        exact = spec["exact"]
        count = source_module.count(exact)
        if count != 1:
            raise SystemExit(f"{spec['slug']}: anchor not unique for {version} ({count})")
        payload = operation_payload(spec, helper)
        op_id = f"{config['op_prefix']}-{spec['slug']}-{slug}"
        payload_path = f"payloads/{index:02d}-{op_id}.js"
        payloads[payload_path] = payload
        operations.append(
            {
                "opId": op_id,
                "label": spec["label"],
                "type": "replace_exact",
                "exact": exact,
                "requireWithinRange": spec["requireWithinRange"],
                "oldRangeSha256": sha(exact.encode()),
                "oldRangeLength": len(exact.encode()),
                "replacement": {"path": payload_path, "sha256": sha(payload.encode())},
                "knownBehaviorChange": spec["knownBehaviorChange"],
            }
        )
        patched = patched.replace(exact, payload, 1)

    manifest = generated_package_manifest(
        config=config,
        source=source,
        version=version,
        version_out=version_out,
        source_bytes=source_bytes,
        module_info=module_info,
        operations=operations,
    )
    destination = Path(os.environ.get("HM_GENERATE_OUT", ROOT / "packages" / config["package_id"]))
    write_output_package(destination, manifest, payloads, config.get("extra_files", {}))
    print(f"wrote {destination / 'patch.json'}")
    print(f"operations: {len(operations)}")
    print(f"patched module length: {len(patched.encode())}")
    print(f"patched module sha256: {sha(patched.encode())}")
