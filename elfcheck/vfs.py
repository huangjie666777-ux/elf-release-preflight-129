"""Virtual absolute path mapping onto a release root.

All user supplied paths are *virtual* absolute paths ("/app/bin/prog").
They are resolved against the release root on the host.  Symlinks are
followed with loop detection; anything escaping the release root or
pointing outside of it is rejected so host libraries are never read.
"""

import os
import posixpath

from .errors import PathError

MAX_SYMLINKS = 40


class Vfs:
    def __init__(self, root: str):
        if not root:
            raise PathError("release_root must not be empty")
        real = os.path.realpath(root)
        if not os.path.isdir(real):
            raise PathError(f"release_root is not a directory: {root}")
        self.root = real

    @staticmethod
    def _check_virtual(path: str) -> str:
        if not isinstance(path, str) or not path.startswith("/"):
            raise PathError(f"path must be a virtual absolute path: {path!r}")
        norm = posixpath.normpath(path)
        if not norm.startswith("/"):
            raise PathError(f"path escapes root: {path!r}")
        return norm

    def to_host(self, vpath: str) -> str:
        """Map a virtual absolute path to a host path, resolving symlinks."""
        vpath = self._check_virtual(vpath)
        host = self.root
        resolved = []
        links = 0
        parts = [p for p in vpath.split("/") if p]
        i = 0
        while i < len(parts):
            host = os.path.join(host, parts[i])
            resolved.append(parts[i])
            i += 1
            if os.path.islink(host):
                links += 1
                if links > MAX_SYMLINKS:
                    raise PathError(f"symlink loop detected at: {vpath}")
                target = os.readlink(host)
                if target.startswith("/"):
                    # absolute symlink target is a virtual path
                    tnorm = self._check_virtual(target)
                    parts = [p for p in tnorm.split("/") if p] + parts[i:]
                else:
                    tnorm = posixpath.normpath(
                        posixpath.join("/", *resolved[:-1], target)
                    )
                    if not tnorm.startswith("/"):
                        raise PathError(f"symlink escapes root: {vpath}")
                    parts = [p for p in tnorm.split("/") if p] + parts[i:]
                host = self.root
                resolved = []
                i = 0
        real = os.path.realpath(host)
        if real != self.root and not real.startswith(self.root + os.sep):
            raise PathError(f"path escapes release root: {vpath}")
        return real

    def to_virtual(self, host_path: str) -> str:
        rel = os.path.relpath(host_path, self.root)
        if rel == ".":
            return "/"
        if rel.startswith(".."):
            raise PathError(f"host path outside release root: {host_path}")
        return "/" + rel.replace(os.sep, "/")

    def exists(self, vpath: str) -> bool:
        try:
            return os.path.isfile(self.to_host(vpath))
        except PathError:
            raise

