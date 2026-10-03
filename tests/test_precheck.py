import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.vfs import EscapeError, LoopError, VirtualFS

ROOT = "/tmp/precheck-release"


@pytest.fixture(scope="session", autouse=True)
def fixtures():
    script = os.path.join(os.path.dirname(__file__), "make_fixtures.sh")
    subprocess.run(["bash", script, ROOT], check=True)


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


def post(client, **kw):
    payload = {"root": ROOT, "entry": "/bin/app", "lib_dirs": ["/lib"]}
    payload.update(kw)
    resp = client.post("/api/precheck", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_graph_and_soname_reuse(client):
    rep = post(client)
    keys = [n["key"] for n in rep["nodes"]]
    assert "libfoo.so.1" in keys and "libbar.so" in keys
    # libbar also needs libfoo.so.1 -> same node reused, edge kept
    foo_edges = [e for e in rep["edges"] if e["needed"] == "libfoo.so.1"]
    assert len(foo_edges) == 2
    assert all(e["selected"] == "/lib/libfoo.so.1" for e in foo_edges)
    # libc is not in the release root and must be reported missing
    assert any(e["error"] == "library not found" for e in rep["edges"])
    assert not rep["ok"]


def test_missing_version_keeps_first_selection(client):
    rep = post(client, lib_dirs=["/oldlib", "/lib"])
    assert not rep["ok"]
    foo_edges = [e for e in rep["edges"] if e["needed"] == "libfoo.so.1"]
    assert any("LIBFOO_2" in e["missing_versions"] for e in foo_edges)
    # selection must not jump to the later good copy
    assert all(e["selected"] == "/oldlib/libfoo.so.1" for e in foo_edges)


def test_runpath_origin_expansion(client):
    rep = post(client, lib_dirs=[])
    edge = next(e for e in rep["edges"] if e["needed"] == "libfoo.so.1")
    assert "/bin/../lib/libfoo.so.1" in edge["candidates"]
    assert edge["selected"] == "/bin/../lib/libfoo.so.1"


def test_rpath_plugin(client):
    rep = post(client, entry="/plugins/libplug.so", lib_dirs=[])
    edge = next(e for e in rep["edges"] if e["needed"] == "libfoo.so.1")
    assert edge["selected"] == "/plugins/../lib/libfoo.so.1"


def test_symlink_escape_and_loop():
    vfs = VirtualFS(ROOT)
    with pytest.raises(EscapeError):
        vfs.resolve("/lib/evil-link")
    with pytest.raises(LoopError):
        vfs.resolve("/lib/loop-a")


def test_bad_search_dirs(client):
    for bad in ["", "relative/dir", "/ok/$LIB", "/ok/${PLATFORM}"]:
        resp = client.post("/api/precheck", json={
            "root": ROOT, "entry": "/bin/app", "lib_dirs": [bad]})
        assert resp.status_code == 400, bad


def test_node_limit_marks_incomplete(client):
    rep = post(client, max_nodes=1)
    assert rep["incomplete"]
    assert not rep["ok"]


def test_invalid_elf_rejected(client):
    resp = client.post("/api/precheck", json={
        "root": ROOT, "entry": "/lib/evil-link", "lib_dirs": []})
    assert resp.status_code == 200
    assert not resp.json()["ok"]

