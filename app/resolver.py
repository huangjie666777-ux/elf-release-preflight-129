"""Dependency resolution: search rules, BFS graph construction, version checks."""

from collections import deque
from dataclasses import dataclass, field

from .elfparse import ElfFormatError, ElfInfo, parse_elf
from .vfs import VfsError, VirtualFS

DEFAULT_MAX_FILE_SIZE = 64 * 1024 * 1024
DEFAULT_MAX_NODES = 256


@dataclass
class SearchContext:
    lib_dirs: list[str]          # request-provided ordered library directories
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    max_nodes: int = DEFAULT_MAX_NODES


@dataclass
class Node:
    key: str                     # SONAME if present, else the NEEDED name
    vpath: str                   # virtual absolute path of the selected file
    info: ElfInfo
    dirname: str                 # virtual dir of the object (for $ORIGIN)


@dataclass
class Edge:
    referrer: str                # key of referring node ("<entry>" for root)
    needed: str                  # raw DT_NEEDED string
    candidates: list[str] = field(default_factory=list)
    selected: str | None = None  # virtual path of selected object
    node_key: str | None = None
    missing_versions: list[str] = field(default_factory=list)
    error: str | None = None


def expand_search_dir(entry: str, origin: str) -> str:
    """Expand $ORIGIN; reject other variables, empty and relative entries."""
    if entry == "":
        raise VfsError("empty search directory entry")
    out = entry.replace("$ORIGIN", origin).replace("${ORIGIN}", origin)
    if "$" in out:
        raise VfsError(f"unsupported variable in search directory: {entry!r}")
    if not out.startswith("/"):
        raise VfsError(f"search directory is not a virtual absolute path: {entry!r}")
    return out


class Resolver:
    def __init__(self, vfs: VirtualFS, ctx: SearchContext):
        self.vfs = vfs
        self.ctx = ctx
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.diagnostics: list[str] = []
        self.incomplete = False
        self._node_order: list[str] = []

    # -- loading -----------------------------------------------------------

    def _load(self, vpath: str) -> Node:
        data = self.vfs.read(vpath, self.ctx.max_file_size)
        info = parse_elf(data, vpath)
        key = info.soname or vpath.rsplit("/", 1)[-1]
        dirname = vpath.rsplit("/", 1)[0] or "/"
        return Node(key=key, vpath=vpath, info=info, dirname=dirname)

    # -- search path construction ------------------------------------------

    def _rpath_chain(self, referrer_chain: list[Node]) -> list[str]:
        """Effective RPATH: inherited along the load chain; each ancestor
        contributes its DT_RPATH only if it has no DT_RUNPATH."""
        dirs: list[str] = []
        for node in reversed(referrer_chain):  # immediate referrer first
            if node.info.runpath:
                continue
            for entry in node.info.rpath:
                dirs.append(expand_search_dir(entry, node.dirname))
        return dirs

    def _candidates(self, referrer: Node, chain: list[Node], needed: str) -> list[str]:
        if "/" in needed:
            if not needed.startswith("/"):
                raise VfsError(
                    f"dependency with slash must be a virtual absolute path: {needed!r}"
                )
            return [needed]
        dirs = self._rpath_chain(chain)
        dirs += self.ctx.lib_dirs
        dirs += [expand_search_dir(e, referrer.dirname) for e in referrer.info.runpath]
        dirs += ["/lib", "/usr/lib"]
        seen: set[str] = set()
        out: list[str] = []
        for d in dirs:
            cand = d.rstrip("/") + "/" + needed
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
        return out

    # -- graph construction -------------------------------------------------

    def analyze(self, entry_vpath: str) -> dict:
        try:
            root = self._load(entry_vpath)
        except (VfsError, ElfFormatError) as exc:
            self.diagnostics.append(f"entry: {exc}")
            return self._report()
        self.nodes[root.key] = root
        self._node_order.append(root.key)
        # parent chain per node key, for RPATH inheritance
        chains: dict[str, list[str]] = {root.key: [root.key]}
        queue: deque[str] = deque([root.key])

        while queue:
            if len(self.nodes) > self.ctx.max_nodes:
                self.incomplete = True
                self.diagnostics.append(
                    f"node limit {self.ctx.max_nodes} exceeded; graph truncated"
                )
                break
            cur_key = queue.popleft()
            cur = self.nodes[cur_key]
            chain = chains[cur_key]
            for needed in cur.info.needed:
                edge = Edge(referrer=cur_key, needed=needed)
                self.edges.append(edge)
                try:
                    candidates = self._candidates(cur, [self.nodes[k] for k in chain], needed)
                    edge.candidates = candidates
                    selected = next(
                        (c for c in candidates if self.vfs.is_file(c)), None
                    )
                    if selected is None:
                        edge.error = "library not found"
                        self.diagnostics.append(
                            f"{cur_key}: dependency {needed!r} not found "
                            f"(searched: {', '.join(candidates)})"
                        )
                        continue
                    edge.selected = selected
                    try:
                        node = self._load(selected)
                    except (VfsError, ElfFormatError) as exc:
                        edge.error = str(exc)
                        self.diagnostics.append(f"{cur_key}: {needed!r}: {exc}")
                        continue
                    key = node.key
                    edge.node_key = key
                    if key in self.nodes:
                        node = self.nodes[key]  # reuse first object with this SONAME
                        edge.selected = node.vpath
                    else:
                        self.nodes[key] = node
                        self._node_order.append(key)
                        chains[key] = chain + [key]
                        queue.append(key)
                    self._check_versions(cur, node, needed, edge)
                except VfsError as exc:
                    edge.error = str(exc)
                    self.diagnostics.append(f"{cur_key}: {needed!r}: {exc}")
        return self._report()

    # -- version checks ------------------------------------------------------

    def _check_versions(self, referrer: Node, lib: Node, needed: str, edge: Edge) -> None:
        for vn in referrer.info.verneed:
            if vn.weak or vn.lib != needed:
                continue
            if vn.name not in lib.info.verdef:
                edge.missing_versions.append(vn.name)
                self.diagnostics.append(
                    f"{referrer.key}: {needed!r} requires version {vn.name!r} "
                    f"not provided by {lib.vpath}"
                )

    # -- report ---------------------------------------------------------------

    def _report(self) -> dict:
        ok = (
            not self.diagnostics
            and not self.incomplete
            and all(e.error is None and not e.missing_versions for e in self.edges)
        )
        return {
            "ok": ok,
            "incomplete": self.incomplete,
            "nodes": [
                {
                    "key": k,
                    "path": self.nodes[k].vpath,
                    "soname": self.nodes[k].info.soname,
                    "needed": self.nodes[k].info.needed,
                    "rpath": self.nodes[k].info.rpath,
                    "runpath": self.nodes[k].info.runpath,
                    "verdef": sorted(self.nodes[k].info.verdef),
                }
                for k in self._node_order
            ],
            "edges": [
                {
                    "referrer": e.referrer,
                    "needed": e.needed,
                    "candidates": e.candidates,
                    "selected": e.selected,
                    "missing_versions": e.missing_versions,
                    "error": e.error,
                }
                for e in self.edges
            ],
            "diagnostics": self.diagnostics,
        }
