"""FastAPI HTTP layer for the dependency precheck service."""

from typing import List

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .errors import PathError
from .graph import Analyzer
from .resolver import expand_dir
from .vfs import Vfs

app = FastAPI(title="elfcheck", version="0.1.0")


class CheckRequest(BaseModel):
    release_root: str = Field(..., description="host path of the release root")
    entry: str = Field(..., description="virtual absolute path of the entry ELF")
    lib_dirs: List[str] = Field(
        default_factory=list,
        description="ordered virtual absolute library directories",
    )


@app.post("/check")
def check(req: CheckRequest):
    try:
        vfs = Vfs(req.release_root)
    except PathError as exc:
        return {"ok": False, "incomplete": False, "nodes": [], "edges": [],
                "diagnostics": [{"kind": "path", "message": str(exc)}]}
    lib_dirs = []
    diagnostics = []
    for d in req.lib_dirs:
        try:
            lib_dirs.append(expand_dir(d, "/"))
        except PathError as exc:
            diagnostics.append({"kind": "path", "message": f"lib_dirs: {exc}"})
    analyzer = Analyzer(vfs, lib_dirs)
    analyzer.diagnostics.extend(diagnostics)
    analyzer.analyze(req.entry)
    return analyzer.report()


@app.get("/health")
def health():
    return {"status": "ok"}

