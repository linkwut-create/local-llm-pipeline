#!/usr/bin/env python3
"""
Local LLM MCP Server — exposes read-only CLI tools as MCP (Model Context Protocol) tools.

Transport: stdio JSON-RPC 2.0.
Read-only: never modifies source files, never runs arbitrary commands.

Usage:
    python tools/local_llm_mcp_server.py
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid

import requests
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from local_llm_worker import is_blocked_path
from health_store import load_profile_health, record_invocation

# Concurrency guard: prevent multiple LLM calls from competing for GPU
_call_lock = threading.Lock()

# Quality-based escalation chain (Layer 4): task → ordered profiles by capability.
# When confidence=low or uncertain_points>3, the server auto-escalates to the next tier.
# Timeout errors fall back to a faster model instead.
_ESCALATION_CHAIN = {
    # Summarization: fast/e4b → smart/9b → gemma4-26b llama.cpp (0.4s!) → qwen3.6-27b
    "summarize-file": ["fast_summary", "smart_summary", "gemma4_26b_llamacpp",
                       "gemma4_26b", "qwen3.6_27b_mtp", "code_worker"],
    "summarize-tree": ["fast_summary", "smart_summary", "gemma4_26b_llamacpp",
                       "qwen3.6_27b_mtp"],
    # Diff review: commit reviewer (30b) → nemotron reasoning → 27b → 35b deep
    "review-diff": ["commit_reviewer", "diff_reviewer", "qwen3.6_27b_mtp",
                    "deep_reviewer"],
    # Code generation: coder → gemma4 fast path → 27b → 35b
    "generate-test-plan": ["code_worker", "gemma4_26b_llamacpp", "qwen3.6_27b_mtp",
                           "deep_reviewer"],
    "generate-test-draft": ["code_worker", "qwen3.6_27b_mtp", "deep_reviewer"],
    "draft-fix": ["code_worker", "qwen3.6_27b_mtp", "deep_reviewer"],
    "draft-feature": ["code_worker", "qwen3.6_27b_mtp", "deep_reviewer"],
    "draft-refactor": ["code_worker", "reasoning_checker", "deep_reviewer"],
    # Suggestions: fast llama.cpp → 27b → coder → 35b
    "suggest-improvements": ["gemma4_26b_llamacpp", "qwen3.6_27b_mtp",
                             "code_worker", "deep_reviewer"],
    # Deep/architecture review: 35b MoE → 35b → 31b Opus → 128b → nemotron super → 120b
    "deep-code-review": ["qwen3.6_35b_moe_mtp", "deep_reviewer", "gemma4_31b",
                         "release_auditor", "nemotron_super", "heavy_reviewer"],
    "architecture-review": ["qwen3.6_35b_moe_mtp", "deep_reviewer", "gemma4_31b",
                            "release_auditor", "nemotron_super", "heavy_reviewer"],
    # Release: 128b → nemotron super → 35b
    "release-risk-review": ["release_auditor", "nemotron_super", "deep_reviewer",
                            "qwen3.6_35b_moe_mtp"],
    # Reasoning: nemotron → deepseek-r1-32b → 128b (70b unavailable, API timeout)
    "risk-analysis": ["reasoning_checker", "deep_reasoning", "release_auditor"],
    "logic-check": ["reasoning_checker", "deep_reasoning", "release_auditor"],
    "failure-mode-analysis": ["reasoning_checker", "deep_reasoning",
                               "release_auditor"],
    "contextual-analyze": ["qwen3.6_27b_mtp", "code_worker", "reasoning_checker"],
    "translate-text": ["translation", "qwen3.6_27b_mtp"],
    "rewrite-text": ["fast_summary", "smart_summary", "gemma4_26b_llamacpp",
                     "qwen3.6_27b_mtp"],
    "extract-todos": ["code_worker", "gemma4_26b_llamacpp", "qwen3.6_27b_mtp"],
    "find-related-files": ["code_worker", "gemma4_26b_llamacpp", "qwen3.6_27b_mtp"],
}

# Security-sensitive patterns that auto-trigger reasoning model review.
# These patterns imply eval/exec/subprocess/file-op risk that needs deeper analysis.
# Word-boundary patterns (simple identifiers/keywords).
_SECURITY_CODE_RE = re.compile(
    r'\b(eval|exec|compile|__import__|subprocess|os\.system|os\.popen'
    r'|pickle\.loads?|pickle\.dumps?|marshal\.loads?'
    r'|shell\s*=\s*True)\b',
    re.IGNORECASE,
)
# Shell-command patterns (spaces, slashes, flags — no \b boundary).
_SECURITY_SHELL_RE = re.compile(
    r'(rm\s+-rf?\s+/|del\s+/[sfq]\s+/\S'
    r'|chmod\s+[+]?777|chmod\s+[+-]?[rwx]*s'
    r'|Remove-Item\s+-Recurse\s+-Force)',
    re.IGNORECASE,
)


def _has_security_sensitive_patterns(text: str) -> bool:
    """Check if text contains patterns that warrant reasoning-model review."""
    return bool(_SECURITY_CODE_RE.search(text) or _SECURITY_SHELL_RE.search(text))


# Content-type detection patterns (first 2KB of input is usually enough)
_SHELL_RE = re.compile(
    r'^#!(?:/usr)?/bin/(?:ba)?sh|^#!\s*/usr/bin/env\s+(?:ba)?sh'
    r'|\$\{|export\s+\w+=|\b(?:chmod|chown|sudo|apt|brew|pip|npm|docker)\b',
    re.MULTILINE,
)
_CONFIG_RE = re.compile(
    r'^[{[]\s*$|^\s*"[^"]+"\s*:\s*|^\s*\w+\s*:\s*'
    r'|^\s*\[[^\]]+\]\s*$|^[^=]*=\s*(?:true|false|yes|no|"[^"]*"|\d+)',
    re.MULTILINE,
)
_DOCS_RE = re.compile(
    r'^#{1,6}\s+\w+|^\*\*[^*]+\*\*|^[-*]\s+\w+|\[.+\]\(.+\)'
    r'|^>\s+|^\|.+\|',
    re.MULTILINE,
)


def _detect_content_type(text: str) -> str:
    """Detect the type of content for routing decisions.

    Returns one of: "shell", "code", "config", "docs", "unknown".
    Uses first 4KB for detection — enough to catch shebangs and structure.
    """
    sample = text[:4096] if len(text) > 4096 else text
    if not sample.strip():
        return "unknown"

    # Shebangs or shell patterns → shell
    if _SHELL_RE.search(sample):
        return "shell"

    # Strong config indicators first (before code, since configs can look like code)
    config_lines = len(_CONFIG_RE.findall(sample))
    total_lines = max(sample.count('\n'), 1)
    if config_lines > total_lines * 0.4:
        return "config"

    # Code detection: high density of code keywords
    code_lines = len(_CODE_LINE_RE.findall(sample))
    if code_lines > total_lines * 0.15:
        return "code"

    # Docs: markdown patterns, high prose density
    docs_lines = len(_DOCS_RE.findall(sample))
    if docs_lines > 0:
        return "docs"

    # Fallback: high prose-to-code ratio → docs
    if code_lines == 0 and total_lines > 5:
        return "docs"

    return "unknown"


# Logic-indicator patterns for proactive routing (reused from call_review_diff).
_LOGIC_RE = re.compile(
    r'^(?:[+-]\s*)?(?:def |class |async |await |return |if __|import |from \w+ import'
    r'|@\w+|raise |yield |with |try:|except |finally:|while |for )',
    re.MULTILINE,
)

# Code-density patterns: lines that look like source code vs prose.
_CODE_LINE_RE = re.compile(
    r'^\s*(def |class |import |from |#|//|/\*|package |use |require |fn |pub |let |var |const )',
    re.MULTILINE,
)


def _classify_input_complexity(text: str, *, is_diff: bool = False) -> dict:
    """Analyze input text and return routing-relevant characteristics.

    Used by tool handlers to make proactive profile selections before the
    first worker invocation.  Cheap — regex-only, no model calls.

    Returns a dict with keys used by callers for routing decisions.
    """
    char_count = len(text)
    line_count = text.count('\n') + 1 if text else 0
    cjk_ratio = _detect_cjk_ratio(text)
    has_security = _has_security_sensitive_patterns(text)
    content_type = _detect_content_type(text)

    # File count (diff mode) or code-line density (file mode)
    file_count = 0
    has_logic = False
    code_density = 0.0

    if is_diff:
        file_count = len(re.findall(r'^diff --git ', text, re.MULTILINE))
        has_logic = bool(_LOGIC_RE.search(text))
    else:
        if text:
            code_lines = len(_CODE_LINE_RE.findall(text))
            total_lines = max(line_count, 1)
            code_density = code_lines / total_lines

    # Complexity tier for routing decisions
    if char_count > 200_000 or line_count > 5_000 or file_count > 10:
        tier = "massive"
    elif char_count > 80_000 or line_count > 2_000 or file_count > 5 or has_security:
        tier = "heavy"
    elif char_count > 20_000 or line_count > 500 or file_count >= 3 or cjk_ratio > 0.1:
        tier = "normal"
    else:
        tier = "light"

    return {
        "char_count": char_count,
        "line_count": line_count,
        "file_count": file_count,
        "cjk_ratio": cjk_ratio,
        "has_security": has_security,
        "has_logic": has_logic,
        "code_density": code_density,
        "complexity_tier": tier,
        "content_type": content_type,
        "_input_text": text[:32_768],  # for arch-pattern detection in routing
    }


def _resolve_starting_profile(task: str, info: dict, user_profile: str | None = None,
                               is_commit_gate: bool = False) -> str:
    """Pick the right starting profile based on input complexity.

    Maps complexity_tier to escalation chain index:
      "light"  → chain[0] (smallest/fastest)
      "normal" → chain[1] (mid-tier, CJK-capable if needed)
      "heavy"  → chain[2] (skip small models, jump to mid/deep)

    Special cases:
    - user_profile always wins (respect explicit choice)
    - commit_gate always returns commit_reviewer (safety)
    - has_security patterns → reasoning tier (skip code review models)
    - Falls back through chain if resolved profile is unhealthy
    """
    # 1. User override wins
    if user_profile:
        return user_profile

    # 2. Commit gate: always commit_reviewer
    if is_commit_gate:
        return "commit_reviewer"

    chain = _ESCALATION_CHAIN.get(task, [])
    if not chain:
        return "fast_summary"

    tier = info.get("complexity_tier", "light")
    has_security = info.get("has_security", False)
    cjk_ratio = info.get("cjk_ratio", 0.0)
    content_type = info.get("content_type", "unknown")

    # 3a. Content-type adjustments: shell/config/docs get special treatment
    if content_type == "shell":
        # Shell scripts → always use security-aware model
        tier = "heavy" if tier == "light" else tier
    elif content_type == "config" and tier != "massive":
        # Config files are simple structure → step down
        tier = "light"
    elif content_type == "docs" and tier != "massive":
        # Documentation doesn't need deep review → keep light/normal
        if tier == "heavy":
            tier = "normal"

    # 3. Security-sensitive → skip straight to reasoning (even if not in task chain)
    if has_security and task != "rewrite-text":
        security_targets = ["reasoning_checker", "deep_reasoning",
                            "release_auditor"]
        for p in security_targets:
            if _profile_is_healthy(p):
                print(f"MCP: security patterns detected -> routing to {p}", file=sys.stderr)
                return p
        # Fallback: if no reasoning profile is healthy, use highest in chain
        if chain:
            print(f"MCP: security patterns detected but no healthy reasoning profile, using {chain[-1]}", file=sys.stderr)
            return chain[-1]

    # Architecture-significant patterns for deep/architecture review tasks
    _ARCH_PATTERNS = re.compile(
        r'\b(__init__|abstract|interface|protocol|Metaclass|BaseModel'
        r'|middleware|pipeline|plugin|migration|schema|router|serializer'
        r'|descriptor|dataclass|dependency_injection|factory)\b',
        re.IGNORECASE,
    )
    has_arch = False
    if task in ("deep-code-review", "architecture-review", "release-risk-review"):
        has_arch = bool(_ARCH_PATTERNS.search(
            info.get("_input_text", "")))

    # 4. Map complexity tier to chain index
    tier_map = {"light": 0, "normal": 1, "heavy": 2, "massive": 4}
    index = tier_map.get(tier, 0)

    # Architecture keywords at heavy+ → boost by 1 index
    if has_arch and tier in ("heavy", "massive"):
        index = min(index + 1, len(chain) - 1)

    index = min(index, len(chain) - 1)
    profile = chain[index]

    # 5. Massive tier: differentiated large model selection
    if tier == "massive" and len(chain) >= 5:
        has_security = info.get("has_security", False)
        has_logic = info.get("has_logic", False)
        file_count = info.get("file_count", 0)
        # Security-heavy massive → prefer nemotron_super if in chain
        if has_security and "nemotron_super" in chain:
            ns_idx = chain.index("nemotron_super")
            if ns_idx > index and _profile_is_healthy(chain[ns_idx]):
                profile = chain[ns_idx]
                index = ns_idx
        # Multi-file diff with logic → prefer release_auditor
        elif has_logic and file_count > 3 and "release_auditor" in chain:
            ra_idx = chain.index("release_auditor")
            if ra_idx > index and _profile_is_healthy(chain[ra_idx]):
                profile = chain[ra_idx]
                index = ra_idx
        # Many files → prefer heavy_reviewer for context breadth
        elif file_count > 8 and "heavy_reviewer" in chain:
            hr_idx = chain.index("heavy_reviewer")
            if hr_idx > index and _profile_is_healthy(chain[hr_idx]):
                profile = chain[hr_idx]
                index = hr_idx

    # 6. CJK-aware: if normal/heavy/massive with CJK, prefer CJK-capable
    if tier in ("normal", "heavy", "massive") and cjk_ratio > 0.1:
        if profile not in _CJK_CAPABLE_PROFILES:
            cjk_target = _prefer_cjk_profile(chain[0], task)
            if cjk_target and _profile_is_healthy(cjk_target):
                profile = cjk_target

    # 6a. Strength-aware: at heavy+ tier, prefer profile with matching strengths
    if tier in ("heavy", "massive") and len(chain) >= 3:
        try:
            profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
            pd = json.loads(profiles_path.read_text(encoding="utf-8"))
            task_strength_map = {
                "review-diff": ["code-review", "diff-analysis", "coding"],
                "deep-code-review": ["deep-review", "coding"],
                "architecture-review": ["architecture", "deep-review"],
                "risk-analysis": ["risk-analysis", "reasoning", "logic"],
                "logic-check": ["logic", "reasoning"],
                "failure-mode-analysis": ["reasoning", "deep-analysis"],
                "generate-test-plan": ["test-generation", "coding"],
                "suggest-improvements": ["coding", "refactoring"],
                "summarize-file": ["summarization", "speed"],
                "summarize-tree": ["summarization", "speed"],
                "translate-text": ["translation", "multilingual"],
                "release-risk-review": ["release-audit", "deep-review"],
            }
            wanted = task_strength_map.get(task, [])
            if wanted:
                # Score profiles in chain starting from current index
                best_score = -1
                best_p = profile
                for i in range(index, len(chain)):
                    p_cfg = pd.get("profiles", {}).get(chain[i], {})
                    p_strengths = p_cfg.get("_strengths", [])
                    score = sum(1 for s in wanted if s in p_strengths)
                    if score > best_score and _profile_is_healthy(chain[i]):
                        best_score = score
                        best_p = chain[i]
                if best_p != profile and best_score > 0:
                    print(f"MCP: strength match — {best_p} ({best_score}/{len(wanted)} strengths)", file=sys.stderr)
                    profile = best_p
        except Exception:
            pass

    # 6b. Backend-aware + GPU-aware: prefer llama.cpp for speed, Ollama for stability
    try:
        profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
        pd6 = json.loads(profiles_path.read_text(encoding="utf-8"))
        loaded = _get_loaded_models()
        all_loaded = loaded.get("ollama", set()) | loaded.get("llamacpp", set())
        if all_loaded:
            p_cfg = pd6.get("profiles", {}).get(profile, {})
            p_model = p_cfg.get("model", "")
            p_has_env = bool(p_cfg.get("_env", ""))
            p_variant = p_cfg.get("_variant_of", "")

            # Backend preference: use llama.cpp for fast tasks when available
            is_fast_task = task in ("summarize-file", "summarize-tree",
                                    "suggest-improvements", "rewrite-text",
                                    "extract-todos", "find-related-files")

            # For fast tasks, jump to llama.cpp variant if healthy (endpoint alive)
            if is_fast_task and "gemma4_26b_llamacpp" in chain:
                # Check endpoint health + any model is loaded (name may differ from profile)
                if (loaded.get("llamacpp")  # at least 1 model loaded
                        and _profile_is_healthy("gemma4_26b_llamacpp")):
                    ollama_name = profile
                    profile = "gemma4_26b_llamacpp"
                    index = chain.index(profile)
                    print(f"MCP: backend-preference — {ollama_name} -> {profile} (llama.cpp, 0.4s)", file=sys.stderr)

            # If current profile's model is NOT loaded, check neighbors
            elif p_model and p_model not in all_loaded:
                for i in range(index - 1, index + 2):
                    if 0 <= i < len(chain) and i != index:
                        nb_cfg = pd6.get("profiles", {}).get(chain[i], {})
                        nb_model = nb_cfg.get("model", "")
                        # Prefer llama.cpp-loaded models for speed
                        nb_loaded = nb_model in loaded.get("llamacpp", set())
                        nb_ollama = nb_model in loaded.get("ollama", set())
                        if (nb_loaded or nb_ollama) and _profile_is_healthy(chain[i]):
                            backend = "llamacpp" if nb_loaded else "ollama"
                            print(f"MCP: GPU-aware — {profile} not loaded, using {chain[i]} ({backend})", file=sys.stderr)
                            profile = chain[i]
                            index = i
                            break
    except Exception:
        pass

    # 7. Health fallback: if resolved profile is unhealthy, try next
    if not _profile_is_healthy(profile):
        for i in range(index + 1, len(chain)):
            if _profile_is_healthy(chain[i]):
                profile = chain[i]
                print(f"MCP: {chain[index]} unhealthy -> fell back to {profile}", file=sys.stderr)
                break

    print(f"MCP: complexity-based routing — tier={tier} profile={profile}", file=sys.stderr)
    return profile


def _profile_is_healthy(profile_name: str) -> bool:
    """Check if a profile is healthy (best-effort, always True on failure).

    Reads runtime health from `.local_llm_out/local_llm_health.json`
    (MCP Health Telemetry Isolation P1-H.2). Still reads the static
    `_env` field from `tools/local_llm_profiles.json` for the optional
    llama.cpp endpoint probe.

    Thresholds unchanged: consecutive_failures>=2 or success_rate<0.5
    is unhealthy. Missing runtime health is treated as healthy.
    """
    try:
        profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
        pd = json.loads(profiles_path.read_text(encoding="utf-8"))
        p = pd.get("profiles", {}).get(profile_name, {})
        health = load_profile_health(profile_name)
        if health.get("consecutive_failures", 0) >= 2:
            return False
        if health.get("success_rate", 1.0) < 0.5:
            return False
        # For llama.cpp profiles, probe the endpoint
        env_str = p.get("_env", "")
        for part in env_str.split(" "):
            if part.startswith("LOCAL_LLM_BASE_URL="):
                base_url = part.split("=", 1)[1].rstrip("/")
                try:
                    url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
                    resp = requests.get(url, timeout=5)
                    if resp.status_code != 200:
                        return False
                except Exception:
                    return False
                break
        return True
    except Exception:
        return True  # Best-effort


_LOADED_MODELS_CACHE: tuple[float, dict[str, set[str]]] = (0.0, {})


def _get_loaded_models() -> dict[str, set[str]]:
    """Query both Ollama /api/ps and llama.cpp /v1/models for loaded models.

    Returns {"ollama": {model_names}, "llamacpp": {model_names}}.
    Cached for 30 seconds.
    """
    global _LOADED_MODELS_CACHE
    now = time.time()
    if now - _LOADED_MODELS_CACHE[0] < 30:
        return _LOADED_MODELS_CACHE[1]

    result = {"ollama": set(), "llamacpp": set()}

    # Query Ollama
    try:
        ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        resp = requests.get(f"{ollama_host}/api/ps", timeout=5)
        if resp.status_code == 200:
            for entry in resp.json().get("models", []):
                name = entry.get("name", "")
                if name:
                    result["ollama"].add(name)
                    if name.endswith(":latest"):
                        result["ollama"].add(name.rsplit(":", 1)[0])
    except Exception:
        pass

    # Query llama.cpp endpoints (from _env profiles)
    try:
        profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
        pd = json.loads(profiles_path.read_text(encoding="utf-8"))
        for name, cfg in pd.get("profiles", {}).items():
            env_str = cfg.get("_env", "")
            for part in env_str.split(" "):
                if part.startswith("LOCAL_LLM_BASE_URL="):
                    base_url = part.split("=", 1)[1].rstrip("/")
                    url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
                    resp = requests.get(url, timeout=5)
                    if resp.status_code == 200:
                        for m in resp.json().get("data", []):
                            m_name = m.get("id", "")
                            if m_name:
                                result["llamacpp"].add(m_name)
                    break
    except Exception:
        pass

    _LOADED_MODELS_CACHE = (now, result)
    return result


def _detect_cjk_ratio(text: str) -> float:
    """Return the fraction of CJK characters in text (0.0 - 1.0).

    Used for language-aware routing: when ratio > 0.1, prefer CJK-capable profiles.
    """
    if not text:
        return 0.0
    cjk_count = 0
    total = 0
    for ch in text:
        total += 1
        cp = ord(ch)
        for lo, hi in _CJK_RANGES:
            if lo <= cp <= hi:
                cjk_count += 1
                break
    return cjk_count / total if total > 0 else 0.0


def _prefer_cjk_profile(current_profile: str, task: str) -> str | None:
    """If the current profile is not CJK-capable but CJK is detected,
    return a CJK-capable replacement from the escalation chain."""
    chain = _ESCALATION_CHAIN.get(task, [])
    # Find the first CJK-capable profile in the chain at or above current level
    for p in chain:
        if p in _CJK_CAPABLE_PROFILES:
            if p == current_profile:
                return None  # Already on a CJK-capable profile
            return p
    # Fallback: any CJK-capable profile in the chain
    for p in chain:
        if p in _CJK_CAPABLE_PROFILES:
            return p
    return None


def _update_model_health(profile_name: str, ok: bool, elapsed_s: float,
                          error_type: str = ""):
    """Record per-invocation health telemetry via the runtime health
    store (MCP Health Telemetry Isolation P1-H.2).

    Previously wrote into each profile's `_health` block in
    `tools/local_llm_profiles.json`, dirtying the configuration file
    on every MCP call. Now delegates to
    `tools.health_store.record_invocation`, which persists into
    `.local_llm_out/local_llm_health.json` (gitignored).

    Same 90/10 weighted formula, same field shape, same best-effort
    contract — only the storage location changed.
    """
    record_invocation(profile_name, ok=ok, elapsed_s=elapsed_s,
                      error_type=error_type)

_MAX_ESCALATION_DEPTH = 2  # Allow up to 2 escalation hops (3 total invocations). Safe with _tried_profiles loop prevention.


# MCP Cost Discipline P3-B: env knob constants + parser.
# Defined but NOT wired into _check_quality_escalation yet — P3-B is the
# helper/plumbing phase; behavioral flip lives in P3-C1 / P3-C2. The
# current default-on behavior for `confidence=="low"` and
# `len(uncertain_points) > 3` is preserved unchanged at this commit.
# See docs/MCP_COST_DISCIPLINE_PLAN.md §4.2 for the P3 target table.
_ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE = "LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE"
_ENV_AUTO_ESCALATE_ON_UNCERTAIN = "LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN"


def _parse_env_flag(name: str, default: bool = False) -> bool:
    """Parse an environment variable as a boolean.

    - Unset → ``default``.
    - Truthy values ``true`` / ``1`` / ``yes`` / ``on`` (case-insensitive,
      whitespace-trimmed) → ``True``.
    - Falsy values ``false`` / ``0`` / ``no`` / ``off`` and the empty
      string (after trim) → ``False`` (explicit; does not fall back to
      ``default``).
    - Unrecognized non-empty values → ``default``.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("", "false", "0", "no", "off"):
        return False
    return default


