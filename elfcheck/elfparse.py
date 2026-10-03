"""ELF64 x86-64 little-endian parsing via pyelftools (no execution, no ldd)."""

import os
from dataclasses import dataclass, field

from elftools.common.exceptions import ELFError
from elftools.elf.dynamic import DynamicSegment, DynamicSection
from elftools.elf.elffile import ELFFile
from elftools.elf.gnuversions import GNUVerDefSection, GNUVerNeedSection

from .errors import ElfFormatError

MAX_FILE_SIZE = 64 * 1024 * 1024


@dataclass
class VerNeed:
    lib: str
    name: str
    weak: bool


@dataclass
class ElfInfo:
    path: str
    soname: str | None = None
    needed: list = field(default_factory=list)
    rpath: list = field(default_factory=list)
    runpath: list = field(default_factory=list)
    verdef: set = field(default_factory=set)
    verneed: list = field(default_factory=list)  # list[VerNeed]


def parse_elf(host_path: str, vpath: str) -> ElfInfo:
    try:
        size = os.path.getsize(host_path)
    except OSError as exc:
        raise ElfFormatError(f"cannot stat {vpath}: {exc}")
    if size > MAX_FILE_SIZE:
        raise ElfFormatError(f"file too large ({size} bytes > {MAX_FILE_SIZE}): {vpath}")
    try:
        f = open(host_path, "rb")
    except OSError as exc:
        raise ElfFormatError(f"cannot read {vpath}: {exc}")
    with f:
        try:
            elf = ELFFile(f)
        except ELFError as exc:
            raise ElfFormatError(f"invalid ELF {vpath}: {exc}")
        ident = elf.header.e_ident
        if ident.EI_CLASS != "ELFCLASS64":
            raise ElfFormatError(f"not ELF64: {vpath}")
        if ident.EI_DATA != "ELFDATA2LSB":
            raise ElfFormatError(f"not little-endian: {vpath}")
        if elf.header.e_machine != "EM_X86_64":
            raise ElfFormatError(f"not x86-64: {vpath}")
        if elf.header.e_type not in ("ET_EXEC", "ET_DYN"):
            raise ElfFormatError(f"not an executable or shared object: {vpath}")

        info = ElfInfo(path=vpath)
        for seg in elf.iter_segments():
            if not isinstance(seg, (DynamicSection, DynamicSegment)):
                continue
            for tag in seg.iter_tags():
                d_tag = tag.entry.d_tag
                if d_tag == "DT_NEEDED":
                    info.needed.append(tag.needed)
                elif d_tag == "DT_SONAME":
                    info.soname = tag.soname
                elif d_tag == "DT_RPATH":
                    info.rpath = [e for e in tag.rpath.split(":")]
                elif d_tag == "DT_RUNPATH":
                    info.runpath = [e for e in tag.runpath.split(":")]
        for sec in elf.iter_sections():
            if isinstance(sec, GNUVerDefSection):
                for _, verdaux_iter in sec.iter_versions():
                    for verdaux in verdaux_iter:
                        info.verdef.add(verdaux.name)
                        break  # first aux entry carries the version name
            elif isinstance(sec, GNUVerNeedSection):
                for verneed, vernaux_iter in sec.iter_versions():
                    for vernaux in vernaux_iter:
                        weak = bool(vernaux.entry.vna_flags & 0x2)  # VER_FLG_WEAK
                        info.verneed.append(
                            VerNeed(lib=verneed.name, name=vernaux.name, weak=weak)
                        )
        return info
