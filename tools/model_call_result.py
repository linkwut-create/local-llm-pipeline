#!/usr/bin/env python3
"""ModelCallResult + normalize_usage — Call Ledger v2-A (non-stream).

ModelCallResult is the return type for non-stream provider calls in
tools/local_llm_worker.py. It carries the model's text content plus the
provider's normalized usage block (or None when the provider did not report
usage). Streaming paths are intentionally not touched in v2-A — see
docs/CALL_LEDGER_V2_PLAN.md §3.2 / §6 for the v2-B plan.

normalize_usage(provider, data) is the single entry point for mapping a raw
provider response payload to the normalized usage shape. It is a pure
function with no IO; it never raises and returns None on absence or
malformed input.

Normalized usage shape (when not None):

    {
        "input_tokens":      int,
        "output_tokens":     int,
        "total_tokens":      int,
        "cached_tokens":     int | None,    # DeepSeek prompt_cache_hit_tokens
        "cache_miss_tokens": int | None,    # DeepSeek prompt_cache_miss_tokens
        "provider_raw":      dict,          # untouched original usage block
    }

This module is part of Call Ledger v2-A. v2-B (streaming usage passthrough)
and v2-C (cache-tier cost estimation) are separate work.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelCallResult:
    """Return type for non-stream provider calls.

    `content` is the model's text output (may be empty string for a
    degenerate response — the empty check happens downstream in
    call_model_with_retry).

    `usage` is the normalized usage block (see module docstring), or None
    when the provider did not report usage or normalization failed.

    `raw_provider` echoes the provider tag used in the call ('ollama' or
    'openai-compatible') so downstream code can distinguish without
    re-reading config.
    """
    content: str = ""
    usage: dict | None = None
    raw_provider: str | None = None


_OLLAMA_RAW_KEYS = (
    "prompt_eval_count",
    "eval_count",
    "prompt_eval_duration",
    "eval_duration",
    "total_duration",
)


def normalize_usage(provider: str | None, data) -> dict | None:
    """Map a raw provider response payload to normalized usage.

    Returns None when:
      - provider is None or unrecognized
      - data is not a dict
      - the provider's usage block is absent
      - any required field is missing or wrong type

    Never raises.
    """
    if not provider or not isinstance(data, dict):
        return None
    if provider == "ollama":
        return _normalize_ollama(data)
    if provider == "openai-compatible":
        return _normalize_openai_compat(data)
    return None


def _coerce_int(value, default=None):
    """Coerce to int. Returns `default` (None unless overridden) on failure.

    bool is a subclass of int in Python; treat True/False as invalid since
    a provider should not return a boolean for a token count.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def _normalize_ollama(data: dict) -> dict | None:
    in_tok = _coerce_int(data.get("prompt_eval_count"))
    out_tok = _coerce_int(data.get("eval_count"))
    if in_tok is None or out_tok is None:
        return None
    if in_tok < 0 or out_tok < 0:
        return None
    return {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "cached_tokens": None,
        "cache_miss_tokens": None,
        "provider_raw": {k: data[k] for k in _OLLAMA_RAW_KEYS if k in data},
    }


def _normalize_openai_compat(data: dict) -> dict | None:
    u = data.get("usage")
    if not isinstance(u, dict):
        return None
    in_tok = _coerce_int(u.get("prompt_tokens"))
    out_tok = _coerce_int(u.get("completion_tokens"))
    if in_tok is None or out_tok is None:
        return None
    if in_tok < 0 or out_tok < 0:
        return None
    total = _coerce_int(u.get("total_tokens"))
    if total is None:
        total = in_tok + out_tok
    elif total < 0:
        total = in_tok + out_tok

    cached_raw = u.get("prompt_cache_hit_tokens")
    miss_raw = u.get("prompt_cache_miss_tokens")
    cached_tok = _coerce_int(cached_raw) if cached_raw is not None else None
    miss_tok = _coerce_int(miss_raw) if miss_raw is not None else None
    # Refuse silently invalid negatives — treat as absent.
    if cached_tok is not None and cached_tok < 0:
        cached_tok = None
    if miss_tok is not None and miss_tok < 0:
        miss_tok = None

    return {
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": total,
        "cached_tokens": cached_tok,
        "cache_miss_tokens": miss_tok,
        "provider_raw": dict(u),
    }
