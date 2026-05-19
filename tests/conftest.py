"""pytest configuration and workarounds for the test suite."""
import subprocess
import sys

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
