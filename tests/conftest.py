"""pytest configuration and workarounds for the test suite."""
import subprocess
import sys
from pathlib import Path

# ── Python 3.14 on Windows: _winapi.DuplicateHandle regression ──
# subprocess.Popen._get_handles calls _make_inheritable on stdin, which
# fails with OSError(WinError 6) when the handle can't be duplicated.
# This is a known CPython regression (not a project bug).
# Workaround: monkey-patch Popen to default stdin=DEVNULL when stdin is
# None (the default), avoiding the broken handle-inheritance path.
if sys.platform == "win32":
    _original_popen_init = subprocess.Popen.__init__

    def _patched_popen_init(self, *args, **kwargs):
        # Default stdin=None triggers _make_inheritable — use DEVNULL instead
        if kwargs.get("stdin") is None and len(args) < 3:
            kwargs["stdin"] = subprocess.DEVNULL
        return _original_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_popen_init


def pytest_configure(config):
    """Set project-local basetemp to avoid Windows system temp permission issues.

    C:\\Users\\Zero\\AppData\\Local\\Temp\\pytest-of-Zero can accumulate stale
    dirs with broken ACLs from mixed-elevation runs, causing PermissionError in
    os.scandir during tmp_path fixture setup.  Using a project-local temp dir
    avoids that entirely.
    """
    if config.option.basetemp is None:
        project_tmp = Path(__file__).parent.parent / ".local_llm_out" / "pytest-tmp"
        project_tmp.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(project_tmp)
