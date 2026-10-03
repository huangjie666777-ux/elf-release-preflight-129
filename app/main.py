"""FastAPI HTTP layer for the release dependency precheck service."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .resolver import (
    DEFAULT_MAX_FILE_SIZE,
    DEFAULT_MAX_NODES,
    Resolver,
    SearchContext,
    expand_search_dir,
)
from .vfs import VfsError, VirtualFS

app = FastAPI(title="ELF release dependency precheck")


class PrecheckRequest(BaseModel):
    root: str = Field(..., description="host path of the release root")
    entry: str = Field(..., description="entry program, virtual absolute path")
    lib_dirs: list[str] = Field(
        default_factory=list,
        description="ordered library directories (virtual absolute paths)",
    )
    max_file_size: int = DEFAULT_MAX_FILE_SIZE
    max_nodes: int = DEFAULT_MAX_NODES


@app.post("/api/precheck")
def precheck(req: PrecheckRequest):
    try:
        vfs = VirtualFS(req.root)
    except VfsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not req.entry.startswith("/"):
        raise HTTPException(status_code=400, detail="entry must be a virtual absolute path")
    lib_dirs = []
    for d in req.lib_dirs:
        try:
            lib_dirs.append(expand_search_dir(d, "/"))
        except VfsError as exc:
            raise HTTPException(status_code=400, detail=f"invalid lib_dirs entry: {exc}")
    ctx = SearchContext(
        lib_dirs=lib_dirs,
        max_file_size=req.max_file_size,
        max_nodes=req.max_nodes,
    )
    return Resolver(vfs, ctx).analyze(req.entry)


@app.get("/api/health")
def health():
    return {"status": "ok"}
