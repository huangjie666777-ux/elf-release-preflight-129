"""Virtual filesystem: map virtual absolute paths onto the release root.

All in-package paths are *virtual absolute* (they start with "/" and are
interpreted relative to the release root).  Symlinks are resolved manually
so that escapes outside the root and symlink loops are detected and never
cause host files (e.g. the host /lib) to be read.
"""

import os


class VfsError(Exception):
    pass


class EscapeError(VfsError):
    pass


class LoopError(VfsError):
    pass


class NotFoundError(VfsError):
    pass


MAX_SYMLINKS = 40


class VirtualFS:
    def __init__(self, root: str):
        if not root:
            raise VfsError("release root must not be empty")
        real = os.path.realpath(root)
        if not os.path.isdir(real):
            raise VfsError(f"release root is not a directory: {root}")
        self.root = real

    def _check_inside(self, host_path: str, vpath: str) -> None:
        real = os.path.realpath(host_path)
        if real != self.root and not real.startswith(self.root + os.sep):
            raise EscapeError(
                f"path {vpath!r} escapes the release root (resolves to {real})"
            )

    def resolve(self, vpath: str) -> str:
        """Resolve a virtual absolute path to a host path inside the root.

        Follows symlinks (absolute symlink targets are re-interpreted as
        virtual absolute paths, i.e. relative to the release root, never the
        host root).  Raises on loops, escapes and missing files.
        """
        if not vpath.startswith("/"):
            raise VfsError(f"not a virtual absolute path: {vpath!r}")
        if "\x00" in vpath:
            raise VfsError("NUL byte in path")

        links = 0
        parts = [p for p in vpath.split("/") if p not in ("", ".")]
        resolved: list[str] = []
        idx = 0
        while idx < len(parts):
            part = parts[idx]
            if part == "..":
                if resolved:
                    resolved.pop()
                idx += 1
                continue
            resolved.append(part)
            host = os.path.join(self.root, *resolved)
            self._check_inside(host, vpath)
            if os.path.islink(host):
                links += 1
                if links > MAX_SYMLINKS:
                    raise LoopError(f"symlink loop detected resolving {vpath!r}")
                target = os.readlink(host)
                if target.startswith("/"):
                    # absolute target: virtual absolute, re-rooted
                    rest = [p for p in target.split("/") if p not in ("", ".")]
                else:
                    rest = [p for p in target.split("/") if p not in ("", ".")]
                    # relative to the directory containing the link
                    resolved.pop()
                tail = rest + parts[idx + 1:]
                parts = resolved + tail
                resolved = []
                idx = 0
                continue
            idx += 1
        host = os.path.join(self.root, *resolved) if resolved else self.root
        self._check_inside(host, vpath)
        if not os.path.exists(host):
            raise NotFoundError(f"virtual path not found: {vpath!r}")
        return host

    def is_file(self, vpath: str) -> bool:
        try:
            return os.path.isfile(self.resolve(vpath))
        except VfsError:
            return False

    def read(self, vpath: str, max_size: int) -> bytes:
        host = self.resolve(vpath)
        if not os.path.isfile(host):
            raise NotFoundError(f"not a regular file: {vpath!r}")
        size = os.path.getsize(host)
        if size > max_size:
            raise VfsError(f"file too large: {vpath} ({size} > {max_size} bytes)")
        with open(host, "rb") as fh:
            return fh.read()
