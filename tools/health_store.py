"""Runtime per-profile health telemetry store.

Introduced by MCP Health Telemetry Isolation P1-H.1.

This module is a self-contained read/write helper for the runtime
health file `.local_llm_out/local_llm_health.json`. It is the future
home for what `_update_model_health` in `tools/local_llm_mcp_server.py`
currently writes into each profile's `_health` block in
`tools/local_llm_profiles.json`.

P1-H.1 scope: add the helper, do NOT change any call site. The MCP
server's existing `_update_model_health` continues to write into
profiles JSON for now; that switch lands in P1-H.2 with debate review.

Public API:
    HEALTH_PATH
    load_health(path=None) -> dict
    load_profile_health(profile_name, path=None) -> dict
    record_invocation(profile_name, ok, elapsed_s, error_type="", path=None) -> None

Contract:
- All reads tolerate a missing file (return `{}`).
- `record_invocation` is best-effort and NEVER raises.
- Atomic write via `.tmp` + `os.replace`.
- This module NEVER reads or writes `tools/local_llm_profiles.json`.
- 90/10 weighted formula matches `_update_model_health` exactly so
  that swapping the writer in P1-H.2 produces identical numerics.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
HEALTH_PATH = PROJECT_ROOT / ".local_llm_out" / "local_llm_health.json"

SCHEMA_VERSION = 1


def _today() -> str:
    return datetime.now(timezone.utc).isoformat()[:10]


def _resolve(path: Path | str | None) -> Path:
    return Path(path) if path else HEALTH_PATH


def load_health(path: Path | str | None = None) -> dict:
    """Return the full health document. Returns `{}` if the file does
    not exist or cannot be parsed."""
    p = _resolve(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_profile_health(
    profile_name: str, path: Path | str | None = None
) -> dict:
    """Return the per-profile health dict, or `{}` if absent."""
    doc = load_health(path)
    profiles = doc.get("profiles", {})
    if not isinstance(profiles, dict):
        return {}
    h = profiles.get(profile_name, {})
    return h if isinstance(h, dict) else {}


def record_invocation(
    profile_name: str,
    ok: bool,
    elapsed_s: float,
    error_type: str = "",
    path: Path | str | None = None,
) -> None:
    """Update the runtime health record for `profile_name`.

    Mirrors the formula in
    `tools/local_llm_mcp_server.py::_update_model_health`:

        success_rate = old * 0.9 + (1.0 if ok else 0.0) * 0.1
        avg_latency_s = old * 0.9 + elapsed_s * 0.1

    On first record for a profile, defaults are `success_rate=1.0` and
    `avg_latency_s=elapsed_s` (so the first sample is recorded as-is).

    `consecutive_failures` increments on `ok=False`, resets to 0 on
    `ok=True`. `last_timeout` is set to today's UTC date only when
    `error_type == "timeout"`; non-timeout invocations leave an
    existing value unchanged.

    Best-effort: any IO/encoding error is swallowed.
    """
    if not profile_name:
        return
    try:
        p = _resolve(path)
        doc = load_health(p)
        if not isinstance(doc, dict):
            doc = {}

        profiles = doc.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}

        h: dict[str, Any] = profiles.get(profile_name, {})
        if not isinstance(h, dict):
            h = {}

        now = _today()

        old_rate = h.get("success_rate", 1.0)
        new_point = 1.0 if ok else 0.0
        h["success_rate"] = round(old_rate * 0.9 + new_point * 0.1, 3)

        old_lat = h.get("avg_latency_s", elapsed_s)
        h["avg_latency_s"] = round(old_lat * 0.9 + elapsed_s * 0.1, 1)

        if error_type == "timeout":
            h["last_timeout"] = now
        if ok:
            h["last_timeout"] = None

        if ok:
            h["consecutive_failures"] = 0
        else:
            h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1

        h["_updated"] = now

        profiles[profile_name] = h
        doc["profiles"] = profiles
        doc["schema_version"] = SCHEMA_VERSION
        doc["_updated"] = now

        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        # Best-effort — health telemetry must never block the caller.
        return