# CJK Unicode ranges for language-aware routing (Phase 3A)
_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0xAC00, 0xD7AF),   # Hangul Syllables
    (0x3000, 0x303F),   # CJK Symbols/Punctuation
    (0xFF00, 0xFFEF),   # Fullwidth Forms
    (0x2E80, 0x2EFF),   # CJK Radicals Supplement
]

# Profiles known to handle CJK/multilingual content well
_CJK_CAPABLE_PROFILES = {"translation", "qwen3.6_27b_mtp", "qwen3.6_35b_moe_mtp",
                         "smart_summary", "code_worker", "deep_reviewer",
                         "reasoning_checker", "gemma4_31b", "gemma4_26b",
                         "gemma4_26b_llamacpp",
                         "nemotron_super", "command_r"}


def _check_quality_escalation(payload: dict, current_profile: str, task: str,
                               cjk_ratio: float = 0.0,
                               _tried_profiles: set[str] | None = None) -> str | None:
    """Determine if quality signals warrant escalating to a more capable profile.

    Returns the next profile name, or None if no escalation is needed.
    Skips profiles already in _tried_profiles to prevent loops.
    """
    chain = _ESCALATION_CHAIN.get(task, [])
    if current_profile not in chain or len(chain) < 2:
        return None
    idx = chain.index(current_profile)
    tried = _tried_profiles or set()
    error_type = (payload.get("error_type") or "").lower()
    confidence = (payload.get("confidence") or "medium").lower()
    uncertain_count = len(payload.get("uncertain_points") or [])

    def _next_untried(start_idx: int, direction: int = 1) -> str | None:
        """Find the next untried profile in the given direction."""
        i = start_idx + direction
        while 0 <= i < len(chain):
            if chain[i] not in tried:
                return chain[i]
            i += direction
        return None

    # Timeout → step down to a lighter/faster model (skip tried)
    if error_type == "timeout":
        target = _next_untried(idx, -1)
        if target:
            print(f"MCP: quality escalation — timeout, downgrading {current_profile} → {target}", file=sys.stderr)
            return target
        return None

    # Low confidence → escalate to next tier (prefer CJK-capable if CJK detected).
    # MCP Cost Discipline P3-C1: default OFF. Legacy "always escalate on
    # confidence=low" behavior is restorable via the env knob
    # LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE=true (see
    # docs/MCP_COST_DISCIPLINE_PLAN.md §4.2). When the knob is OFF we fall
    # through to the uncertain_points check rather than short-circuiting,
    # so a payload with confidence=low AND uncertain_points>3 still
    # escalates via the uncertain branch. P3-C2 will gate the
    # uncertain_points branch behind LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN.
    if confidence == "low" and _parse_env_flag(
            _ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, default=False):
        target = None
        if cjk_ratio > 0.1 and current_profile not in _CJK_CAPABLE_PROFILES:
            target = _prefer_cjk_profile(current_profile, task)
            if target is not None and target in tried:
                target = None
        if target is None:
            target = _next_untried(idx, 1)
        if target:
            print(f"MCP: quality escalation — confidence=low, upgrading {current_profile} → {target}", file=sys.stderr)
            return target
        return None

    # Many uncertain points → escalate
    if uncertain_count > 3:
        target = _next_untried(idx, 1)
        if target:
            # If CJK detected and target is not CJK-capable, look further
            if cjk_ratio > 0.1 and target not in _CJK_CAPABLE_PROFILES:
                cjk_target = _prefer_cjk_profile(current_profile, task)
                if cjk_target and cjk_target not in tried:
                    target = cjk_target
            print(f"MCP: quality escalation — {uncertain_count} uncertain_points, upgrading {current_profile} → {target}", file=sys.stderr)
            return target
        return None

    return None


