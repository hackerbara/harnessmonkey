from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BuildReport:
    status: str
    sourceClaudePath: str
    sourceVersion: str
    sourceVersionOutput: str
    sourceSha256: str
    sourceSizeBytes: int
    platform: str
    arch: str
    enabledPatches: list[str]
    manifestDigests: dict[str, str]
    operationsApplied: list[dict[str, Any]] = field(default_factory=list)
    byteRanges: list[dict[str, Any]] = field(default_factory=list)
    verificationResults: list[dict[str, Any]] = field(default_factory=list)
    signingResult: dict[str, Any] = field(default_factory=lambda: {"status": "skipped"})
    smokeTestResults: list[dict[str, Any]] = field(default_factory=list)
    activationStatus: str = "skipped"
    failureReason: str | None = None
    unverifiedCandidate: bool = False

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")
