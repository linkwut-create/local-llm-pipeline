"""Test blocked-path enforcement in the worker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from local_llm_worker import is_blocked_path


def test_git_blocked():
    assert is_blocked_path(Path(".git/config"))
    assert is_blocked_path(Path(".git/HEAD"))
    assert is_blocked_path(Path("some/deep/.git/objects"))


def test_env_blocked():
    assert is_blocked_path(Path(".env"))
    assert is_blocked_path(Path(".env.local"))
    assert is_blocked_path(Path(".env.production"))


def test_key_files_blocked():
    assert is_blocked_path(Path("secrets/id_rsa"))
    assert is_blocked_path(Path("id_ed25519"))
    assert is_blocked_path(Path("cert.pem"))
    assert is_blocked_path(Path("private.key"))


def test_vendor_dirs_blocked():
    assert is_blocked_path(Path("node_modules/express/index.js"))
    assert is_blocked_path(Path("venv/lib/python3.11/site.py"))
    assert is_blocked_path(Path(".venv/bin/activate"))
    assert is_blocked_path(Path("__pycache__/mod.cpython-311.pyc"))
    assert is_blocked_path(Path("dist/bundle.js"))
    assert is_blocked_path(Path("build/output.o"))
    assert is_blocked_path(Path("target/debug/main"))


def test_output_dir_blocked():
    assert is_blocked_path(Path(".local_llm_out/result.json"))


def test_normal_files_allowed():
    assert not is_blocked_path(Path("src/main.py"))
    assert not is_blocked_path(Path("README.md"))
    assert not is_blocked_path(Path("tools/local_llm_worker.py"))
    assert not is_blocked_path(Path("package.json"))
    assert not is_blocked_path(Path("docs/guide.md"))
    assert not is_blocked_path(Path("tests/test_foo.py"))
