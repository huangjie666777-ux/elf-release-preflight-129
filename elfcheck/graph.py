"""BFS dependency graph construction and version verification."""

import posixpath
from collections import deque

from .elfparse import ElfInfo, parse_elf
from .errors import CheckError, ElfFormatError, PathError
from .resolver import expand_dirs

MAX_NODES = 256
FALLBACK_DIRS = ["/lib", "/usr/lib"]


class Node:
    def __init__(self, key: str, info: ElfInfo):
        self.key = key
        self.info = info


class Analyzer:
    def __init__(self, vfs, lib_dirs):
        self.vfs = vfs
        self.lib_dirs = list(lib_dirs)
        self.nodes = {}  # key -> Node
        self.edges = []
        self.diagnostics = []
        self.incomplete = False
        self.truncated = False

    def _diag(self, kind, message, **extra):
        d = {"kind": kind, "message": message}
        d.update(extra)
        self.diagnostics.append(d)

    def _load(self, vpath):
        """Parse one ELF. Returns Node or None (diagnostic recorded)."""
        if len(self.nodes) >= MAX_NODES:
            self.incomplete = True
            self.truncated = True
            self._diag("limit", f"node limit {MAX_NODES} exceeded, graph incomplete")
            return None
        try:
            host = self.vfs.to_host(vpath)
        except PathError as exc:
            self._diag("path", str(exc), path=vpath)
            return None
        try:
            info = parse_elf(host, vpath)
        except ElfFormatError as exc:
            self._diag("elf", str(exc), path=vpath)
            return None
        key = info.soname or vpath
        if key in self.nodes:
            return self.nodes[key]
        node = Node(key, info)
        self.nodes[key] = node
        return node

    def _effective_rpath(self, chain):
        """RPATH inherited along the load chain; objects with RUNPATH
        do not contribute (their RPATH is ignored)."""
        dirs, errors = [], []
        for node in chain:
            info = node.info
            if info.runpath:
                continue
            origin = posixpath.dirname(info.path)
            d, e = expand_dirs(info.rpath, origin)
            dirs.extend(d)
            errors.extend(e)
        return dirs, errors

    def _resolve(self, dep, chain, requester):
        """Search one DT_NEEDED. Returns (candidates, selected_vpath)."""
        if "/" in dep:
            if not dep.startswith("/"):
                self._diag(
                    "path",
                    f"dependency with slash must be a virtual absolute path: {dep!r}",
                    dependency=dep,
                )
                return [dep], None
            return [dep], dep
        rpath_dirs, rpath_errs = self._effective_rpath(chain)
        for e in rpath_errs:
            self._diag("path", e, dependency=dep, requester=requester.info.path)
        origin = posixpath.dirname(requester.info.path)
        runpath_dirs, runpath_errs = expand_dirs(requester.info.runpath, origin)
        for e in runpath_errs:
            self._diag("path", e, dependency=dep, requester=requester.info.path)
        search = rpath_dirs + self.lib_dirs + runpath_dirs + FALLBACK_DIRS
        candidates = []
        seen = set()
        for d in search:
            c = posixpath.join(d, dep)
            if c not in seen:
                seen.add(c)
                candidates.append(c)
        for c in candidates:
            try:
                if self.vfs.exists(c):
                    return candidates, c
            except PathError as exc:
                self._diag("path", str(exc), dependency=dep)
        return candidates, None

    def analyze(self, entry: str):
        root = self._load(entry)
        if root is None:
            return
        queue = deque([(root, [root])])
        enqueued = {root.key}
        while queue:
            node, chain = queue.popleft()
            for dep in node.info.needed:
                candidates, selected = self._resolve(dep, chain, node)
                edge = {
                    "from": node.info.path,
                    "dependency": dep,
                    "candidates": candidates,
                    "selected": selected,
                    "missing_versions": [],
                }
                child = None
                if selected is None:
                    self._diag(
                        "missing",
                        f"library not found: {dep} (needed by {node.info.path})",
                        dependency=dep,
                        requester=node.info.path,
                    )
                else:
                    child = self._load(selected)
                    if child is None and self.truncated:
                        self.edges.append(edge)
                        continue
                if child is not None:
                    edge["selected"] = child.info.path
                    self._check_versions(node, child, dep, edge)
                    if child.key not in enqueued:
                        enqueued.add(child.key)
                        queue.append((child, chain + [child]))
                self.edges.append(edge)

    def _check_versions(self, node, child, dep, edge):
        for vn in node.info.verneed:
            if vn.weak:
                continue
            if vn.lib != dep and vn.lib != child.info.soname:
                continue
            if vn.name not in child.info.verdef:
                edge["missing_versions"].append(vn.name)
                self._diag(
                    "version",
                    f"version {vn.name} required by {node.info.path} "
                    f"not defined in {child.info.path}",
                    dependency=dep,
                    requester=node.info.path,
                    library=child.info.path,
                    version=vn.name,
                )

    def report(self):
        ok = not self.diagnostics and not self.incomplete
        return {
            "ok": ok,
            "incomplete": self.incomplete,
            "nodes": [
                {
                    "path": n.info.path,
                    "soname": n.info.soname,
                    "needed": n.info.needed,
                    "rpath": n.info.rpath,
                    "runpath": n.info.runpath,
                    "verdef": sorted(n.info.verdef),
                }
                for n in self.nodes.values()
            ],
            "edges": self.edges,
            "diagnostics": self.diagnostics,
        }

