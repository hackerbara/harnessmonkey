from __future__ import annotations

import hashlib
from typing import Any

from harnessmonkey.binary_format import detect_binary_format, locate_bun_section
from harnessmonkey.bun_graph import parse_bun_section


def inspect_binary_bytes(data: bytes, *, source_path: str) -> dict[str, Any]:
    source_sha = hashlib.sha256(data).hexdigest()
    try:
        fmt = detect_binary_format(data)
        start, length = locate_bun_section(data)
        graph = parse_bun_section(data[start:start + length])
        if fmt == "macho":
            from harnessmonkey.macho import find_macho_layout
            layout = find_macho_layout(data)
            bun_segment_name = layout.bun_segment.name
            bun_section_name = layout.bun_section.name
        else:
            bun_segment_name = ""
            bun_section_name = ".bun"
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
        "format": "macho64" if fmt == "macho" else "pe64",
        "supported": True,
        "bun": {
            "segment": bun_segment_name,
            "section": bun_section_name,
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
