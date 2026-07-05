from __future__ import annotations

import struct
from dataclasses import dataclass

TRAILER = b"\n---- Bun! ----\n"
MODULE_RECORD_SIZE = 52
POINTER_PAIR_COUNT = 6


class BunGraphError(ValueError):
    pass


@dataclass(frozen=True)
class PointerPair:
    offset: int
    size: int


@dataclass(frozen=True)
class BunModule:
    index: int
    record_offset: int
    path: str
    path_offset: int
    path_size: int
    content_offset: int
    content_size: int
    content: bytes
    raw_u32: tuple[int, ...]


@dataclass(frozen=True)
class BunGraphRewriteResult:
    section_bytes: bytes
    delta: int
    old_payload_length: int
    new_payload_length: int
    old_byte_count: int
    new_byte_count: int
    shifted_pointers: int
    validation_errors: list[str]


@dataclass(frozen=True)
class BunGraph:
    section_bytes: bytes
    declared_payload_len: int
    payload: bytes
    trailer_offset: int
    offsets_struct_offset: int
    byte_count: int
    modules_offset: int
    modules_size: int
    entry_point_id: int
    compile_exec_argv_offset: int
    compile_exec_argv_size: int
    flags: int
    module_record_size: int
    modules: tuple[BunModule, ...]
    validation_errors: list[str]

    def module_by_path(self, path: str) -> BunModule:
        matches = [module for module in self.modules if module.path == path]
        if len(matches) != 1:
            raise BunGraphError(f"module_not_found_or_not_unique:{path}")
        return matches[0]

    def replace_module_content(self, path: str, new_content: bytes) -> BunGraphRewriteResult:
        module = self.module_by_path(path)
        start = module.content_offset
        end = module.content_offset + module.content_size
        payload = bytearray(self.payload)
        payload[start:end] = new_content
        delta = len(new_content) - module.content_size
        insert_point = end
        new_modules_offset = (
            self.modules_offset + delta
            if self.modules_offset >= insert_point
            else self.modules_offset
        )
        new_offsets_struct_offset = (
            self.offsets_struct_offset + delta
            if self.offsets_struct_offset >= insert_point
            else self.offsets_struct_offset
        )
        shifted = 0
        for index in range(len(self.modules)):
            rec = new_modules_offset + index * MODULE_RECORD_SIZE
            for pair in range(POINTER_PAIR_COUNT):
                pos = rec + pair * 8
                ptr = _u32(payload, pos)
                size = _u32(payload, pos + 4)
                if ptr <= start < ptr + size:
                    struct.pack_into("<I", payload, pos + 4, size + delta)
                elif ptr >= insert_point and ptr != 0:
                    struct.pack_into("<I", payload, pos, ptr + delta)
                    shifted += 1
        struct.pack_into("<Q", payload, new_offsets_struct_offset, self.byte_count + delta)
        struct.pack_into("<I", payload, new_offsets_struct_offset + 8, new_modules_offset)
        struct.pack_into("<I", payload, new_offsets_struct_offset + 12, self.modules_size)
        struct.pack_into("<I", payload, new_offsets_struct_offset + 16, self.entry_point_id)
        argv_offset = self.compile_exec_argv_offset
        if argv_offset >= insert_point and argv_offset != 0:
            argv_offset += delta
            shifted += 1
        struct.pack_into("<I", payload, new_offsets_struct_offset + 20, argv_offset)
        struct.pack_into("<I", payload, new_offsets_struct_offset + 24, self.compile_exec_argv_size)
        struct.pack_into("<I", payload, new_offsets_struct_offset + 28, self.flags)
        section = struct.pack("<Q", self.declared_payload_len + delta) + bytes(payload)
        reparsed = parse_bun_section(section)
        return BunGraphRewriteResult(
            section_bytes=section,
            delta=delta,
            old_payload_length=self.declared_payload_len,
            new_payload_length=self.declared_payload_len + delta,
            old_byte_count=self.byte_count,
            new_byte_count=self.byte_count + delta,
            shifted_pointers=shifted,
            validation_errors=reparsed.validation_errors,
        )


def _u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _slice(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise BunGraphError("pointer_out_of_bounds")
    return data[offset : offset + size]


def parse_bun_section(section: bytes) -> BunGraph:
    if len(section) < 8:
        raise BunGraphError("section_too_short")
    declared_len = _u64(section, 0)
    if declared_len + 8 > len(section):
        raise BunGraphError("payload_length_out_of_bounds")
    payload = section[8 : 8 + declared_len]
    trailer_offset = payload.rfind(TRAILER)
    if trailer_offset < 0:
        raise BunGraphError("trailer_not_found")
    if trailer_offset + len(TRAILER) != declared_len:
        raise BunGraphError("payload_length_trailer_mismatch")
    offsets_struct_offset = trailer_offset - 32
    if offsets_struct_offset < 0:
        raise BunGraphError("offsets_struct_missing")
    byte_count = _u64(payload, offsets_struct_offset)
    modules_offset = _u32(payload, offsets_struct_offset + 8)
    modules_size = _u32(payload, offsets_struct_offset + 12)
    entry_point_id = _u32(payload, offsets_struct_offset + 16)
    argv_offset = _u32(payload, offsets_struct_offset + 20)
    argv_size = _u32(payload, offsets_struct_offset + 24)
    flags = _u32(payload, offsets_struct_offset + 28)
    if modules_size % MODULE_RECORD_SIZE != 0:
        raise BunGraphError("bun_module_table_invalid")
    module_count = modules_size // MODULE_RECORD_SIZE
    modules: list[BunModule] = []
    validation_errors: list[str] = []
    for index in range(module_count):
        rec = modules_offset + index * MODULE_RECORD_SIZE
        if rec + MODULE_RECORD_SIZE > len(payload):
            raise BunGraphError("module_record_out_of_bounds")
        fields = tuple(_u32(payload, rec + i * 4) for i in range(13))
        path_offset, path_size = fields[0], fields[1]
        content_offset, content_size = fields[2], fields[3]
        try:
            path = _slice(payload, path_offset, path_size).decode("utf-8")
            content = _slice(payload, content_offset, content_size)
        except UnicodeDecodeError as exc:
            raise BunGraphError("module_path_not_utf8") from exc
        if not path.startswith("/$bunfs/") and not path.startswith("file:///$bunfs/"):
            validation_errors.append(f"module {index} suspicious path {path!r}")
        if content_offset + content_size > byte_count:
            validation_errors.append(f"module {index} content out of byte_count")
        modules.append(
            BunModule(
                index,
                rec,
                path,
                path_offset,
                path_size,
                content_offset,
                content_size,
                content,
                fields,
            )
        )
    seen_paths: set[str] = set()
    duplicate_paths: set[str] = set()
    for module in modules:
        if module.path in seen_paths:
            duplicate_paths.add(module.path)
        seen_paths.add(module.path)
    for path in sorted(duplicate_paths):
        validation_errors.append(f"duplicate_module_path:{path}")
    return BunGraph(
        section_bytes=section,
        declared_payload_len=declared_len,
        payload=payload,
        trailer_offset=trailer_offset,
        offsets_struct_offset=offsets_struct_offset,
        byte_count=byte_count,
        modules_offset=modules_offset,
        modules_size=modules_size,
        entry_point_id=entry_point_id,
        compile_exec_argv_offset=argv_offset,
        compile_exec_argv_size=argv_size,
        flags=flags,
        module_record_size=MODULE_RECORD_SIZE,
        modules=tuple(modules),
        validation_errors=validation_errors,
    )
