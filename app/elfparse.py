"""ELF parsing: x86-64 little-endian ELF64 dynamic objects via pyelftools.

Never executes the inspected files and never shells out to ldd.
"""

import io
from dataclasses import dataclass, field

from elftools.common.exceptions import ELFError
from elftools.elf.dynamic import DynamicSegment
from elftools.elf.elffile import ELFFile
from elftools.elf.gnuversions import GNUVerDefSection, GNUVerNeedSection
from elftools.elf.sections import SymbolTableSection


class ElfFormatError(Exception):
    pass


@dataclass
class VerNeedEntry:
    lib: str        # DT_NEEDED name the version requirement refers to
    name: str       # version name, e.g. "LIBFOO_2"
    weak: bool


@dataclass
class ElfInfo:
    soname: str | None = None
    needed: list[str] = field(default_factory=list)
    rpath: list[str] = field(default_factory=list)
    runpath: list[str] = field(default_factory=list)
    verdef: set[str] = field(default_factory=set)
    verneed: list[VerNeedEntry] = field(default_factory=list)


def _split_path_list(raw: str) -> list[str]:
    # DT_RPATH / DT_RUNPATH are colon-separated; empty entries are kept so
    # the caller can reject them explicitly.
    return raw.split(":")


def parse_elf(data: bytes, name: str) -> ElfInfo:
    if len(data) < 16 or data[:4] != b"\x7fELF":
        raise ElfFormatError(f"{name}: not an ELF file")
    if data[4] != 2:  # ELFCLASS64
        raise ElfFormatError(f"{name}: not a 64-bit (ELF64) object")
    if data[5] != 1:  # ELFDATA2LSB
        raise ElfFormatError(f"{name}: not little-endian")
    try:
        elf = ELFFile(io.BytesIO(data))
    except ELFError as exc:
        raise ElfFormatError(f"{name}: malformed ELF: {exc}") from exc

    if elf["e_machine"] != "EM_X86_64":
        raise ElfFormatError(
            f"{name}: unsupported machine {elf['e_machine']!r} (need EM_X86_64)"
        )
    if elf["e_type"] not in ("ET_EXEC", "ET_DYN", "PIE"):
        raise ElfFormatError(f"{name}: unsupported ELF type {elf['e_type']!r}")

    info = ElfInfo()
    dynamic = None
    for seg in elf.iter_segments():
        if seg["p_type"] == "PT_DYNAMIC":
            dynamic = seg
            break
    if dynamic is None or not isinstance(dynamic, DynamicSegment):
        raise ElfFormatError(f"{name}: no PT_DYNAMIC segment (not dynamic?)")

    try:
        for tag in dynamic.iter_tags():
            if tag.entry.d_tag == "DT_NEEDED":
                info.needed.append(tag.needed)
            elif tag.entry.d_tag == "DT_SONAME":
                info.soname = tag.soname
            elif tag.entry.d_tag == "DT_RPATH":
                info.rpath = _split_path_list(tag.rpath)
            elif tag.entry.d_tag == "DT_RUNPATH":
                info.runpath = _split_path_list(tag.runpath)
    except ELFError as exc:
        raise ElfFormatError(f"{name}: malformed dynamic section: {exc}") from exc

    for sec in elf.iter_sections():
        try:
            if isinstance(sec, GNUVerDefSection):
                for verdef, aux_iter in sec.iter_versions():
                    for aux in aux_iter:
                        info.verdef.add(aux.name)
            elif isinstance(sec, GNUVerNeedSection):
                for verneed, aux_iter in sec.iter_versions():
                    for aux in aux_iter:
                        weak = bool(aux["vna_flags"] & 0x2)  # VERF_WEAK
                        info.verneed.append(
                            VerNeedEntry(lib=verneed.name, name=aux.name, weak=weak)
                        )
        except ELFError as exc:
            raise ElfFormatError(f"{name}: malformed GNU version info: {exc}") from exc
    return info
