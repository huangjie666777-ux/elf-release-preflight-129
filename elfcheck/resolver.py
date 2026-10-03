"""Dependency search path handling: RPATH/RUNPATH, $ORIGIN, virtual dirs."""

import posixpath
import re

from .errors import PathError

_ORIGIN_RE = re.compile(r"\$\{?ORIGIN\}?")
_VAR_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")


def expand_dir(entry: str, origin: str) -> str:
    """Expand one search dir entry. Only $ORIGIN is supported.

    Returns a virtual absolute path. Raises PathError for empty entries,
    relative paths, or unsupported variables ($LIB, $PLATFORM, ...).
    """
    if entry == "":
        raise PathError("empty search directory entry")
    rest = _ORIGIN_RE.sub("", entry)
    if _VAR_RE.search(rest):
        raise PathError(f"unsupported variable in search directory: {entry!r}")
    if entry.startswith("$ORIGIN") or entry.startswith("${ORIGIN}"):
        expanded = _ORIGIN_RE.sub(origin, entry)
    else:
        expanded = entry
    if not expanded.startswith("/"):
        raise PathError(f"search directory must be absolute: {entry!r}")
    return posixpath.normpath(expanded)


def expand_dirs(entries, origin: str):
    """Expand a list of entries, collecting per-entry errors."""
    dirs, errors = [], []
    for e in entries:
        try:
            dirs.append(expand_dir(e, origin))
        except PathError as exc:
            errors.append(str(exc))
    return dirs, errors

