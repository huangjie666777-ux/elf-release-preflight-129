import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from elfcheck.app import app
from elfcheck.errors import PathError
from elfcheck.resolver import expand_dir
from elfcheck.vfs import Vfs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE = os.path.join(ROOT, "examples", "release")


@pytest.fixture(scope="session", autouse=True)
def build_examples():
    subprocess.run(["sh", os.path.join(ROOT, "examples", "build_examples.sh")],
                   check=True)


@pytest.fixture()
def client():
    return TestClient(app)


def check(client, entry, lib_dirs=None):
    r = client.post("/check", json={
        "release_root": RELEASE,
        "entry": entry,
        "lib_dirs": lib_dirs or [],
    })
    assert r.status_code == 200
    return r.json()


def test_happy_path(client):
    rep = check(client, "/app/bin/app")
    assert rep["ok"], rep["diagnostics"]
    paths = {n["path"] for n in rep["nodes"]}
    assert "/app/bin/app" in paths
    assert "/app/lib/libbar.so" in paths
    assert "/app/lib/libfoo.so.1" in paths
    assert "/app/lib2/libbaz.so" in paths  # via inherited RPATH of entry
    # every edge selected
    assert all(e["selected"] for e in rep["edges"])
    # candidates reported
    edge = next(e for e in rep["edges"] if e["dependency"] == "libbar.so")
    assert edge["candidates"][0] == "/app/lib/libbar.so"


def test_soname_reuse_and_cycle(client):
    rep = check(client, "/app/bin/app")
    keys = [n["soname"] or n["path"] for n in rep["nodes"]]
    assert len(keys) == len(set(keys))  # first object reused per SONAME


def test_missing_version_and_lib(client):
    rep = check(client, "/app/bin/app_bad")
    assert not rep["ok"]
    kinds = {d["kind"] for d in rep["diagnostics"]}
    assert "version" in kinds
    assert "missing" in kinds
    edge = next(e for e in rep["edges"] if e["dependency"] == "libfoo.so.1"
                and e["from"].endswith("libneed9.so"))
    assert edge["missing_versions"] == ["FOO_9.9"]
    # other branches still diagnosed
    assert any(e["dependency"] == "libbar.so" and e["selected"]
               for e in rep["edges"])


def test_entry_not_found(client):
    rep = check(client, "/app/bin/nope")
    assert not rep["ok"]


def test_invalid_elf(client):
    rep = check(client, "/app/lib/notelf.so")
    assert not rep["ok"]
    assert rep["diagnostics"][0]["kind"] == "elf"


def test_symlink_loop(client):
    rep = check(client, "/app/lib/loop.so")
    assert not rep["ok"]
    assert "loop" in rep["diagnostics"][0]["message"]


def test_symlink_escape(client):
    rep = check(client, "/app/lib/escape.so")
    assert not rep["ok"]
    assert rep["diagnostics"][0]["kind"] in ("path", "elf")


def test_lib_dirs_validation(client):
    rep = check(client, "/app/bin/app", lib_dirs=["relative/dir"])
    assert not rep["ok"]
    assert any("lib_dirs" in d["message"] for d in rep["diagnostics"])


def test_expand_dir_rules():
    assert expand_dir("$ORIGIN/lib", "/app/bin") == "/app/bin/lib"
    assert expand_dir("/abs/dir", "/app/bin") == "/abs/dir"
    with pytest.raises(PathError):
        expand_dir("", "/app/bin")
    with pytest.raises(PathError):
        expand_dir("rel/dir", "/app/bin")
    with pytest.raises(PathError):
        expand_dir("$LIB/foo", "/app/bin")
    assert expand_dir("$ORIGIN/../lib", "/app/bin") == "/app/lib"


def test_vfs_rejects_relative():
    vfs = Vfs(RELEASE)
    with pytest.raises(PathError):
        vfs.to_host("etc/passwd")