# Per-request streaming context — set by handle_tools_call, consumed by _wrap_worker_call
_stream_ctx = threading.local()


def _get_effective_project_root() -> Path:
    """Return the effective project root.

    When LOCAL_LLM_TARGET_PROJECT is set (global MCP launcher mode),
    use it as the project root so that path resolution, output dir, and
    subprocess cwd all target the caller's project rather than the pipeline
    source repo itself.
    """
    target = os.environ.get("LOCAL_LLM_TARGET_PROJECT")
    if target:
        tp = Path(target).resolve()
        if tp.exists():
            return tp
    return PROJECT_ROOT


def _get_source_repo_root() -> Path:
    """Return the pipeline source repo root for reading VERSION, prompts, etc.

    When LOCAL_LLM_SOURCE_REPO is set (global MCP launcher mode), use it to
    locate pipeline-owned assets (VERSION, prompts, registry).  Never returns
    the target project root — version provenance is always from the pipeline.
    """
    source = os.environ.get("LOCAL_LLM_SOURCE_REPO")
    if source:
        sp = Path(source).resolve()
        if sp.exists():
            return sp
    return PROJECT_ROOT


def _read_version() -> str:
    """Read the pipeline version from the source repo, never the target project.

    Priority:
    1. LOCAL_LLM_SOURCE_REPO / VERSION (global MCP launcher mode)
    2. PROJECT_ROOT / VERSION (running directly from pipeline source repo)
    """
    vf = _get_source_repo_root() / "VERSION"
    if vf.exists():
        return vf.read_text(encoding="utf-8").strip()
    return "unknown"

SERVER_NAME = "local-llm-pipeline"
SERVER_VERSION = _read_version()

MAX_DIFF_CHARS = 100_000
MAX_PATH_MAX_CHARS = 200_000
MAX_MAX_FILES = 50
DEFAULT_TIMEOUT = 600
DEBATE_TIMEOUT = 900
DEBATE_FAST_PER_ROUND_TIMEOUT = 350

TOOLS = {
    "local_check": {
        "description": "Run local LLM environment health check. Returns Ollama connectivity, model availability, and profile recommendations. Fast (~5s), no LLM call. Use before other local tools to verify the environment is ready.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "local_summarize_file": {
        "description": "Summarize a single file using a local LLM. Returns purpose, key functions, dependencies, and potential issues. Typical time: 20-60s. Use for understanding unfamiliar source files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to summarize (must exist, must not be blocked).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override (e.g. fast_summary, code_worker).",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max input characters (default: profile default or 60000, max: 200000).",
                },
            },
            "required": ["path"],
        },
    },
    "local_summarize_tree": {
        "description": "Summarize a directory tree using a local LLM. Returns directory purpose, main modules, and suggested reading order. Typical time: 30-90s.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to summarize (must exist, must not be blocked).",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Max files to read (default: 20, max: 50).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max input characters (default: profile default or 60000, max: 200000).",
                },
            },
            "required": ["path"],
        },
    },
    "local_generate_test_plan": {
        "description": "Generate a test plan for a source file using a local LLM. Returns test categories, edge cases, and coverage suggestions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the source file (must exist, must not be blocked).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
            },
            "required": ["path"],
        },
    },
    "local_review_diff": {
        "description": (
            "Review a git diff using a local LLM (single model). Returns problems, test gaps, "
            "compatibility risks, and security concerns. "
            "Set commit_gate=true for fast pre-commit review (skips auto-debate escalation, "
            "uses 60s timeout). For deep multi-model review call local_debate_review_diff directly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff_text": {
                    "type": "string",
                    "description": "The diff text to review (max 100000 chars).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
                "commit_gate": {
                    "type": "boolean",
                    "description": (
                        "Set to true for fast pre-commit review. Skips automatic debate escalation "
                        "and uses the 60s timeout single-model path. For deep review, "
                        "call local_debate_review_diff explicitly."
                    ),
                },
            },
            "required": ["diff_text"],
        },
    },
    "local_debate_review_diff": {
        "description": "Cross-review a git diff using multiple local models in debate mode. Defaults to fast mode (2 rounds) with summary-only output. Full 3-round debate available for large/risky diffs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff_text": {
                    "type": "string",
                    "description": "The diff text to review (max 100000 chars).",
                },
                "fast": {
                    "type": "boolean",
                    "description": "Use fast mode (2 rounds instead of 3). Ignored if profiles is set. Default: true.",
                },
                "summary_only": {
                    "type": "boolean",
                    "description": "Return only findings summary, no per-round details. Default: true.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max input characters (default: profile default or 60000, max: 200000).",
                },
                "profiles": {
                    "type": "string",
                    "description": "Comma-separated profile names overriding default rounds (e.g. 'qwen3.6_27b_mtp,reasoning_checker,qwen3.6_35b_moe_mtp'). Overrides --fast.",
                },
                "rounds": {
                    "type": "integer",
                    "description": "Number of debate rounds (1-3, default: 3, or 2 with --fast).",
                },
            },
            "required": ["diff_text"],
        },
    },
    "local_parallel_review": {
        "description": "Run multiple local models in parallel for independent cross-verification of a git diff. Uses 2-3 models from different families (Qwen/Nemotron/Mistral) simultaneously, synthesizes findings. Best for release reviews, architecture changes, and high-stakes diffs. Parallel execution is ~150s vs ~500s sequential debate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff_text": {
                    "type": "string",
                    "description": "The diff text to review (max 100000 chars).",
                },
            },
            "required": ["diff_text"],
        },
    },
    "local_contextual_analyze": {
        "description": "Analyze a file with a specific question or focus area using a local LLM. Unlike summarize-file (broad overview), this tool does targeted analysis: 'does this code handle errors correctly?', 'what are the thread-safety issues here?', 'how does this module couple to others?'. Accepts previous analysis result as optional context for progressive deepening.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to analyze (must exist, must not be blocked).",
                },
                "question": {
                    "type": "string",
                    "description": "The specific question or focus area for analysis.",
                },
                "previous_result": {
                    "type": "string",
                    "description": "Optional JSON string from a prior MCP call result, used as context for progressive analysis.",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override (e.g. reasoning_checker for risk analysis).",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max input characters (default: profile default or 60000, max: 200000).",
                },
            },
            "required": ["path", "question"],
        },
    },
    "local_draft_code": {
        "description": "Draft code (fix, feature, refactor) or suggest improvements using a local LLM. Output goes to .local_llm_out/ only — NEVER modifies source files. Controller must review, decide, and apply manually.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Draft task: draft-fix, draft-feature, draft-refactor, or suggest-improvements.",
                    "enum": ["draft-fix", "draft-feature", "draft-refactor", "suggest-improvements"],
                },
                "prompt": {
                    "type": "string",
                    "description": "Description of the issue, feature, refactoring goal, or code to improve.",
                },
                "context_file": {
                    "type": "string",
                    "description": "Optional path to a file to include as context.",
                },
                "profile": {"type": "string", "description": "Optional profile override."},
                "model": {"type": "string", "description": "Optional model override."},
            },
            "required": ["task"],
        },
    },
}


