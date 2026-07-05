from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

MACHO_MAGIC_64_LE = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_CODE_SIGNATURE = 0x1D
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LINKEDIT_DATA_CMDS = {0x26, 0x29, 0x2B, 0x2E, 0x32, 0x33, 0x34, 0x35, 0x80000033, 0x80000034}
MACHO_SEGMENT_ALIGNMENT = 0x4000


class MachOError(ValueError):
    pass


@dataclass(frozen=True)
class Segment64:
    command_offset: int
    name: str
    vmaddr: int
    vmsize: int
    fileoff: int
    filesize: int
    nsects: int


@dataclass(frozen=True)
class Section64:
    command_offset: int
    name: str
    segname: str
    addr: int
    size: int
    offset: int


@dataclass(frozen=True)
class LinkeditData:
    command_offset: int
    dataoff: int
    datasize: int


@dataclass(frozen=True)
class MachOLayout:
    commands: tuple[tuple[int, int, int, int], ...]
    bun_segment: Segment64
    bun_section: Section64
    linkedit_segment: Segment64
    code_signature: LinkeditData


def align_up(value: int, alignment: int = MACHO_SEGMENT_ALIGNMENT) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def u64(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


def _name(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def find_macho_layout(data: bytes | bytearray) -> MachOLayout:
    if len(data) < 32 or u32(data, 0) != MACHO_MAGIC_64_LE:
        raise MachOError("unsupported_macho_magic")
    (
        _magic,
        _cputype,
        _cpusubtype,
        _filetype,
        ncmds,
        sizeofcmds,
        _flags,
        _reserved,
    ) = struct.unpack_from("<IiiIIIII", data, 0)
    commands: list[tuple[int, int, int, int]] = []
    bun_segment: Segment64 | None = None
    linkedit_segment: Segment64 | None = None
    bun_section: Section64 | None = None
    code_signature: LinkeditData | None = None
    off = 32
    end = 32 + sizeofcmds
    for index in range(ncmds):
        if off + 8 > len(data) or off >= end:
            raise MachOError("load_command_out_of_bounds")
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmdsize < 8 or off + cmdsize > len(data):
            raise MachOError("invalid_load_command_size")
        commands.append((index, off, cmd, cmdsize))
        if cmd == LC_SEGMENT_64:
            name = _name(struct.unpack_from("16s", data, off + 8)[0])
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, off + 24)
            nsects = u32(data, off + 64)
            segment = Segment64(off, name, vmaddr, vmsize, fileoff, filesize, nsects)
            if name == "__BUN":
                bun_segment = segment
            elif name == "__LINKEDIT":
                linkedit_segment = segment
            section_off = off + 72
            for section_index in range(nsects):
                so = section_off + section_index * 80
                sect_name = _name(struct.unpack_from("16s", data, so)[0])
                seg_name = _name(struct.unpack_from("16s", data, so + 16)[0])
                addr, size = struct.unpack_from("<QQ", data, so + 32)
                file_offset = u32(data, so + 48)
                section = Section64(so, sect_name, seg_name, addr, size, file_offset)
                if seg_name == "__BUN" and sect_name == "__bun":
                    bun_section = section
        elif cmd == LC_CODE_SIGNATURE:
            code_signature = LinkeditData(off, u32(data, off + 8), u32(data, off + 12))
        off += cmdsize
    if (
        bun_segment is None
        or bun_section is None
        or linkedit_segment is None
        or code_signature is None
    ):
        raise MachOError("missing_required_macho_layout")
    return MachOLayout(tuple(commands), bun_segment, bun_section, linkedit_segment, code_signature)


def _bump_u32(
    data: bytearray, pos: int, threshold: int, delta: int, field: str, updates: list[dict[str, Any]]
) -> None:
    value = u32(data, pos)
    if value >= threshold:
        struct.pack_into("<I", data, pos, value + delta)
        updates.append({"field": field, "old": value, "new": value + delta})


def shift_macho_after_bun_change(
    data: bytes | bytearray, *, insert_abs: int, delta: int, segment_delta: int | None = None
) -> tuple[bytes, list[dict[str, Any]]]:
    section_delta = delta
    segment_shift = section_delta if segment_delta is None else segment_delta
    out = bytearray(data)
    layout = find_macho_layout(out)
    updates: list[dict[str, Any]] = []
    bun = layout.bun_segment
    section = layout.bun_section
    linkedit = layout.linkedit_segment
    struct.pack_into("<Q", out, bun.command_offset + 32, bun.vmsize + segment_shift)
    struct.pack_into("<Q", out, bun.command_offset + 48, bun.filesize + segment_shift)
    struct.pack_into("<Q", out, section.command_offset + 40, section.size + section_delta)
    struct.pack_into("<Q", out, linkedit.command_offset + 24, linkedit.vmaddr + segment_shift)
    struct.pack_into("<Q", out, linkedit.command_offset + 40, linkedit.fileoff + segment_shift)
    updates.extend(
        [
            {"field": "__BUN.vmsize", "old": bun.vmsize, "new": bun.vmsize + segment_shift},
            {"field": "__BUN.filesize", "old": bun.filesize, "new": bun.filesize + segment_shift},
            {"field": "__bun.size", "old": section.size, "new": section.size + section_delta},
            {
                "field": "__LINKEDIT.vmaddr",
                "old": linkedit.vmaddr,
                "new": linkedit.vmaddr + segment_shift,
            },
            {
                "field": "__LINKEDIT.fileoff",
                "old": linkedit.fileoff,
                "new": linkedit.fileoff + segment_shift,
            },
        ]
    )
    for index, command_offset, cmd, _cmdsize in layout.commands:
        if cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            for field_index, name in enumerate(
                ["rebase_off", "bind_off", "weak_bind_off", "lazy_bind_off", "export_off"]
            ):
                _bump_u32(
                    out,
                    command_offset + 8 + field_index * 8,
                    insert_abs,
                    segment_shift,
                    f"cmd{index}.{name}",
                    updates,
                )
        elif cmd == LC_SYMTAB:
            _bump_u32(
                out, command_offset + 8, insert_abs, segment_shift, f"cmd{index}.symoff", updates
            )
            _bump_u32(
                out, command_offset + 16, insert_abs, segment_shift, f"cmd{index}.stroff", updates
            )
        elif cmd == LC_DYSYMTAB:
            for rel, name in [
                (32, "tocoff"),
                (40, "modtaboff"),
                (48, "extrefsymoff"),
                (56, "indirectsymoff"),
                (64, "extreloff"),
                (72, "locreloff"),
            ]:
                _bump_u32(
                    out,
                    command_offset + rel,
                    insert_abs,
                    segment_shift,
                    f"cmd{index}.{name}",
                    updates,
                )
        elif cmd == LC_CODE_SIGNATURE:
            _bump_u32(
                out,
                command_offset + 8,
                insert_abs,
                segment_shift,
                "LC_CODE_SIGNATURE.dataoff",
                updates,
            )
        elif cmd in LINKEDIT_DATA_CMDS:
            _bump_u32(
                out, command_offset + 8, insert_abs, segment_shift, f"cmd{index}.dataoff", updates
            )
    return bytes(out), updates


def macho_alignment_errors(
    layout: MachOLayout, alignment: int = MACHO_SEGMENT_ALIGNMENT
) -> list[str]:
    checks = {
        "__BUN.fileoff": layout.bun_segment.fileoff,
        "__BUN.filesize": layout.bun_segment.filesize,
        "__BUN.vmsize": layout.bun_segment.vmsize,
        "__LINKEDIT.fileoff": layout.linkedit_segment.fileoff,
        "__LINKEDIT.vmaddr": layout.linkedit_segment.vmaddr,
    }
    return [f"unaligned:{field}:{value}" for field, value in checks.items() if value % alignment]
