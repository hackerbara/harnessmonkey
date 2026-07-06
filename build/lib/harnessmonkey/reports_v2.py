from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BuildReportV2:
    schemaVersion: int = 3
    status: str = "failed"
    automatedStatus: str = "failed"
    engine: str = "bun_graph_repack"
    sourceClaudePath: str = ""
    sourceVersion: str = ""
    sourceVersionOutput: str = ""
    sourceSha256: str = ""
    sourceSizeBytes: int = 0
    enabledPatches: list[str] = field(default_factory=list)
    packageManifestDigests: dict[str, str] = field(default_factory=dict)
    sourceIdentity: dict[str, Any] = field(default_factory=dict)
    buildInputSnapshot: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(
        default_factory=lambda: {"status": "unknown", "warnings": []}
    )
    changedModules: list[dict[str, Any]] = field(default_factory=list)
    operationsApplied: list[dict[str, Any]] = field(default_factory=list)
    bunGraphUpdates: dict[str, Any] = field(default_factory=dict)
    machoUpdates: dict[str, Any] = field(default_factory=dict)
    machoUpdateDetails: list[dict[str, Any]] = field(default_factory=list)
    verificationResults: list[dict[str, Any]] = field(default_factory=list)
    outputPath: str | None = None
    outputSha256: str | None = None
    outputSizeBytes: int | None = None
    signingResult: dict[str, Any] = field(default_factory=lambda: {"status": "skipped"})
    postSignInspection: dict[str, Any] = field(default_factory=dict)
    smokeTestResults: list[dict[str, Any]] = field(default_factory=list)
    manualSmoke: dict[str, Any] = field(
        default_factory=lambda: {"required": False, "status": "not_required"}
    )
    activationEligible: bool = False
    activationBlockers: list[str] = field(default_factory=list)
    activationStatus: str = "skipped"
    failureReason: str | None = None
    skippedGates: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")