def read_json_request() -> dict | None:
    """Read a single JSON-RPC request from stdin."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    except EOFError:
        return None


def write_progress_notification(progress_token: str, progress: float, total: float | None = None,
                                message: str | None = None):
    """Send a $/progress notification to the MCP client. Never raises."""
    notification = {
        "jsonrpc": "2.0",
        "method": "$/progress",
        "params": {
            "progressToken": progress_token,
            "progress": progress,
        },
    }
    if total is not None:
        notification["params"]["total"] = total
    if message:
        notification["params"]["message"] = message
    try:
        line = json.dumps(notification, ensure_ascii=False, default=str)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def write_json_response(response: dict):
    """Write a JSON-RPC response to stdout. Failure is logged but never raised
    — a broken stdout pipe must not propagate up and tear the server down,
    because the MCP host may simply have disconnected and we want the next
    request (or a clean shutdown) to be handled gracefully."""
    try:
        line = json.dumps(response, ensure_ascii=False, default=str)
    except Exception as exc:
        line = json.dumps({
            "jsonrpc": "2.0",
            "id": response.get("id"),
            "error": {"code": -32603, "message": f"serialization failed: {exc}"},
        })
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, OSError) as exc:
        print(f"WARN: write_json_response failed: {exc}", file=sys.stderr)


def handle_initialize(msg_id: int | str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
            },
        },
    }


def handle_tools_list(msg_id: int | str) -> dict:
    tool_list = []
    for name, schema in TOOLS.items():
        tool_list.append({
            "name": name,
            "description": schema["description"],
            "inputSchema": schema["inputSchema"],
        })
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"tools": tool_list},
    }


def _is_path_inside_project(resolved: Path) -> bool:
    """Return True if *resolved* is inside the effective project root."""
    effective_root = _get_effective_project_root().resolve()
    try:
        resolved.relative_to(effective_root)
        return True
    except ValueError:
        return False


def validate_path(path_str: str) -> tuple[bool, str]:
    """Validate a file/directory path. Returns (ok, error_message).

    Always resolves to absolute path to prevent symlink and '..' bypasses.
    Blocked paths are rejected regardless of existence.
    Paths outside the project root are rejected unless
    LOCAL_LLM_ALLOW_OUTSIDE_PROJECT=1.
    """
    path = Path(path_str)
    resolved = path.resolve()
    if is_blocked_path(path) or is_blocked_path(resolved):
        return False, f"Path is blocked (secrets/system dirs): {path_str}"

    # Project boundary check (v0.9.4)
    allow_outside = os.environ.get("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", "") == "1"
    if not allow_outside and not _is_path_inside_project(resolved):
        return False, (
            f"Path is outside the current project: {path_str}. "
            f"Use a path inside the current git project, "
            f"or set LOCAL_LLM_ALLOW_OUTSIDE_PROJECT=1."
        )

    if not path.exists():
        return False, f"Path not found: {path_str}"
    return True, ""


def build_router_cmd(task: str, path: str | None, max_files: int | None,
                     max_chars: int | None, profile: str | None, model: str | None) -> list[str]:
    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"), task]
    if path:
        cmd.append(path)
    if max_files is not None:
        cmd.extend(["--max-files", str(max_files)])
    if max_chars is not None:
        cmd.extend(["--max-chars", str(max_chars)])
    if profile:
        cmd.extend(["--profile", profile])
    if model:
        cmd.extend(["--model", model])
    return cmd


# MCP Cost Discipline P2-C1.1: build the env dict that stamps per-call
# cost-discipline context onto a worker subprocess via the
# LOCAL_LLM_LEDGER_EXTRA channel introduced in P2-C1.0. The worker reads
# this env var, intersects with call_ledger.KNOWN_EXTRA_KEYS, and folds
# the result into the call ledger record's `extra` field.
#
# Call sites pass the returned dict as `extra_env=` to run_subprocess /
# run_subprocess_streaming / _wrap_worker_call. P2-C1.2 (auto hook) will
# call this helper with `source="auto-hook"`. P2-C1.1 itself only sets it
# from MCP tool handlers, which default to "manual-mcp".
def _build_ledger_extra_env(
    *,
    mcp_tool_name: str,
    commit_gate: bool | None = None,
    source: str = "manual-mcp",
) -> dict[str, str]:
    payload: dict[str, object] = {
        "mcp_tool_name": mcp_tool_name,
        "source": source,
    }
    if commit_gate is not None:
        payload["commit_gate"] = bool(commit_gate)
    return {
        "LOCAL_LLM_LEDGER_EXTRA": json.dumps(
            payload, separators=(",", ":"), sort_keys=True,
        ),
    }


# MCP Cost Discipline P2-C2.1: derive the escalation trigger from the
# worker payload's quality signals that drove _check_quality_escalation
# to escalate.  The three triggers mirror the branches in that function:
#   timeout        → error_type == "timeout"
#   low_confidence → confidence == "low"
#   uncertain_points → len(uncertain_points) > 3
#
# MCP Cost Discipline P3-C1: the low_confidence branch is gated behind
# LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE so the returned trigger label
# matches the branch in _check_quality_escalation that actually fired.
# When the knob is OFF and a payload has both `confidence=="low"` and
# `uncertain_points > 3`, escalation fires via the uncertain_points
# branch and this helper now correctly reports "uncertain_points"
# instead of the stale "low_confidence" label.
def _derive_escalation_trigger(payload: dict) -> str:
    error_type = (payload.get("error_type") or "").lower()
    if error_type == "timeout":
        return "timeout"
    confidence = (payload.get("confidence") or "medium").lower()
    if confidence == "low" and _parse_env_flag(
            _ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, default=False):
        return "low_confidence"
    uncertain_count = len(payload.get("uncertain_points") or [])
    if uncertain_count > 3:
        return "uncertain_points"
    return "unknown"


# MCP Cost Discipline P2-C2.1: build the env dict for an escalated
# child worker call.  Inherits parent extra_env fields (mcp_tool_name,
# source, commit_gate) and adds escalation context so the child's ledger
# record links back to the parent request.
def _merge_escalation_ledger_extra_env(
    extra_env: dict[str, str] | None,
    *,
    auto_escalated: bool,
    escalation_trigger: str,
    escalation_reason: str,
    escalation_from_profile: str,
    escalation_to_profile: str,
    escalation_depth: int,
    parent_request_id: str,
) -> dict[str, str]:
    parent_payload: dict[str, object] = {}
    if extra_env:
        raw = extra_env.get("LOCAL_LLM_LEDGER_EXTRA", "")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    parent_payload = parsed
            except (json.JSONDecodeError, TypeError):
                pass
    child_payload: dict[str, object] = dict(parent_payload)
    child_payload.update({
        "auto_escalated": auto_escalated,
        "escalation_trigger": escalation_trigger,
        "escalation_reason": escalation_reason,
        "escalation_from_profile": escalation_from_profile,
        "escalation_to_profile": escalation_to_profile,
        "escalation_depth": escalation_depth,
        "parent_request_id": parent_request_id,
    })
    return {
        "LOCAL_LLM_LEDGER_EXTRA": json.dumps(
            child_payload, separators=(",", ":"), sort_keys=True,
        ),
    }


def run_subprocess(cmd: list[str], stdin_data: str | None = None,
                   timeout: int = DEFAULT_TIMEOUT,
                   extra_env: dict[str, str] | None = None) -> dict:
    """Run a subprocess and return a structured result.

    Forces UTF-8 decoding with `errors="replace"` so non-ASCII output (e.g.
    Chinese in worker stderr / em-dashes in summaries) cannot trip a GBK
    locale UnicodeDecodeError on Windows. Also force the child's
    PYTHONIOENCODING to utf-8 so the worker writes UTF-8 to its own stdout.

    Uses the effective project root (LOCAL_LLM_TARGET_PROJECT when set) as
    cwd so output lands in the correct project's .local_llm_out/.

    ``extra_env`` (P2-C1.1) is merged into the child env after the defaults
    are seeded; values in ``extra_env`` overwrite any inherited value so a
    per-call MCP-tool stamp wins over a stale external env.
    """
    start = time.time()
    effective_root = _get_effective_project_root()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Direct worker output to the effective project's .local_llm_out/
    env.setdefault("LOCAL_LLM_OUTPUT_DIR", str(effective_root / ".local_llm_out"))
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(effective_root),
            env=env,
        )
        elapsed = round(time.time() - start, 2)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        return {
            "ok": result.returncode == 0,
            "stdout": stdout[:50000],
            "stderr": stderr[:10000],
            "returncode": result.returncode,
            "elapsed_seconds": elapsed,
        }
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 2)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Subprocess timed out after {timeout}s",
            "returncode": -1,
            "elapsed_seconds": elapsed,
        }
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Subprocess error: {e}",
            "returncode": -1,
            "elapsed_seconds": elapsed,
        }


def run_subprocess_streaming(cmd: list[str], progress_token: str,
                              stdin_data: str | None = None,
                              timeout: int = DEFAULT_TIMEOUT,
                              extra_env: dict[str, str] | None = None) -> dict:
    """Run a subprocess with real-time progress via MCP $/progress notifications.

    Reads stdout line-by-line. Lines prefixed ``DATA:`` are treated as
    streaming content tokens and forwarded as progress notifications.
    Lines prefixed ``JSON:`` are the final output marker (same as batch mode).

    ``extra_env`` (P2-C1.1) is merged into the child env after the defaults
    are seeded; values in ``extra_env`` overwrite any inherited value.
    """
    start = time.time()
    effective_root = _get_effective_project_root()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("LOCAL_LLM_OUTPUT_DIR", str(effective_root / ".local_llm_out"))
    if extra_env:
        env.update(extra_env)

    accumulated = []
    token_count = 0

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_data else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(effective_root),
            env=env,
        )

        stderr_chunks: list[str] = []

        def _drain_stderr():
            for chunk in proc.stderr:
                stderr_chunks.append(chunk)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        json_path = None

        try:
            if stdin_data:
                proc.stdin.write(stdin_data)
                proc.stdin.close()

            for line in proc.stdout:
                line = line.rstrip("\n").rstrip("\r")
                if line.startswith("DATA:"):
                    token = line[5:].strip()
                    if token:
                        accumulated.append(token)
                        token_count += 1
                        if token_count % 10 == 0:
                            write_progress_notification(
                                progress_token, token_count,
                                message="".join(accumulated[-200:]),
                            )
                elif line.startswith("JSON:"):
                    json_path = line.split(":", 1)[1].strip()

            proc.wait(timeout=timeout)
            elapsed = round(time.time() - start, 2)

            stderr_thread.join(timeout=5)
            stderr_data = "".join(stderr_chunks)[:10000]

        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            elapsed = round(time.time() - start, 2)
            return {
                "ok": False,
                "stdout": json_path or "",
                "stderr": f"Subprocess timed out after {timeout}s",
                "returncode": -1,
                "elapsed_seconds": elapsed,
            }

        # Send final progress with full accumulated text
        if accumulated:
            write_progress_notification(
                progress_token, token_count, total=token_count,
                message="".join(accumulated),
            )

        # If we have a JSON path, read the output file
        if json_path:
            output, _ = load_worker_output(json_path)
            if output:
                return {
                    "ok": proc.returncode == 0,
                    "stdout": json.dumps(output, ensure_ascii=False, default=str),
                    "stderr": (stderr_data or "")[:10000],
                    "returncode": proc.returncode,
                    "elapsed_seconds": elapsed,
                    "streamed": True,
                    "streamed_tokens": token_count,
                }

        return {
            "ok": proc.returncode == 0,
            "stdout": json_path or "",
            "stderr": (stderr_data or "")[:10000],
            "returncode": proc.returncode,
            "elapsed_seconds": elapsed,
            "streamed": True,
            "streamed_tokens": token_count,
        }

    except Exception as exc:
        elapsed = round(time.time() - start, 2)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Subprocess error: {exc}",
            "returncode": -1,
            "elapsed_seconds": elapsed,
        }


_JSON_MARKER_RE = re.compile(r"^JSON:\s*(.+)$", re.MULTILINE)


def _make_request_id() -> str:
    return f"req_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def parse_worker_json_path(stdout: str) -> Path | None:
    """Find the `JSON: <path>` marker the worker prints on every exit path.

    Returning the worker's own output file (instead of "the most recent JSON
    file in .local_llm_out") prevents the v0.9.2 stale-fallback bug where a
    crashed summarize-tree silently returned a previous summarize-file result.
    """
    if not stdout:
        return None
    matches = _JSON_MARKER_RE.findall(stdout)
    if not matches:
        return None
    candidate = Path(matches[-1].strip())
    if candidate.exists():
        return candidate
    return None


def load_worker_output(stdout: str) -> tuple[dict | None, str | None]:
    """Locate and load the JSON output file produced by THIS worker run.

    Returns (data, error). On any failure the second element describes why,
    so the caller can surface a structured error rather than fall back to a
    stale result.
    """
    path = parse_worker_json_path(stdout)
    if path is None:
        return None, "worker did not emit a JSON: marker — output file unknown"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"worker output unreadable at {path}: {exc}"


def find_latest_json_output() -> dict | None:
    """Backward-compatible scanner. Kept for callers that legitimately want
    the most recent file (e.g. local_check, which does not emit a JSON marker).
    Tool wrappers that consume worker output MUST use load_worker_output().
    """
    out_dir = _get_effective_project_root() / ".local_llm_out"
    if not out_dir.exists():
        return None
    json_files = sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for jf in json_files:
        try:
            return json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return None


def build_error_response(tool: str, error_type: str, error: str,
                         suggestion: str = "", elapsed: float = 0.0,
                         request_id: str | None = None,
                         profile: str | None = None,
                         model: str | None = None,
                         task: str | None = None) -> dict:
    """Uniform structured error envelope for every tool wrapper."""
    return {
        "tool": tool,
        "task": task or tool.replace("local_", ""),
        "ok": False,
        "result": None,
        "error": error[:500] if error else error_type,
        "error_type": error_type,
        "suggestion": suggestion,
        "request_id": request_id or _make_request_id(),
        "profile": profile,
        "model": model,
        "elapsed_seconds": round(elapsed, 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_success_response(tool: str, payload: dict, elapsed: float,
                           request_id: str | None = None) -> dict:
    """Wrap a worker result dict for return through MCP. Surfaces prompt
    metadata at the top level so log entries can pick it up uniformly.
    """
    return {
        "tool": tool,
        "task": payload.get("task") or tool.replace("local_", ""),
        "ok": True,
        "result": truncate_output(payload),
        "error": None,
        "error_type": None,
        "suggestion": None,
        "request_id": request_id or _make_request_id(),
        "profile": payload.get("profile"),
        "model": payload.get("model"),
        "prompt_id": payload.get("prompt_id"),
        "prompt_version": payload.get("prompt_version"),
        "prompt_hash": payload.get("prompt_hash"),
        "cache_hit": payload.get("cache_hit", False),
        "elapsed_seconds": round(elapsed, 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def coerce_failure_response(tool: str, payload: dict | None,
                            stderr: str, elapsed: float,
                            request_id: str | None = None) -> dict:
    """Build a failure response from a worker JSON payload (preferred) or,
    when payload is missing, from subprocess stderr.
    """
    if payload:
        return {
            "tool": tool,
            "task": payload.get("task") or tool.replace("local_", ""),
            "ok": False,
            "result": truncate_output(payload),
            "error": payload.get("error") or stderr[:300] or "worker failed",
            "error_type": payload.get("error_type") or "worker_failed",
            "suggestion": payload.get("suggestion") or "see worker stderr",
            "request_id": request_id or _make_request_id(),
            "profile": payload.get("profile"),
            "model": payload.get("model"),
            "prompt_id": payload.get("prompt_id"),
            "prompt_version": payload.get("prompt_version"),
            "prompt_hash": payload.get("prompt_hash"),
            "elapsed_seconds": round(elapsed, 2),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    return build_error_response(
        tool=tool,
        error_type="worker_failed_no_output",
        error=(stderr or "worker exited without output").strip()[:500],
        suggestion="check that the model is reachable and the path is valid",
        elapsed=elapsed,
        request_id=request_id,
    )


# Fields to prioritize in the result dict when compressing — kept in full,
# others may be truncated if the response is large.
_PRIORITY_RESULT_FIELDS = {
    "summary", "high_confidence_findings", "error", "error_type", "ok",
}


def _strip_nulls(obj):
    """Recursively remove None values and empty lists/dicts to save space."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items()
                if v is not None and v != [] and v != {}}
    if isinstance(obj, list):
        return [_strip_nulls(v) for v in obj
                if v is not None and v != [] and v != {}]
    return obj


