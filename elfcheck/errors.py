class CheckError(Exception):
    """Base error for precheck failures."""


class PathError(CheckError):
    """Invalid or unsafe virtual path."""


class ElfFormatError(CheckError):
    """File is not a valid/supported ELF."""

