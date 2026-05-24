#!/usr/bin/env python3
"""Call Ledger — append-only per-call JSONL accounting for local LLM pipeline.

Records every model invocation (success or failure) to .local_llm_out/audit/calls.jsonl
so token spend, cost, duration, project, phase, task type, files referenced and git
state can be reconstructed later.

Storage:    .local_llm_out/audit/calls.jsonl  (one JSON object per line)
Toggle:     LOCAL_LLM_LEDGER=0 disables writing (default: enabled).
Privacy:    never writes prompt body, full diff, response body, secrets or api keys.

Tokens are estimated from character counts when the upstream provider does not
return a usage block; in that case `tokens_estimated: true` is set on the record.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

LEDGER_DIR = Path(".local_llm_out") / "audit"
LEDGER_FILE = LEDGER_DIR / "calls.jsonl"

CHARS_PER_TOKEN = 4

_LOCAL_PROVIDERS = frozenset({"ollama", "llama.cpp", "llamacpp"})
_LOCAL_HOST_HINTS = ("localhost", "127.0.0.1", "0.0.0.0", "192.168.", "10.", "::1")

# M7 (v0.10.0-L): execution-location classification — distinguishes truly local
# Ollama from LAN-proxy Ollama so cost confidence can be reported honestly.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_FALSY = frozenset({"0", "false", "no", "off", "", "none"})

# Privacy: fields that must never appear in a ledger record, even if a caller
# passes them in via the extra dict.
_FORBIDDEN_KEYS = frozenset({
    "prompt_body", "user_prompt", "system_prompt",
    "full_diff", "full_code", "file_content", "response_body", "result_body",
    "api_key", "token", "password", "secret", "authorization",
})

# Cost-discipline / model-allocation fields that P2-C+ will populate via the
# `extra` dict on a per-call basis. Listed here so downstream consumers can
# distinguish recognised cost-discipline keys from ad-hoc ones. This is an
# allowlist for documentation and downstream filtering; `build_record` itself
# does NOT reject unknown extras — backward compatibility is preserved.
KNOWN_EXTRA_KEYS = frozenset({
    # MCP / routing identity
    "mcp_tool_name",
    "source",
    "commit_gate",
    "commit_gate_allowed",
    # Auto-escalation context (populated by _wrap_worker_call in P2-C2)
    "auto_escalated",
    "escalation_trigger",
    "escalation_reason",
    "escalation_from_profile",
    "escalation_to_profile",
    "escalation_depth",
    "parent_request_id",
    # Debate context (populated by debate path in P2-C3)
    "debate_mode",
    "debate_rounds",
    "debate_round_index",
    "debate_trigger",
    # Review classification
    "review_necessity",
    "risk_level",
    "cost_class",
    "local_only",
    "cost_budget_remaining",
    # Worker-pool attribution (future)
    "worker_id",
    "host",
    # Structured error type (worker already classifies via output.error_type)
    "error_type",
    # Diff preclassifier fields (B1-B ledger contract)
    "diff_risk_level",
    "diff_risk_confidence",
    "debate_skipped",
    "debate_skip_reason",
    "preclassifier_profile",
    "preclassifier_model",
    "preclassifier_request_id",
    "safety_blockers",
    "debate_skip_allowed",
    "skip_debate_recommended",
    "preclassifier_method",
    "changed_files_count",
    # Controlled auto-debate skip policy fields (B1-E)
    "debate_skip_policy",
    "debate_skip_policy_version",
    "skipped_estimated_seconds_saved",
    # Repo map tool fields (C2)
    "repo_map_schema_version",
    "repo_map_total_files",
    "repo_map_test_mappings",
    "repo_map_cache_hit",
    "repo_map_advisory_only",
    # Test-plan repo-map advisory fields (C3-B)
    "test_plan_repo_map_used",
    "test_plan_related_tests_count",
    "test_plan_subsystems",
    "test_plan_repo_map_warning",
})


def is_ledger_enabled() -> bool:
    """True unless LOCAL_LLM_LEDGER is set to a falsy value."""
    val = os.environ.get("LOCAL_LLM_LEDGER")
    if val is None:
        return True
    return val.strip().lower() not in _FALSY


def detect_project(cwd: str | Path | None = None) -> str:
    """Resolve project name: LOCAL_LLM_PROJECT env var first, else cwd basename."""
    env = os.environ.get("LOCAL_LLM_PROJECT")
    if env and env.strip():
        return env.strip()
    base = Path(cwd) if cwd else Path.cwd()
    try:
        name = base.resolve().name
    except Exception:
        name = base.name or "unknown"
    return name or "unknown"


def detect_phase() -> str | None:
    val = os.environ.get("LOCAL_LLM_PHASE")
    if val is None:
        return None
    val = val.strip()
    return val or None


def git_state(cwd: str | Path | None = None) -> tuple[str | None, bool | None]:
    """Return (short_commit, dirty). (None, None) if git unavailable or not a repo."""
    work = str(cwd) if cwd else None
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=work, capture_output=True, text=True, timeout=2, check=False,
        )
        if commit.returncode != 0:
            return (None, None)
        commit_hash = commit.stdout.strip() or None

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=work, capture_output=True, text=True, timeout=2, check=False,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return (commit_hash, dirty)
    except Exception:
        return (None, None)


def estimate_tokens(chars: int | None) -> int:
    if not chars or chars <= 0:
        return 0
    return int(chars) // CHARS_PER_TOKEN


def _is_local_provider(provider: str | None, base_url: str | None) -> bool:
    if provider and provider.lower() in _LOCAL_PROVIDERS:
        return True
    if base_url:
        url = base_url.lower()
        for hint in _LOCAL_HOST_HINTS:
            if hint in url:
                return True
    return False


def _parse_url_host(base_url: str | None) -> str | None:
    """Extract hostname from *base_url*, or ``None`` when unparseable."""
    if not base_url:
        return None
    try:
        from urllib.parse import urlparse
        return urlparse(base_url).hostname
    except Exception:
        return None


def _is_private_host(host: str) -> bool:
    """Return ``True`` when *host* is a loopback, RFC-1918, or link-local address."""
    if host in _LOCAL_HOSTS:
        return True
    if host.startswith("192.168.") or host.startswith("10."):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def classify_execution_location(provider: str | None, base_url: str | None) -> str:
    """Classify where a model invocation executed.

    Returns one of ``"local"``, ``"lan"``, ``"remote"``, ``"unknown"``.
    """
    if not provider and not base_url:
        return "unknown"

    host = _parse_url_host(base_url) if base_url else None
    is_local_style = bool(provider and provider.lower() in _LOCAL_PROVIDERS)

    if host in _LOCAL_HOSTS:
        return "local" if is_local_style else "unknown"
    if host and _is_private_host(host):
        return "lan" if is_local_style else "unknown"
    if host and not _is_private_host(host):
        return "remote"
    if not is_local_style and provider:
        return "remote"
    return "unknown"


def classify_cost_confidence(
    execution_location: str,
    tokens_estimated: bool,
    has_cost_rate: bool,
) -> str:
    """Derive a cost-confidence label from execution location and token source.

    Returns one of ``"high"``, ``"medium"``, ``"low"``, ``"none"``.
    """
    if execution_location == "local":
        return "high" if not tokens_estimated else "medium"
    if execution_location == "lan":
        return "medium" if not tokens_estimated else "low"
    if execution_location == "remote":
        return "medium" if has_cost_rate else "none"
    return "none"


def _has_cost_rate(model: str | None) -> bool:
    """Return ``True`` when the configured cost table carries a rate for *model*."""
    if not model:
        return False
    return model in _load_cost_table()


def _load_cost_table() -> dict[str, dict[str, float]]:
    raw = os.environ.get("LOCAL_LLM_COST_TABLE")
    if not raw:
        return {}
    try:
        table = json.loads(raw)
        if isinstance(table, dict):
            return {str(k): v for k, v in table.items() if isinstance(v, dict)}
    except Exception:
        return {}
    return {}


def estimate_cost_cny(provider: str | None, base_url: str | None, model: str | None,
                      input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Best-effort cost estimate in CNY.

    Returns 0.0 for known-local providers, None when no rate is known. A pricing
    table may be supplied via LOCAL_LLM_COST_TABLE (JSON):
        {"deepseek-chat": {"in_per_1k": 0.001, "out_per_1k": 0.002}, ...}
    """
    if _is_local_provider(provider, base_url):
        return 0.0
    if not model:
        return None
    table = _load_cost_table()
    rates = table.get(model)
    if not rates:
        return None
    try:
        in_rate = float(rates.get("in_per_1k", 0.0))
        out_rate = float(rates.get("out_per_1k", 0.0))
    except (TypeError, ValueError):
        return None
    in_tok = int(input_tokens or 0)
    out_tok = int(output_tokens or 0)
    cost = (in_tok / 1000.0) * in_rate + (out_tok / 1000.0) * out_rate
    return round(cost, 6)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_record_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


