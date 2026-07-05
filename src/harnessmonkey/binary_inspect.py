from __future__ import annotations

import hashlib
from typing import Any

from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.macho import find_macho_layout


def inspect_binary_bytes(data: bytes, *, source_path: str) -> dict[str, Any]:
    source_sha = hashlib.sha256(data).hexdigest()
    try:
        layout = find_macho_layout(data)
        start = layout.bun_section.offset
        end = layout.bun_section.offset + layout.bun_section.size
        graph = parse_bun_section(data[start:end])
    except Exception as exc:
        return {
            "schemaVersion": 1,
            "ok": False,
            "sourcePath": source_path,
            "sourceSha256": source_sha,
            "sourceSizeBytes": len(data),
            "format": "unknown",
            "supported": False,
            "bun": None,
            "modules": [],
            "validationErrors": [f"{type(exc).__name__}: {exc}"],
        }
    return {
        "schemaVersion": 1,
        "ok": not graph.validation_errors,
        "sourcePath": source_path,
        "sourceSha256": source_sha,
        "sourceSizeBytes": len(data),
        "format": "macho64",
        "supported": True,
        "bun": {
            "segment": layout.bun_segment.name,
            "section": layout.bun_section.name,
            "payloadLength": graph.declared_payload_len,
            "trailerOffset": graph.trailer_offset,
            "moduleRecordSize": graph.module_record_size,
            "moduleCount": len(graph.modules),
            "entryPointId": graph.entry_point_id,
        },
        "modules": [
            {
                "index": module.index,
                "path": module.path,
                "contentLength": module.content_size,
                "contentSha256": hashlib.sha256(module.content).hexdigest(),
            }
            for module in graph.modules
        ],
        "validationErrors": graph.validation_errors,
    }