def truncate_output(data: dict, max_chars: int = 50_000) -> dict:
    """Truncate large outputs to keep MCP responses agent-consumable.

    When the serialized JSON exceeds max_chars, strips nulls/empties first,
    then truncates verbose string fields and long lists.
    """
    raw = json.dumps(data, ensure_ascii=False)
    if len(raw) <= max_chars:
        return data

    # First pass: strip nulls and empties (often saves 20-40%)
    stripped = _strip_nulls(data)
    raw = json.dumps(stripped, ensure_ascii=False)
    if len(raw) <= max_chars:
        return stripped

    # Second pass: truncate verbose fields in result
    result = stripped.get("result", {})
    if isinstance(result, dict):
        for k, v in list(result.items()):
            if k in _PRIORITY_RESULT_FIELDS:
                continue
            if isinstance(v, str) and len(v) > 2000:
                result[k] = v[:2000] + "... [truncated]"
            elif isinstance(v, list) and len(v) > 20:
                result[k] = v[:20] + ["... [truncated]"]
        stripped["result"] = result

    # Third pass: if still too large, truncate all non-priority fields heavily
    raw = json.dumps(stripped, ensure_ascii=False)
    if len(raw) > max_chars:
        for k in list(stripped.keys()):
            if k in ("tool", "task", "ok", "error", "error_type", "request_id",
                     "elapsed_seconds", "profile", "model"):
                continue
            if isinstance(stripped[k], dict):
                stripped[k] = _strip_nulls(stripped[k])
                # Keep only priority sub-fields
                for sk in list(stripped[k].keys()):
                    if sk not in _PRIORITY_RESULT_FIELDS:
                        sv = stripped[k][sk]
                        if isinstance(sv, str) and len(sv) > 500:
                            stripped[k][sk] = sv[:500] + "... [truncated]"
            elif isinstance(stripped[k], str) and len(stripped[k]) > 500:
                stripped[k] = stripped[k][:500] + "... [truncated]"

    stripped["_compressed"] = True
    return stripped


