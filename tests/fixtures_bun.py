from __future__ import annotations

import struct
from dataclasses import dataclass

TRAILER = b"\n---- Bun! ----\n"
MACHO_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_CODE_SIGNATURE = 0x1D
CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_ARM64_ALL = 0
MH_EXECUTE = 2

MODULE_PATH_0 = "/$bunfs/root/src/entrypoints/cli.js"
MODULE_PATH_1 = "/$bunfs/root/src/other.js"
MODULE_0 = b"function render(){OLD_RENDER}\nfunction after(){return 1}\n"
MODULE_1 = b"export const other = true;\n"


@dataclass(frozen=True)
class FixtureOffsets:
    bun_fileoff: int
    bun_size: int
    linkedit_fileoff: int
    code_signature_offset: int
    module0_content_offset: int
    module1_content_offset: int


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def u64(value: int) -> bytes:
    return struct.pack("<Q", value)


def pad_name(value: bytes) -> bytes:
    return value + (b"\0" * (16 - len(value)))


def module_record(path_off: int, path_len: int, content_off: int, content_len: int) -> bytes:
    pairs = [
        (path_off, path_len),
        (content_off, content_len),
        (0, 0),
        (0, 0),
        (0, 0),
        (0, 0),
    ]
    raw = b"".join(u32(off) + u32(size) for off, size in pairs)
    return raw + u32(0x00030201)


def build_payload() -> tuple[bytes, FixtureOffsets]:
    path0 = MODULE_PATH_0.encode("utf-8")
    path1 = MODULE_PATH_1.encode("utf-8")
    chunks = bytearray()
    path0_off = len(chunks)
    chunks.extend(path0)
    content0_off = len(chunks)
    chunks.extend(MODULE_0)
    path1_off = len(chunks)
    chunks.extend(path1)
    content1_off = len(chunks)
    chunks.extend(MODULE_1)
    modules_offset = len(chunks)
    records = module_record(path0_off, len(path0), content0_off, len(MODULE_0))
    records += module_record(path1_off, len(path1), content1_off, len(MODULE_1))
    chunks.extend(records)
    byte_count = len(chunks)
    chunks.extend(u64(byte_count))
    chunks.extend(u32(modules_offset))
    chunks.extend(u32(len(records)))
    chunks.extend(u32(0))
    chunks.extend(u32(0))
    chunks.extend(u32(0))
    chunks.extend(u32(0))
    chunks.extend(TRAILER)
    payload = bytes(chunks)
    return u64(len(payload)) + payload, FixtureOffsets(
        bun_fileoff=0,
        bun_size=0,
        linkedit_fileoff=0,
        code_signature_offset=0,
        module0_content_offset=content0_off,
        module1_content_offset=content1_off,
    )


def segment_command(
    segname: bytes, vmaddr: int, vmsize: int, fileoff: int, filesize: int, sections: list[bytes]
) -> bytes:
    cmdsize = 72 + 80 * len(sections)
    return b"".join(
        [
            u32(LC_SEGMENT_64),
            u32(cmdsize),
            pad_name(segname),
            u64(vmaddr),
            u64(vmsize),
            u64(fileoff),
            u64(filesize),
            u32(7),
            u32(5),
            u32(len(sections)),
            u32(0),
            *sections,
        ]
    )


def section(sectname: bytes, segname: bytes, addr: int, size: int, offset: int) -> bytes:
    return b"".join(
        [
            pad_name(sectname),
            pad_name(segname),
            u64(addr),
            u64(size),
            u32(offset),
            u32(0),
            u32(0),
            u32(0),
            u32(0),
            u32(0),
            u32(0),
            u32(0),
        ]
    )


def code_signature_command(dataoff: int, datasize: int) -> bytes:
    return u32(LC_CODE_SIGNATURE) + u32(16) + u32(dataoff) + u32(datasize)


def build_macho_fixture() -> tuple[bytes, FixtureOffsets]:
    bun_section, partial = build_payload()
    bun_fileoff = 0x4000
    linkedit_fileoff = 0x8000
    code_sig_size = 128
    code_sig_offset = linkedit_fileoff
    bun_size = len(bun_section)
    text = segment_command(b"__TEXT", 0x100000000, 0x4000, 0, 0x4000, [])
    bun_sec = section(b"__bun", b"__BUN", 0x100004000, bun_size, bun_fileoff)
    bun = segment_command(b"__BUN", 0x100004000, bun_size, bun_fileoff, bun_size, [bun_sec])
    linkedit = segment_command(
        b"__LINKEDIT", 0x100008000, code_sig_size, linkedit_fileoff, code_sig_size, []
    )
    code_sig = code_signature_command(code_sig_offset, code_sig_size)
    load_commands = text + bun + linkedit + code_sig
    ncmds = 4
    header = struct.pack(
        "<IiiIIIII",
        MACHO_MAGIC_64,
        CPU_TYPE_ARM64,
        CPU_SUBTYPE_ARM64_ALL,
        MH_EXECUTE,
        ncmds,
        len(load_commands),
        0,
        0,
    )
    prefix = header + load_commands
    data = bytearray(prefix)
    data.extend(b"\0" * (bun_fileoff - len(data)))
    data.extend(bun_section)
    data.extend(b"\0" * (linkedit_fileoff - len(data)))
    data.extend(b"C" * code_sig_size)
    return bytes(data), FixtureOffsets(
        bun_fileoff=bun_fileoff,
        bun_size=bun_size,
        linkedit_fileoff=linkedit_fileoff,
        code_signature_offset=code_sig_offset,
        module0_content_offset=partial.module0_content_offset,
        module1_content_offset=partial.module1_content_offset,
    )


def align_up(value: int, alignment: int = 0x4000) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def build_aligned_macho_fixture() -> tuple[bytes, FixtureOffsets]:
    bun_section, partial = build_payload()
    bun_fileoff = 0x4000
    bun_section_size = len(bun_section)
    bun_segment_size = align_up(bun_section_size)
    linkedit_fileoff = bun_fileoff + bun_segment_size
    code_sig_size = 128
    code_sig_offset = linkedit_fileoff
    text = segment_command(b"__TEXT", 0x100000000, 0x4000, 0, 0x4000, [])
    bun_sec = section(b"__bun", b"__BUN", 0x100004000, bun_section_size, bun_fileoff)
    bun = segment_command(
        b"__BUN", 0x100004000, bun_segment_size, bun_fileoff, bun_segment_size, [bun_sec]
    )
    linkedit = segment_command(
        b"__LINKEDIT", 0x100004000 + bun_segment_size, code_sig_size,
        linkedit_fileoff, code_sig_size, []
    )
    code_sig = code_signature_command(code_sig_offset, code_sig_size)
    load_commands = text + bun + linkedit + code_sig
    header = struct.pack(
        "<IiiIIIII",
        MACHO_MAGIC_64,
        CPU_TYPE_ARM64,
        CPU_SUBTYPE_ARM64_ALL,
        MH_EXECUTE,
        4,
        len(load_commands),
        0,
        0,
    )
    data = bytearray(header + load_commands)
    data.extend(b"\0" * (bun_fileoff - len(data)))
    data.extend(bun_section)
    data.extend(b"P" * (bun_segment_size - bun_section_size))
    data.extend(b"C" * code_sig_size)
    return bytes(data), FixtureOffsets(
        bun_fileoff=bun_fileoff,
        bun_size=bun_section_size,
        linkedit_fileoff=linkedit_fileoff,
        code_signature_offset=code_sig_offset,
        module0_content_offset=partial.module0_content_offset,
        module1_content_offset=partial.module1_content_offset,
    )
