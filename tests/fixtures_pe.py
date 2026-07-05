"""Synthetic PE32+ fixtures carrying a Bun `.bun` payload as the last section.

Mirrors tests/fixtures_bun.py's Mach-O builders so pe.py can be exercised
without the ~240 MB real claude.exe. The `.bun` section holds the exact
`[u64 len][payload]` bytes build_payload() produces — byte-identical to the
macOS payload — so bun_graph.py parses it unchanged.
"""
from __future__ import annotations

import struct

FILE_ALIGNMENT = 0x200
SECTION_ALIGNMENT = 0x1000
FORCE_INTEGRITY = 0x0080


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def build_pe_fixture(section: bytes, *, with_authenticode: bool = False) -> bytes:
    # Header sizes: DOS stub (0x40) + PE sig (4) + COFF header (20) +
    # optional header (240 for PE32+ with 16 data dirs) + 2 section headers (80).
    e_lfanew = 0x40
    opt_size = 240
    n_sections = 2
    headers_end = e_lfanew + 4 + 20 + opt_size + n_sections * 40
    size_of_headers = _align(headers_end, FILE_ALIGNMENT)

    text = b"\xc3" * 0x10  # trivial .text body
    text_rawsize = _align(len(text), FILE_ALIGNMENT)
    text_ptr = size_of_headers
    text_vaddr = SECTION_ALIGNMENT

    bun_rawsize = _align(len(section), FILE_ALIGNMENT)
    bun_ptr = text_ptr + text_rawsize
    bun_vaddr = _align(text_vaddr + text_rawsize, SECTION_ALIGNMENT)
    size_of_image = _align(bun_vaddr + len(section), SECTION_ALIGNMENT)

    out = bytearray(bun_ptr + bun_rawsize)
    out[0:2] = b"MZ"
    struct.pack_into("<I", out, 0x3C, e_lfanew)
    out[e_lfanew:e_lfanew + 4] = b"PE\0\0"
    # COFF header: machine=0x8664, nsections, ..., SizeOfOptionalHeader, chars
    struct.pack_into("<HH", out, e_lfanew + 4, 0x8664, n_sections)
    struct.pack_into("<H", out, e_lfanew + 20, opt_size)
    struct.pack_into("<H", out, e_lfanew + 22, 0x0022)  # EXECUTABLE_IMAGE|LARGE_ADDRESS_AWARE
    opt = e_lfanew + 24
    struct.pack_into("<H", out, opt + 0, 0x020B)  # PE32+
    struct.pack_into("<I", out, opt + 32, SECTION_ALIGNMENT)
    struct.pack_into("<I", out, opt + 36, FILE_ALIGNMENT)
    struct.pack_into("<I", out, opt + 56, size_of_image)
    struct.pack_into("<I", out, opt + 60, size_of_headers)
    struct.pack_into("<I", out, opt + 108, 16)  # NumberOfRvaAndSizes

    st = opt + opt_size
    _write_section(out, st, b".text", len(text), text_vaddr, text_rawsize, text_ptr)
    _write_section(out, st + 40, b".bun", len(section), bun_vaddr, bun_rawsize, bun_ptr)

    out[text_ptr:text_ptr + len(text)] = text
    out[bun_ptr:bun_ptr + len(section)] = section

    if with_authenticode:
        cert = b"\x08\x00\x00\x00" + b"\x02\x02" + b"CERTDATA"  # dummy WIN_CERTIFICATE-ish blob
        cert_off = len(out)
        out.extend(cert)
        struct.pack_into("<II", out, opt + 112 + 32, cert_off, len(cert))  # DataDirectory[4]
        dll = struct.unpack_from("<H", out, opt + 70)[0]
        struct.pack_into("<H", out, opt + 70, dll | FORCE_INTEGRITY)
        struct.pack_into("<I", out, opt + 64, 0x1234)  # nonzero stored checksum

    return bytes(out)


def _write_section(
    buf: bytearray, off: int, name: bytes, vsize: int, vaddr: int, rawsize: int, rawptr: int
) -> None:
    buf[off:off + 8] = name.ljust(8, b"\0")
    struct.pack_into("<IIII", buf, off + 8, vsize, vaddr, rawsize, rawptr)