def _sanitize_extra(extra: Mapping[str, Any] | None) -> dict[str, Any]:
    if not extra:
        return {}
    clean: dict[str, Any] = {}
    for k, v in extra.items():
        key = str(k)
        if key.lower() in _FORBIDDEN_KEYS:
            continue
        clean[key] = v
    return clean


def build_record(*,
                 project: str | None = None,
                 phase: str | None = None,
                 task_type: str,
                 tool_name: str,
                 profile: str | None = None,
                 model: str | None,
                 provider: str | None,
                 base_url: str | None = None,
                 input_chars: int = 0,
                 output_chars: int = 0,
                 input_tokens: int | None = None,
                 output_tokens: int | None = None,
                 cached_tokens: int | None = None,
                 cache_miss_tokens: int | None = None,
                 duration_ms: int = 0,
                 success: bool = True,
                 cache_hit: bool = False,
                 failure_reason: str | None = None,
                 result_summary: str | None = None,
                 files_referenced: Iterable[str] | None = None,
                 git_commit_before: str | None = None,
                 git_dirty_before: bool | None = None,
                 git_commit_after: str | None = None,
                 git_dirty_after: bool | None = None,
                 request_id: str | None = None,
                 extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Assemble a JSON-serializable ledger record. Does not write anything."""
    tokens_estimated = False
    if input_tokens is None:
        input_tokens = estimate_tokens(input_chars)
        tokens_estimated = True
    if output_tokens is None:
        output_tokens = estimate_tokens(output_chars)
        tokens_estimated = True

    # Cache hits represent zero actual spend regardless of any cost table:
    # we only count tokens that left the local machine.
    if cache_hit:
        cost: float | None = 0.0
    else:
        cost = estimate_cost_cny(provider, base_url, model, input_tokens, output_tokens)

    # M7 (v0.10.0-L): execution location and cost confidence — additive fields
    # that distinguish truly-local Ollama from LAN-proxy Ollama without
    # claiming exact dollar costs for LAN.
    exec_loc = classify_execution_location(provider, base_url)
    has_rate = _has_cost_rate(model)
    confidence = classify_cost_confidence(exec_loc, tokens_estimated, has_rate)

    files = list(files_referenced) if files_referenced else []

    summary_text: str | None = None
    if result_summary is not None:
        s = str(result_summary).replace("\n", " ").strip()
        summary_text = s[:300] if s else None

    failure_text: str | None = None
    if failure_reason is not None:
        f = str(failure_reason).replace("\n", " ").strip()
        failure_text = f[:300] if f else None

    record: dict[str, Any] = {
        "id": _new_record_id(),
        "timestamp": _utc_now_iso(),
        "project": project if project is not None else detect_project(),
        "phase": phase if phase is not None else detect_phase(),
        "task_type": task_type,
        "tool_name": tool_name,
        "profile": profile,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "input_chars": int(input_chars or 0),
        "output_chars": int(output_chars or 0),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cached_tokens": int(cached_tokens) if cached_tokens is not None else None,
        "cache_miss_tokens": int(cache_miss_tokens) if cache_miss_tokens is not None else None,
        "total_tokens": int(input_tokens or 0) + int(output_tokens or 0),
        "tokens_estimated": tokens_estimated,
        "estimated_cost_cny": cost,
        "execution_location": exec_loc,
        "cost_confidence": confidence,
        "duration_ms": int(duration_ms or 0),
        "success": bool(success),
        "cache_hit": bool(cache_hit),
        "failure_reason": failure_text,
        "result_summary": summary_text,
        "files_referenced": files,
        "git_commit_before": git_commit_before,
        "git_dirty_before": git_dirty_before,
        "git_commit_after": git_commit_after,
        "git_dirty_after": git_dirty_after,
        "request_id": request_id,
    }

    sanitized_extra = _sanitize_extra(extra)
    if sanitized_extra:
        record["extra"] = sanitized_extra

    return record


def _resolve_path(path: Path | None) -> Path:
    return Path(path) if path else LEDGER_FILE


_LEDGER_WRITE_FAILURES_MAX_BYTES = 1024 * 1024  # 1 MB before truncation


def _record_write_failure(error: str) -> None:
    """Record a ledger write failure to a bounded diagnostic log. Never raises.

    v0.10.0-G P6-B2-C: previously every ledger write failure was silent —
    ``record_call`` returned ``False`` and callers discarded it.  This helper
    writes one JSONL entry so the operator (and ``mcp_doctor``) can see that
    ledger writes are failing.

    Self-truncates at 1 MB.  Nested ``except: pass`` ensures a broken
    diagnostic log can never cascade into a main-call failure.
    """
    try:
        log_path = LEDGER_DIR / "_ledger_write_failures.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if log_path.exists() and log_path.stat().st_size > _LEDGER_WRITE_FAILURES_MAX_BYTES:
                log_path.unlink()
        except OSError:
            pass
        entry = {
            "ts": _utc_now_iso(),
            "error": str(error)[:500],
        }
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def record_call(record: Mapping[str, Any], path: Path | None = None) -> bool:
    """Append a single ledger record. Never raises.

    Returns True on success, False when disabled or on any IO failure.
    On write failure a diagnostic entry is recorded via
    :func:`_record_write_failure` so operators can detect silent ledger loss.
    """
    if not is_ledger_enabled():
        return False
    try:
        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(record), ensure_ascii=False, default=str)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True
    except Exception as exc:
        _record_write_failure(str(exc))
        return False


def read_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Read all ledger records. Returns [] if missing. Skips malformed lines."""
    target = _resolve_path(path)
    if not target.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(target, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except Exception:
        return out
    return out


_MAX_DIAGNOSTIC_ERRORS = 20  # Bound error details to avoid unbounded memory.


def read_records_with_diagnostics(
    path: Path | None = None,
) -> dict[str, Any]:
    """Read ledger records with skip-count diagnostics.

    Returns a dict with:
      - records: list of valid dict records (same as read_records)
      - total_lines: physical lines in the file
      - empty_lines: blank/whitespace-only lines
      - malformed_json_lines: lines that failed json.loads
      - non_dict_lines: valid JSON values that are not dicts
      - skipped_lines: empty_lines + malformed_json_lines + non_dict_lines
      - errors: list of {line_number, error, snippet} (max 20)

    Missing file returns empty records and zero counts.
    Existing read_records() behavior is unchanged.
    """
    target = _resolve_path(path)
    result: dict[str, Any] = {
        "records": [],
        "total_lines": 0,
        "empty_lines": 0,
        "malformed_json_lines": 0,
        "non_dict_lines": 0,
        "skipped_lines": 0,
        "errors": [],
    }
    if not target.exists():
        return result
    try:
        with open(target, "r", encoding="utf-8") as fh:
            for raw in fh:
                result["total_lines"] += 1
                line = raw.strip()
                if not line:
                    result["empty_lines"] += 1
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    result["malformed_json_lines"] += 1
                    if len(result["errors"]) < _MAX_DIAGNOSTIC_ERRORS:
                        result["errors"].append({
                            "line_number": result["total_lines"],
                            "error": str(exc)[:200],
                            "snippet": raw.strip()[:120],
                        })
                    continue
                if isinstance(obj, dict):
                    result["records"].append(obj)
                else:
                    result["non_dict_lines"] += 1
                    if len(result["errors"]) < _MAX_DIAGNOSTIC_ERRORS:
                        result["errors"].append({
                            "line_number": result["total_lines"],
                            "error": f"expected dict, got {type(obj).__name__}",
                            "snippet": raw.strip()[:120],
                        })
        result["skipped_lines"] = (
            result["empty_lines"]
            + result["malformed_json_lines"]
            + result["non_dict_lines"]
        )
    except Exception:
        pass
    return result


def _zero_summary() -> dict[str, Any]:
    return {
        "calls": 0,
        "successes": 0,
        "failures": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "total_duration_ms": 0,
        "total_cost_cny": 0.0,
        "cost_known_calls": 0,
        "cost_unknown_calls": 0,
    }


def summarize(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate ledger records into totals."""
    summary = _zero_summary()
    for r in records:
        summary["calls"] += 1
        if r.get("success"):
            summary["successes"] += 1
        else:
            summary["failures"] += 1
        summary["total_input_tokens"] += int(r.get("input_tokens") or 0)
        summary["total_output_tokens"] += int(r.get("output_tokens") or 0)
        summary["total_tokens"] += int(r.get("total_tokens") or 0)
        summary["total_duration_ms"] += int(r.get("duration_ms") or 0)
        cost = r.get("estimated_cost_cny")
        if cost is None:
            summary["cost_unknown_calls"] += 1
        else:
            try:
                summary["total_cost_cny"] += float(cost)
                summary["cost_known_calls"] += 1
            except (TypeError, ValueError):
                summary["cost_unknown_calls"] += 1
    summary["total_cost_cny"] = round(summary["total_cost_cny"], 6)
    return summary


def group_by(records: Iterable[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    """Group records by a field and summarize each group. Missing key → '<none>'."""
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for r in records:
        raw = r.get(key)
        bucket_key = str(raw) if raw is not None and raw != "" else "<none>"
        buckets.setdefault(bucket_key, []).append(r)
    return {k: summarize(v) for k, v in buckets.items()}


def breakdown_counts(records: Iterable[Mapping[str, Any]], key: str,
                     default: str = "unknown") -> dict[str, int]:
    """Count records by *key*. Missing/empty key → *default*.

    Returns a plain ``{value: count}`` dict — no token/cost aggregation.
    """
    counts: dict[str, int] = {}
    for r in records:
        val = r.get(key)
        if val is None or val == "":
            val = default
        else:
            val = str(val)
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items()))


def filter_failures(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in records if not r.get("success")]


def recent(records: Iterable[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    items = [dict(r) for r in records]
    if limit is None or limit <= 0:
        return []
    return items[-limit:]


def _extra_value(record: Mapping[str, Any], key: str) -> object | None:
    """Extract a value from record['extra'][key], or None if unavailable."""
    extra = record.get("extra")
    if not isinstance(extra, dict):
        return None
    val = extra.get(key)
    if val is None or val == "":
        return None
    return val


# P2-D1: group records by a key in the `extra` dict, with optional
# fallback to a top-level key when the extra key is unavailable.
def group_by_extra(records: Iterable[Mapping[str, Any]], key: str,
                   fallback_key: str | None = None) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for r in records:
        val = _extra_value(r, key)
        if val is None and fallback_key:
            raw = r.get(fallback_key)
            val = str(raw) if raw is not None and raw != "" else None
        bucket_key = str(val) if val is not None else "<none>"
        buckets.setdefault(bucket_key, []).append(r)
    return {k: summarize(v) for k, v in buckets.items()}


# P2-D1: filter records that carry escalation extra fields.
def filter_escalations(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        extra = r.get("extra")
        if not isinstance(extra, dict):
            continue
        if extra.get("auto_escalated") is True:
            out.append(dict(r))
            continue
        if any(extra.get(f) is not None for f in (
            "parent_request_id", "escalation_trigger",
            "escalation_from_profile", "escalation_to_profile",
            "escalation_depth",
        )):
            out.append(dict(r))
    return out


# P2-D1: filter records that carry debate extra fields.
def filter_debates(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in records
            if isinstance(r.get("extra"), dict)
            and r["extra"].get("debate_mode") is True]


# B1-B: filter records where a debate was skipped via preclassifier.
def filter_debate_skips(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(r) for r in records
            if isinstance(r.get("extra"), dict)
            and r["extra"].get("debate_skipped") is True]


# B1-B: aggregate stats for debate-skip records.
def summarize_debate_skips(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    skips = filter_debate_skips(records)
    total = len(skips)
    by_risk: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    by_profile: dict[str, int] = {}
    for r in skips:
        extra = r.get("extra") or {}
        rl = extra.get("diff_risk_level", "unknown") or "unknown"
        rc = extra.get("diff_risk_confidence", "unknown") or "unknown"
        pp = extra.get("preclassifier_profile", "unknown") or "unknown"
        by_risk[rl] = by_risk.get(rl, 0) + 1
        by_confidence[rc] = by_confidence.get(rc, 0) + 1
        by_profile[pp] = by_profile.get(pp, 0) + 1
    return {
        "total_skipped": total,
        "by_risk_level": dict(sorted(by_risk.items())),
        "by_confidence": dict(sorted(by_confidence.items())),
        "by_preclassifier_profile": dict(sorted(by_profile.items())),
        "estimated_debate_seconds_saved": total * 500,
        "estimated_tokens_saved": total * 100_000,
        "skipped_records": skips,
    }


# ---------------------------------------------------------------------------
# Ledger lifecycle (v0.10.0-H M3)
# ---------------------------------------------------------------------------

def rotate_ledger(archive_name: str | None = None,
                  path: Path | None = None) -> tuple[bool, str]:
    """Archive the active ``calls.jsonl`` and start a fresh one. Never raises.

    Renames the current ledger file to an archive name so the next
    :func:`record_call` creates a new ledger.  The archive file lives next to
    the active ledger and remains readable via ``--path`` in the CLI.

    Args:
        archive_name: Target archive filename (e.g. ``calls.2026-05-24.jsonl``).
            Defaults to ``calls.<ISO-8601-date>.jsonl``.
        path: Path to the active ledger file. Defaults to :data:`LEDGER_FILE`.

    Returns:
        ``(ok, detail)`` where *ok* is ``True`` when the rotation succeeded
        (or there was nothing to rotate) and *detail* is a human-readable
        explanation.  ``(False, reason)`` when the target archive already
        exists or an OS error occurs.  Never raises.
    """
    target = _resolve_path(path)
    if not target.exists():
        return True, f"nothing to rotate: {target} does not exist"
    if target.stat().st_size == 0:
        return True, f"nothing to rotate: {target} is empty"

    if archive_name is None:
        archive_name = f"calls.{_utc_now_iso()[:10]}.jsonl"
    archive = target.parent / archive_name

    try:
        if archive.exists():
            return False, (
                f"archive target already exists: {archive}\n"
                f"  choose a different --archive-name or move/delete the existing file"
            )
        target.rename(archive)
    except OSError as exc:
        return False, f"rotation failed: {exc}"

    return True, f"archived {target.name} → {archive.name} ({archive.stat().st_size} bytes)"