def _wrap_worker_call(tool: str, cmd: list[str], stdin_data: str | None = None,
                      timeout: int = DEFAULT_TIMEOUT, task: str | None = None,
                      auto_escalate: bool = True, _depth: int = 0,
                      cjk_ratio: float = 0.0,
                      _tried_profiles: set[str] | None = None,
                      extra_env: dict[str, str] | None = None) -> dict:
    """Run the worker subprocess and translate its output into a uniform MCP
    response. Always loads the JSON file the worker pointed to via its
    `JSON: <path>` marker — never falls back to "latest file in
    .local_llm_out/", which would risk returning a stale, unrelated result.

    When streaming context is active (progress_token + stream=True),
    adds ``--stream`` to the worker command and uses real-time subprocess
    output to send MCP $/progress notifications.
    """
    request_id = _make_request_id()
    stream = getattr(_stream_ctx, "stream", False)
    progress_token = getattr(_stream_ctx, "progress_token", None)

    if stream and progress_token:
        if "--stream" not in cmd:
            cmd = cmd + ["--stream"]
        result = run_subprocess_streaming(
            cmd, progress_token, stdin_data=stdin_data, timeout=timeout,
            extra_env=extra_env,
        )
        payload, _ = load_worker_output(result["stdout"])
        if result["ok"] and payload:
            return build_success_response(tool, payload, result["elapsed_seconds"], request_id)
        if result["ok"]:
            return build_error_response(
                tool=tool,
                error_type="missing_worker_output",
                error="worker exited 0 but produced no output file",
                suggestion="check worker stderr for warnings",
                elapsed=result["elapsed_seconds"],
                request_id=request_id,
            )
        return coerce_failure_response(tool, payload, result.get("stderr", ""),
                                       result["elapsed_seconds"], request_id)

    result = run_subprocess(cmd, stdin_data=stdin_data, timeout=timeout,
                            extra_env=extra_env)
    payload, parse_err = load_worker_output(result["stdout"])

    # Phase 3B: auto-update model health (best-effort, never blocks)
    if payload:
        elapsed = result.get("elapsed_seconds", 0)
        _update_model_health(
            payload.get("profile", ""), result["ok"], elapsed,
            error_type=(payload.get("error_type") or "").lower(),
        )

    if result["ok"]:
        if payload is None:
            return build_error_response(
                tool=tool,
                error_type="missing_worker_output",
                error=parse_err or "worker exited 0 but produced no output file",
                suggestion="check worker stderr for warnings",
                elapsed=result["elapsed_seconds"],
                request_id=request_id,
            )

        # Layer 4 quality-based auto-escalation (v0.9.6)
        # Phase 3.0: multi-hop escalation with loop prevention
        if _tried_profiles is None:
            _tried_profiles = set()
        if auto_escalate and task and _depth < _MAX_ESCALATION_DEPTH:
            current_profile = payload.get("profile", "")
            _tried_profiles.add(current_profile)
            escalated = _check_quality_escalation(
                payload, current_profile, task,
                cjk_ratio=cjk_ratio, _tried_profiles=_tried_profiles,
            )
            if escalated:
                # Build a new command with the escalated profile
                escalated_cmd = list(cmd)
                profile_found = False
                for i, arg in enumerate(escalated_cmd):
                    if arg == "--profile" and i + 1 < len(escalated_cmd):
                        escalated_cmd[i + 1] = escalated
                        profile_found = True
                        break
                if not profile_found:
                    escalated_cmd.extend(["--profile", escalated])
                _tried_profiles.add(escalated)
                print(f"MCP: re-running {task} with escalated profile: {escalated} "
                      f"(depth={_depth + 1}, tried={sorted(_tried_profiles)})", file=sys.stderr)

                # Pass previous (poor-quality) output as context for comparison
                escalated_stdin = stdin_data
                prev_summary = payload.get("summary", "")
                prev_uncertain = payload.get("uncertain_points", [])
                prev_confidence = payload.get("confidence", "?")
                if prev_summary or prev_uncertain:
                    context = ("## Previous attempt (lower-quality — re-analyze more thoroughly):\n"
                               f"Summary: {str(prev_summary)[:500]}\n"
                               f"Uncertain: {str(prev_uncertain)[:500]}\n\n")
                    if escalated_stdin:
                        escalated_stdin = context + escalated_stdin
                    else:
                        escalated_stdin = context

                # Log quality delta for future routing optimization
                try:
                    delta_log = SCRIPT_DIR / ".local_llm_out" / "quality_delta.jsonl"
                    delta_log.parent.mkdir(parents=True, exist_ok=True)
                    with open(delta_log, "a", encoding="utf-8") as df:
                        json.dump({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "task": task,
                            "from_profile": current_profile,
                            "to_profile": escalated,
                            "from_confidence": prev_confidence,
                            "from_uncertain_count": len(prev_uncertain) if isinstance(prev_uncertain, list) else 0,
                            "reason": ("low_confidence" if prev_confidence == "low"
                                       else "uncertain_points" if len(prev_uncertain) > 3
                                       else "timeout"),
                        }, df, ensure_ascii=False)
                        df.write("\n")
                except Exception:
                    pass

                # P2-C2.1: stamp escalated child call with escalation context
                # in LOCAL_LLM_LEDGER_EXTRA while preserving parent identity
                # fields (mcp_tool_name, source, commit_gate).
                trigger = _derive_escalation_trigger(payload)
                uncertain_n = len(prev_uncertain) if isinstance(prev_uncertain, list) else 0
                reason = (
                    f"confidence=low on {current_profile}" if trigger == "low_confidence"
                    else f"{uncertain_n} uncertain_points on {current_profile}" if trigger == "uncertain_points"
                    else f"timeout on {current_profile}" if trigger == "timeout"
                    else f"unknown on {current_profile}"
                )
                child_extra_env = _merge_escalation_ledger_extra_env(
                    extra_env,
                    auto_escalated=True,
                    escalation_trigger=trigger,
                    escalation_reason=reason,
                    escalation_from_profile=current_profile,
                    escalation_to_profile=escalated,
                    escalation_depth=_depth + 1,
                    parent_request_id=request_id,
                )
                return _wrap_worker_call(
                    tool, escalated_cmd, stdin_data=escalated_stdin,
                    timeout=timeout, task=task, auto_escalate=auto_escalate,
                    _depth=_depth + 1, cjk_ratio=cjk_ratio,
                    _tried_profiles=_tried_profiles,
                    extra_env=child_extra_env,
                )

        return build_success_response(tool, payload, result["elapsed_seconds"], request_id)

    return coerce_failure_response(tool, payload, result["stderr"], result["elapsed_seconds"], request_id)


