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


def record_call(record: Mapping[str, Any], path: Path | None = None) -> bool:
    """Append a single ledger record. Never raises.

    Returns True on success, False when disabled or on any IO failure.
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
    except Exception:
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
