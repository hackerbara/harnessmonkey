"""PE32+ container parsing for Bun standalone Windows binaries.

Sibling to macho.py. On Windows the Bun module-graph payload lives in a PE
section named `.bun`, always the last section in the file: [u64 LE length]
[payload][zero-pad to file_alignment]. Because it is last-in-file, resizing
it moves nothing else — there is no analog to Mach-O's __LINKEDIT shifting.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from harnessmonkey.bun_graph import parse_bun_section
from harnessmonkey.repack import RepackResult

PE_MAGIC = b"PE\x00\x00"
PE32PLUS_MAGIC = 0x020B
MACHINE_AMD64 = 0x8664
SECURITY_DIR_INDEX = 4
FORCE_INTEGRITY = 0x0080


class PEError(ValueError):
    pass


@dataclass(frozen=True)
class PESection:
    index: int
    name: str
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_pointer: int


@dataclass(frozen=True)
class PELayout:
    e_lfanew: int
    opt_offset: int
    section_table_offset: int
    num_sections: int
    file_alignment: int
    section_alignment: int
    sections: tuple[PESection, ...]
    bun_section: PESection
    security_rva: int
    security_size: int
    checksum_offset: int
    dll_characteristics_offset: int
    size_of_image_offset: int


def _u16(data, off): return struct.unpack_from("<H", data, off)[0]
def _u32(data, off): return struct.unpack_from("<I", data, off)[0]


def find_pe_layout(data: bytes | bytearray) -> PELayout:
    if len(data) < 0x40 or data[0:2] != b"MZ":
        raise PEError("not_a_pe_missing_dos_magic")
    e_lfanew = _u32(data, 0x3C)
    if e_lfanew + 24 > len(data) or data[e_lfanew:e_lfanew + 4] != PE_MAGIC:
        raise PEError("not_a_pe_missing_signature")
    machine = _u16(data, e_lfanew + 4)
    num_sections = _u16(data, e_lfanew + 6)
    size_opt = _u16(data, e_lfanew + 20)
    opt = e_lfanew + 24
    security_dir_offset = opt + 112 + SECURITY_DIR_INDEX * 8
    if opt + size_opt > len(data) or security_dir_offset + 8 > len(data):
        raise PEError("truncated_pe_header")
    if _u16(data, opt) != PE32PLUS_MAGIC:
        raise PEError("unsupported_optional_header_not_pe32plus")
    if machine != MACHINE_AMD64:
        raise PEError(f"unsupported_machine:0x{machine:04x}")

    file_alignment = _u32(data, opt + 36)
    section_alignment = _u32(data, opt + 32)
    checksum_offset = opt + 64
    dll_characteristics_offset = opt + 70
    size_of_image_offset = opt + 56
    security_rva = _u32(data, security_dir_offset)
    security_size = _u32(data, security_dir_offset + 4)

    st = opt + size_opt
    if st + num_sections * 40 > len(data):
        raise PEError("truncated_pe_header")
    sections = []
    for i in range(num_sections):
        off = st + i * 40
        name = data[off:off + 8].rstrip(b"\x00").decode("ascii", "replace")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, off + 8)
        sections.append(PESection(i, name, vsize, vaddr, rawsize, rawptr))

    bun = next((s for s in sections if s.name == ".bun"), None)
    if bun is None:
        raise PEError("missing_bun_section")
    if bun.index != num_sections - 1:
        raise PEError("bun_section_not_last")
    if bun.raw_pointer + bun.raw_size != len(data) and security_rva == 0:
        # With Authenticode stripped/absent, .bun raw data must reach EOF.
        raise PEError("bun_section_not_end_of_file")

    return PELayout(
        e_lfanew=e_lfanew,
        opt_offset=opt,
        section_table_offset=st,
        num_sections=num_sections,
        file_alignment=file_alignment,
        section_alignment=section_alignment,
        sections=tuple(sections),
        bun_section=bun,
        security_rva=security_rva,
        security_size=security_size,
        checksum_offset=checksum_offset,
        dll_characteristics_offset=dll_characteristics_offset,
        size_of_image_offset=size_of_image_offset,
    )


def pe_checksum(buf: bytes) -> int:
    """Microsoft PE image checksum. Caller must zero the CheckSum field first."""
    n = len(buf)
    words = n // 2
    total = sum(struct.unpack_from(f"<{words}H", buf, 0))
    if n & 1:
        total += buf[-1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (total + n) & 0xFFFFFFFF


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def strip_authenticode(data: bytearray, layout: PELayout) -> bytearray:
    """Remove the Authenticode certificate: zero DataDirectory[4], clear
    FORCE_INTEGRITY, and truncate the trailing cert blob. Returns a new
    bytearray. No-op (copy) if no security directory is present."""
    out = bytearray(data)
    if layout.security_rva == 0:
        return out
    # DataDirectory[4] (SECURITY) rva is a *file offset*, not an RVA, per PE spec.
    cert_offset = layout.security_rva
    struct.pack_into("<II", out, layout.opt_offset + 112 + SECURITY_DIR_INDEX * 8, 0, 0)
    dll = _u16(out, layout.dll_characteristics_offset)
    struct.pack_into("<H", out, layout.dll_characteristics_offset, dll & ~FORCE_INTEGRITY)
    del out[cert_offset:]
    return out


def repack_changed_modules(source: bytes, changed_modules: dict[str, bytes]) -> RepackResult:
    if not changed_modules:
        raise ValueError("changed_modules_required")

    layout = find_pe_layout(source)
    # 1. Strip Authenticode first so .bun is last-in-file for resizing.
    data = strip_authenticode(bytearray(source), layout)
    layout = find_pe_layout(data)  # re-derive after truncation

    bun = layout.bun_section
    section = bytes(data[bun.raw_pointer:bun.raw_pointer + bun.raw_size])
    # The section raw_size is file-aligned and may exceed [u64 len][payload];
    # slice to the declared logical section so parse_bun_section validates.
    declared = struct.unpack_from("<Q", section, 0)[0]
    logical = section[: 8 + declared]

    graph = parse_bun_section(logical)
    original_order = {m.path: m.content_offset for m in graph.modules}
    total_delta = 0
    shifted_pointers = 0
    current = logical
    for path in sorted(changed_modules, key=lambda p: original_order[p]):
        graph = parse_bun_section(current)
        rewrite = graph.replace_module_content(path, changed_modules[path])
        if rewrite.validation_errors:
            raise ValueError(f"bun_graph_validation_failed:{rewrite.validation_errors}")
        current = rewrite.section_bytes
        total_delta += rewrite.delta
        shifted_pointers += rewrite.shifted_pointers

    new_logical_len = len(current)
    new_raw_size = _align_up(new_logical_len, layout.file_alignment)
    new_section = current + b"\x00" * (new_raw_size - new_logical_len)

    out = bytearray(data[: bun.raw_pointer])
    out.extend(new_section)

    # Fix the .bun section header: raw size + virtual size; ptr/vaddr unchanged.
    sect_off = layout.section_table_offset + bun.index * 40
    struct.pack_into("<I", out, sect_off + 8, new_logical_len)   # VirtualSize
    struct.pack_into("<I", out, sect_off + 16, new_raw_size)     # SizeOfRawData

    # Fix SizeOfImage = align_up(bun.vaddr + new virtual size, section_alignment).
    new_size_of_image = _align_up(bun.virtual_address + new_logical_len, layout.section_alignment)
    struct.pack_into("<I", out, layout.size_of_image_offset, new_size_of_image)

    # Recompute PE checksum (zero the field first).
    struct.pack_into("<I", out, layout.checksum_offset, 0)
    checksum = pe_checksum(bytes(out))
    struct.pack_into("<I", out, layout.checksum_offset, checksum)

    pe_updates = {
        "authenticodeStripped": layout.security_rva == 0 and source != bytes(data),
        "bunSectionOldRawSize": bun.raw_size,
        "bunSectionNewRawSize": new_raw_size,
        "sizeOfImage": new_size_of_image,
        "checksum": checksum,
        "shiftedPointers": shifted_pointers,
    }
    return RepackResult(
        output_bytes=bytes(out),
        delta=total_delta,
        bun_graph_updates={"delta": total_delta, "shiftedPointers": shifted_pointers},
        macho_updates=pe_updates,
        macho_update_details=[],
    )