def call_parallel_review(params: dict) -> dict:
    """Run multiple models in parallel for independent cross-verification.

    Used for release-risk-review and high-stakes architecture review.
    Runs 2-3 models simultaneously via Popen, collects results, and
    synthesizes findings. Non-blocking path alongside sequential debate.
    """
    request_id = _make_request_id()
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return build_error_response(
            tool="local_parallel_review", error_type="empty_input",
            error="diff_text is empty", request_id=request_id,
        )

    # Select 2-3 models from different families AND different backends
    profiles = []
    try:
        profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
        pd = json.loads(profiles_path.read_text(encoding="utf-8"))
        # llama.cpp: always try to include the fast GPU backend
        if _profile_is_healthy("gemma4_26b_llamacpp"):
            profiles.append("gemma4_26b_llamacpp")
        # Ollama families: Qwen, Nemotron, Mistral/GPT — remaining slots
        families = {
            "qwen": ["qwen3.6_35b_moe_mtp", "deep_reviewer", "qwen3.6_27b_mtp"],
            "nemotron": ["nemotron_super", "reasoning_checker", "diff_reviewer"],
            "mistral_gpt": ["release_auditor", "heavy_reviewer"],
        }
        for family, candidates in families.items():
            if len(profiles) >= 3:
                break
            for c in candidates:
                if c not in profiles and _profile_is_healthy(c):
                    profiles.append(c)
                    break
    except Exception:
        profiles = ["deep_reviewer", "reasoning_checker"]

    if len(profiles) < 2:
        return call_review_diff(params)  # Fall back to single review

    print(f"MCP: parallel review — {len(profiles)} models: {profiles}", file=sys.stderr)

    # Spawn all models in parallel
    processes = {}
    started = time.time()
    for p in profiles:
        pw_cfg = pd.get("profiles", {}).get(p, {})
        model = pw_cfg.get("model", "")
        cmd = [
            sys.executable, str(SCRIPT_DIR / "local_llm_router.py"),
            "review-diff", "--stdin", "--profile", p,
        ]
        if model:
            cmd.extend(["--model", model])
        try:
            stdin_path = SCRIPT_DIR / ".local_llm_out" / f"parallel_{request_id}_{p}.stdin"
            stdin_path.parent.mkdir(parents=True, exist_ok=True)
            stdin_path.write_text(diff_text, encoding="utf-8")
            # P2-C1.1: stamp the worker subprocess with the real MCP tool
            # name so each parallel worker emits a ledger record tagged as
            # local_parallel_review (not just review-diff).
            child_env = os.environ.copy()
            child_env.setdefault("PYTHONIOENCODING", "utf-8")
            child_env.update(_build_ledger_extra_env(
                mcp_tool_name="local_parallel_review"))
            with open(stdin_path, "r", encoding="utf-8") as f:
                proc = subprocess.Popen(
                    cmd, stdin=f,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    env=child_env,
                )
            processes[p] = proc
        except Exception as e:
            print(f"MCP: parallel review — failed to spawn {p}: {e}", file=sys.stderr)

    # Collect results (wait up to 300s per model)
    results = {}
    for p, proc in processes.items():
        try:
            stdout, stderr = proc.communicate(timeout=300)
            payload, _ = load_worker_output(stdout)
            results[p] = {
                "ok": proc.returncode == 0,
                "payload": payload,
                "stderr": stderr[:500],
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            results[p] = {"ok": False, "payload": None,
                          "stderr": "timeout after 300s"}

    elapsed = time.time() - started

    # Synthesize: collect findings from all models
    all_findings = []
    all_uncertain = []
    for p, r in results.items():
        if r["payload"]:
            all_findings.extend(
                r["payload"].get("high_confidence_findings", []))
            all_findings.extend(
                r["payload"].get("candidate_findings", []))
            all_uncertain.extend(
                r["payload"].get("uncertain_points", []))

    ok_count = sum(1 for r in results.values() if r["ok"])
    print(f"MCP: parallel review done — {ok_count}/{len(results)} models OK in {elapsed:.0f}s", file=sys.stderr)

    return build_success_response("local_parallel_review", {
        "task": "parallel-review",
        "mode": "parallel",
        "profiles": profiles,
        "models_ok": ok_count,
        "total_models": len(results),
        "high_confidence_findings": all_findings[:10],
        "candidate_findings": all_findings[:20],
        "uncertain_points": all_uncertain[:10],
        "elapsed_seconds": elapsed,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, elapsed, request_id)


def call_local_check(params: dict) -> dict:
    request_id = _make_request_id()
    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_check.py")]
    result = run_subprocess(cmd)
    return {
        "tool": "local_check",
        "task": "check",
        "version": SERVER_VERSION,
        "ok": result["ok"],
        "result": {
            "stdout": result["stdout"][:10000],
            "stderr": result["stderr"][:5000],
        },
        "error": None if result["ok"] else result["stderr"][:500],
        "error_type": None if result["ok"] else "check_failed",
        "suggestion": None if result["ok"] else "review stderr for the failing check",
        "request_id": request_id,
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def call_summarize_file(params: dict) -> dict:
    path_str = params.get("path", "")
    ok, err = validate_path(path_str)
    if not ok:
        return build_error_response(
            tool="local_summarize_file", error_type="blocked_path", error=err,
            suggestion="use a file path that is not in the blocked list",
            profile=params.get("profile"), model=params.get("model"),
        )

    max_chars = params.get("max_chars")
    if max_chars is not None:
        max_chars = min(int(max_chars), MAX_PATH_MAX_CHARS)

    # Proactive routing: sample file, classify complexity, pick starting profile
    user_profile = params.get("profile", "")
    proactive_profile = None
    cjk_ratio = 0.0
    try:
        fpath = Path(path_str).resolve()
        fsize = fpath.stat().st_size
        est_lines = fsize // 60
        sample = fpath.read_text(encoding="utf-8", errors="replace")[:8192]
        info = _classify_input_complexity(sample, is_diff=False)
        info["char_count"] = max(info["char_count"], fsize)
        info["line_count"] = max(info["line_count"], est_lines)
        info["complexity_tier"] = (
            "heavy" if fsize > 80_000 or est_lines > 2_000 else
            "normal" if fsize > 20_000 or info["cjk_ratio"] > 0.1 else
            "light"
        )
        cjk_ratio = info["cjk_ratio"]
        proactive_profile = _resolve_starting_profile(
            "summarize-file", info, user_profile or None)
    except (OSError, UnicodeError):
        pass

    # Output cache: skip re-analysis if file unchanged and cached result < 1h old
    try:
        cache_dir = SCRIPT_DIR / ".local_llm_out" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cfpath = Path(path_str).resolve()
        mtime = cfpath.stat().st_mtime
        cache_key = hashlib.sha256(
            f"{cfpath}:{mtime}:{proactive_profile or 'default'}".encode()
        ).hexdigest()[:16]
        cache_file = cache_dir / f"summarize_{cache_key}.json"
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < 3600:  # 1 hour TTL
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                cached["cache_hit"] = True
                print(f"MCP: cache hit — summarize {path_str} ({age:.0f}s old)", file=sys.stderr)
                return build_success_response("local_summarize_file", cached, 0, _make_request_id())
    except Exception:
        pass

    cmd = build_router_cmd("summarize-file", path_str, None, max_chars,
                           proactive_profile or user_profile, params.get("model"))
    result = _wrap_worker_call("local_summarize_file", cmd, task="summarize-file",
                               cjk_ratio=cjk_ratio,
                               extra_env=_build_ledger_extra_env(
                                   mcp_tool_name="local_summarize_file"))

    # Write to cache on success
    if result.get("ok"):
        try:
            text = result.get("result", {}).get("content", [{}])[0].get("text", "{}")
            content = json.loads(text)
            cache_file.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return result


def call_summarize_tree(params: dict) -> dict:
    path_str = params.get("path", "")
    ok, err = validate_path(path_str)
    if not ok:
        return build_error_response(
            tool="local_summarize_tree", error_type="blocked_path", error=err,
            suggestion="use a directory path that is not in the blocked list",
            profile=params.get("profile"), model=params.get("model"),
        )

    max_files = min(int(params.get("max_files", 20)), MAX_MAX_FILES)
    max_chars = params.get("max_chars")
    if max_chars is not None:
        max_chars = min(int(max_chars), MAX_PATH_MAX_CHARS)

    # Proactive routing: sample directory to detect complexity
    user_profile = params.get("profile", "")
    proactive_profile = None
    cjk_ratio = 0.0
    try:
        dir_path = Path(path_str).resolve()
        entries = sorted(dir_path.iterdir())[:50]
        file_count = sum(1 for e in entries if e.is_file())
        # Sample first few files to detect CJK and code density
        sample = ""
        sampled = 0
        for entry in entries:
            if entry.is_file() and sampled < 3:
                try:
                    sample += entry.read_text(encoding="utf-8", errors="replace")[:4096]
                    sampled += 1
                except OSError:
                    pass
        info = _classify_input_complexity(sample, is_diff=False)
        info["file_count"] = max(info.get("file_count", 0), file_count)
        # Boost tier for large directories
        if file_count > 30:
            info["complexity_tier"] = "heavy"
        elif file_count > 15 and info["complexity_tier"] == "light":
            info["complexity_tier"] = "normal"
        cjk_ratio = info["cjk_ratio"]
        proactive_profile = _resolve_starting_profile(
            "summarize-tree", info, user_profile or None)
    except (OSError, UnicodeError):
        pass

    cmd = build_router_cmd("summarize-tree", path_str, max_files, max_chars,
                           proactive_profile or user_profile, params.get("model"))
    return _wrap_worker_call("local_summarize_tree", cmd, task="summarize-tree",
                             cjk_ratio=cjk_ratio,
                             extra_env=_build_ledger_extra_env(
                                 mcp_tool_name="local_summarize_tree"))


def call_generate_test_plan(params: dict) -> dict:
    path_str = params.get("path", "")
    ok, err = validate_path(path_str)
    if not ok:
        return build_error_response(
            tool="local_generate_test_plan", error_type="blocked_path", error=err,
            suggestion="use a file path that is not in the blocked list",
            profile=params.get("profile"), model=params.get("model"),
        )

    # Proactive routing: read the file to count definitions and estimate complexity
    user_profile = params.get("profile", "")
    proactive_profile = None
    cjk_ratio = 0.0
    try:
        fpath = Path(path_str).resolve()
        content = fpath.read_text(encoding="utf-8", errors="replace")[:16_384]
        info = _classify_input_complexity(content, is_diff=False)
        cjk_ratio = info["cjk_ratio"]
        # Boost complexity tier based on definition count
        def_count = len(re.findall(
            r'^\s*(?:async\s+)?def\s+\w+|^\s*class\s+\w+',
            content, re.MULTILINE,
        ))
        if def_count > 20:
            info["complexity_tier"] = "heavy"
        elif def_count > 10 and info["complexity_tier"] == "light":
            info["complexity_tier"] = "normal"
        proactive_profile = _resolve_starting_profile(
            "generate-test-plan", info, user_profile or None)
    except (OSError, UnicodeError):
        pass

    cmd = build_router_cmd("generate-test-plan", path_str, None, None,
                           proactive_profile or user_profile, params.get("model"))
    return _wrap_worker_call("local_generate_test_plan", cmd, task="generate-test-plan",
                             cjk_ratio=cjk_ratio,
                             extra_env=_build_ledger_extra_env(
                                 mcp_tool_name="local_generate_test_plan"))


REVIEW_TIMEOUT = 60


def call_review_diff(params: dict) -> dict:
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return build_error_response(
            tool="local_review_diff", error_type="empty_input",
            error="diff_text is empty",
            suggestion="provide a non-empty diff (e.g. `git diff HEAD~1`)",
            profile=params.get("profile"), model=params.get("model"),
        )
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS]

    commit_gate = bool(params.get("commit_gate", False))

    # Auto-escalate to debate for large or multi-file diffs (v0.9.5)
    # commit_gate skips escalation for fast pre-commit review
    if not commit_gate:
        line_count = diff_text.count('\n')
        file_count = len(re.findall(r'^diff --git ', diff_text, re.MULTILINE))
        has_logic = bool(re.search(
            r'^[+-]\s*(def |class |async |await |return |if __|import |from \w+ import)',
            diff_text, re.MULTILINE,
        ))
        is_heavy = line_count > 500 or file_count > 5
        if (line_count > 100 or file_count >= 3
                or (has_logic and file_count >= 2)
                or (is_heavy and has_logic)):
            if is_heavy and has_logic:
                print(f"MCP: heavy diff ({line_count}L, {file_count} files, has_logic) → auto-debate",
                      file=sys.stderr)
            params["_debate_trigger"] = "auto-escalate"
            return call_debate_review_diff(params)

    # Unified complexity-based routing: security → reasoning, CJK → CJK-capable,
    # heavy → deep_reviewer, normal → diff_reviewer, light → commit_reviewer
    cjk_ratio = _detect_cjk_ratio(diff_text)
    route_info = _classify_input_complexity(diff_text, is_diff=True)
    route_info["cjk_ratio"] = cjk_ratio
    resolved = _resolve_starting_profile(
        "review-diff", route_info, params.get("profile") or None, commit_gate)

    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"), "review-diff", "--stdin"]
    cmd.extend(["--profile", resolved])
    if params.get("model"):
        cmd.extend(["--model", params["model"]])

    # Non-commit-gate: route through _wrap_worker_call for quality escalation (v0.9.6)
    if not commit_gate:
        return _wrap_worker_call("local_review_diff", cmd, stdin_data=diff_text,
                                 task="review-diff", cjk_ratio=cjk_ratio,
                                 extra_env=_build_ledger_extra_env(
                                     mcp_tool_name="local_review_diff",
                                     commit_gate=False))

    # Commit gate: pre-invocation constraint check — reject heavy/risky models
    if commit_gate:
        resolved_profile = params.get("profile", "commit_reviewer")
        if resolved_profile != "commit_reviewer":
            try:
                profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
                pd = json.loads(profiles_path.read_text(encoding="utf-8"))
                p = pd.get("profiles", {}).get(resolved_profile, {})
                model_name = p.get("model", "")
                risk = p.get("risk_level", "")
                commit_gate_allowed = p.get("_commit_gate_allowed", False)
                if risk == "high" or not commit_gate_allowed:
                    return build_error_response(
                        tool="local_review_diff",
                        error_type="constraint_violation",
                        error=(
                            f"Profile '{resolved_profile}' ({model_name}) cannot be "
                            f"used in commit gate. Risk={risk}, "
                            f"commit_gate_allowed={commit_gate_allowed}"
                        ),
                        suggestion="Use commit_reviewer profile for commit gate reviews.",
                        profile=resolved_profile, model=model_name,
                    )
            except Exception:
                pass  # Best-effort check

    # Commit gate: fast direct path with 60s timeout
    request_id = _make_request_id()
    result = run_subprocess(
        cmd, stdin_data=diff_text, timeout=REVIEW_TIMEOUT,
        extra_env=_build_ledger_extra_env(
            mcp_tool_name="local_review_diff", commit_gate=True),
    )

    if not result["ok"] and "timed out" in result["stderr"].lower():
        return build_error_response(
            tool="local_review_diff", error_type="timeout",
            error=f"single-model review timed out after {REVIEW_TIMEOUT}s",
            suggestion="try a smaller diff, a lighter profile, or unload the active Ollama model",
            elapsed=result["elapsed_seconds"], request_id=request_id,
            profile=params.get("profile"), model=params.get("model"),
        )

    payload, parse_err = load_worker_output(result["stdout"])

    if result["ok"]:
        if payload is None:
            return build_error_response(
                tool="local_review_diff", error_type="missing_worker_output",
                error=parse_err or "worker exited 0 but produced no output file",
                suggestion="check worker stderr for warnings",
                elapsed=result["elapsed_seconds"], request_id=request_id,
            )
        return build_success_response("local_review_diff", payload,
                                       result["elapsed_seconds"], request_id)

    return coerce_failure_response("local_review_diff", payload,
                                    result["stderr"], result["elapsed_seconds"], request_id)


def call_debate_review_diff(params: dict) -> dict:
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return build_error_response(
            tool="local_debate_review_diff", error_type="empty_input",
            error="diff_text is empty",
            suggestion="provide a non-empty diff",
        )

    if len(diff_text) > MAX_DIFF_CHARS:
        return build_error_response(
            tool="local_debate_review_diff", error_type="diff_too_large",
            error=f"diff_text too large ({len(diff_text)} chars, max {MAX_DIFF_CHARS})",
            suggestion="try smaller diff, --fast, or CLI",
        )
    diff_text = diff_text[:MAX_DIFF_CHARS]

    use_fast = params.get("fast", True)
    use_summary_only = params.get("summary_only", True)
    profiles_override = params.get("profiles")
    rounds_override = params.get("rounds")

    # Auto round-count: analyze diff to decide fast (2) vs full (3) rounds
    # Only applies when the caller hasn't pinned a specific configuration.
    if not profiles_override and not rounds_override and params.get("fast") is None:
        line_count = diff_text.count('\n')
        file_count = len(re.findall(r'^diff --git ', diff_text, re.MULTILINE))
        has_security = _has_security_sensitive_patterns(diff_text)
        if line_count > 300 or file_count > 5 or has_security:
            use_fast = False
            print(f"MCP: debate auto full-mode ({line_count}L, {file_count} files"
                  + (", security" if has_security else "") + ") → 3 rounds",
                  file=sys.stderr)

    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_debate.py"), "review-diff", "--stdin"]
    if profiles_override:
        cmd.extend(["--profiles", profiles_override])
    elif use_fast:
        cmd.append("--fast")
    if rounds_override:
        cmd.extend(["--rounds", str(min(int(rounds_override), 3))])
    if use_fast and not profiles_override:
        cmd.extend(["--timeout", str(DEBATE_FAST_PER_ROUND_TIMEOUT)])
    if use_summary_only:
        cmd.append("--summary-only")
    if params.get("max_chars"):
        cmd.extend(["--max-chars", str(min(int(params["max_chars"]), MAX_PATH_MAX_CHARS))])

    # P2-C3.1: pass debate trigger attribution to the subprocess.
    # Default is manual-mcp; auto-escalation from call_review_diff
    # sets _debate_trigger=auto-escalate in params.
    debate_trigger = params.get("_debate_trigger", "manual-mcp")
    cmd.extend(["--debate-trigger", debate_trigger])

    request_id = _make_request_id()
    result = run_subprocess(cmd, stdin_data=diff_text, timeout=DEBATE_TIMEOUT)

    if not result["ok"] and "timed out" in result["stderr"].lower():
        return build_error_response(
            tool="local_debate_review_diff", error_type="timeout",
            error="subprocess timed out", suggestion="try smaller diff, --fast, or CLI",
            elapsed=result["elapsed_seconds"], request_id=request_id,
        )

    output = None
    if result["ok"]:
        try:
            output = json.loads(result["stdout"])
        except (json.JSONDecodeError, TypeError):
            pass
        if output is None:
            output, _ = load_worker_output(result["stdout"])

    if result["ok"] and output:
        return build_success_response("local_debate_review_diff", output,
                                      result["elapsed_seconds"], request_id)
    if result["ok"]:
        return build_error_response(
            tool="local_debate_review_diff", error_type="missing_worker_output",
            error="debate returned no parsable output",
            suggestion="re-run with --summary-only off to inspect raw output",
            elapsed=result["elapsed_seconds"], request_id=request_id,
        )
    return coerce_failure_response("local_debate_review_diff", output,
                                   result["stderr"], result["elapsed_seconds"], request_id)


def call_contextual_analyze(params: dict) -> dict:
    path_str = params.get("path", "")
    question = params.get("question", "")
    ok, err = validate_path(path_str)
    if not ok:
        return build_error_response(
            tool="local_contextual_analyze", error_type="blocked_path", error=err,
            suggestion="use a file path that is not in the blocked list",
            profile=params.get("profile"), model=params.get("model"),
        )
    if not question.strip():
        return build_error_response(
            tool="local_contextual_analyze", error_type="empty_input",
            error="question is empty",
            suggestion="provide a specific analysis question",
            profile=params.get("profile"), model=params.get("model"),
        )

    max_chars = params.get("max_chars")
    if max_chars is not None:
        max_chars = min(int(max_chars), MAX_PATH_MAX_CHARS)

    # Read file content for analysis
    try:
        file_content = Path(path_str).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return build_error_response(
            tool="local_contextual_analyze", error_type="read_failed",
            error=f"could not read file: {exc}",
            suggestion="check file permissions and encoding",
            profile=params.get("profile"), model=params.get("model"),
        )

    limit = max_chars or 60000
    if len(file_content) > limit:
        file_content = file_content[:limit] + "\n... [truncated]"

    # Build prompt with question as focus and optional prior result as context
    previous = params.get("previous_result", "")
    context_preamble = ""
    if previous.strip():
        context_preamble = (
            "## Previous analysis (use as context, do not repeat):\n"
            f"{previous[:8000]}\n\n"
        )

    stdin_data = (
        f"{context_preamble}"
        f"## File: {path_str}\n"
        f"## Question: {question}\n\n"
        f"## File content:\n```\n{file_content}\n```\n\n"
        f"Please answer the question above based on the file content."
    )

    # Proactive routing: analyze file + question complexity
    user_profile = params.get("profile", "")
    proactive_profile = None
    cjk_ratio = 0.0
    try:
        # Analyze combined content for complexity classification
        analyze_text = question + "\n" + file_content[:16_384]
        info = _classify_input_complexity(analyze_text, is_diff=False)
        cjk_ratio = info["cjk_ratio"]
        # Boost tier for long files or complex questions
        if len(file_content) > 80_000:
            info["complexity_tier"] = "heavy"
        elif len(file_content) > 20_000:
            info["complexity_tier"] = "normal"
        proactive_profile = _resolve_starting_profile(
            "contextual-analyze", info, user_profile or None)
    except Exception:
        pass

    cmd = build_router_cmd("contextual-analyze", path_str, None, max_chars,
                           proactive_profile or user_profile, params.get("model"))
    return _wrap_worker_call("local_contextual_analyze", cmd, stdin_data=stdin_data,
                             task="contextual-analyze", cjk_ratio=cjk_ratio,
                             extra_env=_build_ledger_extra_env(
                                 mcp_tool_name="local_contextual_analyze"))


def call_draft_code(params: dict) -> dict:
    task = params.get("task", "draft-fix")
    prompt = params.get("prompt", "")
    context_file = params.get("context_file", "")

    # Auto-generate prompt for suggest-improvements when only context_file is given
    if not prompt.strip() and task == "suggest-improvements" and context_file:
        prompt = f"Review the code in {context_file} and suggest improvements for quality, safety, and efficiency."

    if not prompt.strip():
        return build_error_response(
            tool="local_draft_code", error_type="empty_input",
            error="prompt is empty",
            suggestion="describe the fix/feature/refactor in the prompt, or provide context_file for suggest-improvements",
            profile=params.get("profile"), model=params.get("model"), task=task,
        )

    user_profile = params.get("profile", "")
    proactive_profile = None

    # Proactive routing: analyze prompt + context file complexity
    if not user_profile:
        try:
            analyze_text = prompt
            if context_file:
                cf_path = Path(context_file)
                if cf_path.is_file():
                    analyze_text += "\n" + cf_path.read_text(
                        encoding="utf-8", errors="replace")[:8192]
            info = _classify_input_complexity(analyze_text, is_diff=False)
            proactive_profile = _resolve_starting_profile(
                task, info, None)
        except Exception:
            pass

    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"), task]

    if context_file:
        ok, err = validate_path(context_file)
        if not ok:
            return build_error_response(
                tool="local_draft_code", error_type="blocked_path", error=err,
                suggestion="use a file path that is not in the blocked list",
                profile=params.get("profile"), model=params.get("model"), task=task,
            )
        cmd.append(context_file)

    resolved = proactive_profile or user_profile
    if resolved:
        cmd.extend(["--profile", resolved])
    if params.get("model"):
        cmd.extend(["--model", params["model"]])

    return _wrap_worker_call("local_draft_code", cmd, stdin_data=prompt, task=task,
                             extra_env=_build_ledger_extra_env(
                                 mcp_tool_name="local_draft_code"))


TOOL_HANDLERS = {
    "local_check": call_local_check,
    "local_summarize_file": call_summarize_file,
    "local_summarize_tree": call_summarize_tree,
    "local_generate_test_plan": call_generate_test_plan,
    "local_contextual_analyze": call_contextual_analyze,
    "local_review_diff": call_review_diff,
    "local_debate_review_diff": call_debate_review_diff,
    "local_parallel_review": call_parallel_review,
    "local_draft_code": call_draft_code,
}


def handle_tools_call(msg_id: int | str, params: dict) -> dict:
    """Dispatch a tool call. ALWAYS returns a JSON-RPC response — never
    raises — so a single tool failure cannot terminate the stdio server.
    """
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {}) or {}

    if tool_name not in TOOL_HANDLERS:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"Unknown tool: {tool_name}",
            },
        }

    # Concurrency guard: prevent multiple LLM calls from competing for GPU
    if not _call_lock.acquire(blocking=False):
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(build_error_response(
                    tool=tool_name,
                    error_type="concurrent_request",
                    error="Another local-llm request is in progress. Only one model call at a time.",
                    suggestion="Wait for the current request to complete and retry.",
                ), ensure_ascii=False)}],
            },
        }

    # Set up streaming context if the client requested it
    _stream_ctx.stream = arguments.get("stream", False)
    _stream_ctx.progress_token = (
        params.get("_meta", {}).get("progressToken")
        or params.get("progressToken")
    )

    handler = TOOL_HANDLERS[tool_name]
    output: dict
    try:
        output = handler(arguments)
        if not isinstance(output, dict):
            output = build_error_response(
                tool=tool_name, error_type="bad_handler_return",
                error=f"handler returned {type(output).__name__}",
                suggestion="report v0.9.3 bug — handler must return dict",
            )
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"WARN: handler {tool_name} raised: {exc}\n{tb}", file=sys.stderr)
        output = build_error_response(
            tool=tool_name, error_type="internal_error",
            error=f"Internal error: {exc}"[:300],
            suggestion="see server stderr for traceback",
        )
    finally:
        _stream_ctx.stream = False
        _stream_ctx.progress_token = None
        _call_lock.release()

    try:
        content = json.dumps(output, ensure_ascii=False, default=str)
    except Exception as exc:
        content = json.dumps(build_error_response(
            tool=tool_name, error_type="serialization_failed",
            error=f"could not serialize tool result: {exc}",
            suggestion="report v0.9.3 bug",
        ))
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"content": [{"type": "text", "text": content}]},
    }


def main():
    # Force stdio to UTF-8 regardless of OS locale (Windows CJK codepages
    # like GBK/CP932 would otherwise corrupt JSON-RPC with CJK characters).
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"local-llm-mcp-server v{SERVER_VERSION}")
        return 0
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python tools/local_llm_mcp_server.py [--version]")
        print("")
        print("MCP (Model Context Protocol) server for local LLM pipeline.")
        print("Communicates via stdio JSON-RPC 2.0.")
        print("")
        print("Tools exposed (source-non-mutating; may write only to .local_llm_out/):")
        for name in sorted(TOOLS):
            print(f"  {name}")
        return 0

    print(f"MCP Server '{SERVER_NAME}' v{SERVER_VERSION} starting on stdio", file=sys.stderr)

    while True:
        try:
            line = sys.stdin.readline()
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as exc:
            print(f"WARN: stdin read failed: {exc}", file=sys.stderr)
            time.sleep(0.05)
            continue
        if not line:
            break  # genuine EOF — host closed stdin
        line = line.strip()
        if not line:
            continue

        # The handler below MUST NOT escape uncaught — every exception path
        # is bounded so that a failure on one request leaves the server live
        # to serve the next. v0.9.2 died because exceptions propagated past
        # the per-request boundary.
        try:
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"WARN: malformed JSON-RPC line dropped: {exc}", file=sys.stderr)
                continue

            msg_id = request.get("id", 0)
            method = request.get("method", "")

            if method == "initialize":
                write_json_response(handle_initialize(msg_id))
            elif method == "tools/list":
                write_json_response(handle_tools_list(msg_id))
            elif method == "tools/call":
                tool_name = request.get("params", {}).get("name", "unknown")
                start = time.time()
                response = handle_tools_call(msg_id, request.get("params", {}))
                elapsed = round(time.time() - start, 2)
                print(f"  [{elapsed}s] {tool_name}", file=sys.stderr)
                # Structured log — prompt metadata is propagated via the
                # response payload so the MCP and CLI log entries carry the
                # same prompt_id / version / hash for traceability.
                try:
                    content = json.loads(response["result"]["content"][0]["text"])
                    from local_llm_logging import write_log_entry
                    write_log_entry({
                        "source": "mcp", "tool": tool_name,
                        "task": content.get("task") or tool_name.replace("local_", ""),
                        "profile": content.get("profile"),
                        "model": content.get("model"),
                        "ok": content.get("ok", False),
                        "duration_sec": elapsed,
                        "error_type": content.get("error_type"),
                        "error": (content.get("error") or "")[:200] if content.get("error") else None,
                        "request_id": content.get("request_id"),
                        "prompt_id": content.get("prompt_id"),
                        "prompt_version": content.get("prompt_version"),
                        "prompt_hash": content.get("prompt_hash"),
                        "cache_hit": content.get("cache_hit", False),
                    })
                except Exception as log_exc:
                    print(f"WARN: log_entry failed: {log_exc}", file=sys.stderr)
                write_json_response(response)
            elif method == "notifications/initialized":
                pass  # ack silently
            elif method.startswith("notifications/"):
                pass  # ignore other notifications silently
            else:
                write_json_response({
                    "jsonrpc": "2.0",
                    "id": request.get("id", 0),
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })
        except KeyboardInterrupt:
            break
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"WARN: per-request handler crashed: {exc}\n{tb}", file=sys.stderr)
            try:
                write_json_response({
                    "jsonrpc": "2.0",
                    "id": 0,
                    "error": {"code": -32603, "message": f"Internal server error: {exc}"},
                })
            except Exception:
                pass
            # Stay in loop. Do not exit on per-request failure.

    print("MCP Server shutting down", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
