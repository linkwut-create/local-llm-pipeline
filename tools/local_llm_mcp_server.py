#!/usr/bin/env python3
"""
Local LLM MCP Server — exposes read-only CLI tools as MCP (Model Context Protocol) tools.

Transport: stdio JSON-RPC 2.0.
Read-only: never modifies source files, never runs arbitrary commands.

Usage:
    python tools/local_llm_mcp_server.py
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from local_llm_worker import is_blocked_path

# Concurrency guard: prevent multiple LLM calls from competing for GPU
_call_lock = threading.Lock()

# Quality-based escalation chain (Layer 4): task → ordered profiles by capability.
# When confidence=low or uncertain_points>3, the server auto-escalates to the next tier.
# Timeout errors fall back to a faster model instead.
_ESCALATION_CHAIN = {
    "summarize-file": ["fast_summary", "smart_summary", "qwen3.6_27b_mtp", "code_worker"],
    "summarize-tree": ["fast_summary", "smart_summary", "qwen3.6_27b_mtp"],
    "review-diff": ["commit_reviewer", "diff_reviewer", "deep_reviewer"],
    "generate-test-plan": ["code_worker", "qwen3.6_27b_mtp", "deep_reviewer"],
    "generate-test-draft": ["code_worker", "qwen3.6_27b_mtp", "deep_reviewer"],
    "draft-fix": ["code_worker", "qwen3.6_27b_mtp", "deep_reviewer"],
    "draft-feature": ["code_worker", "qwen3.6_27b_mtp", "deep_reviewer"],
    "draft-refactor": ["code_worker", "reasoning_checker", "deep_reviewer"],
    "suggest-improvements": ["qwen3.6_27b_mtp", "code_worker", "deep_reviewer"],
    "deep-code-review": ["qwen3.6_35b_moe_mtp", "deep_reviewer", "release_auditor"],
    "architecture-review": ["qwen3.6_35b_moe_mtp", "deep_reviewer", "release_auditor"],
    "release-risk-review": ["release_auditor", "deep_reviewer", "qwen3.6_35b_moe_mtp"],
    "risk-analysis": ["reasoning_checker", "deep_reasoning", "release_auditor"],
    "logic-check": ["reasoning_checker", "deep_reasoning"],
    "failure-mode-analysis": ["reasoning_checker", "deep_reasoning"],
    "contextual-analyze": ["qwen3.6_27b_mtp", "code_worker", "reasoning_checker"],
    "translate-text": ["translation", "qwen3.6_27b_mtp"],
    "rewrite-text": ["fast_summary", "smart_summary", "qwen3.6_27b_mtp"],
    "extract-todos": ["code_worker", "qwen3.6_27b_mtp"],
    "find-related-files": ["code_worker", "qwen3.6_27b_mtp"],
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
    """Update _health fields in profiles.json after each invocation.

    Uses weighted averages (90% old, 10% new) to smooth over outliers.
    Never raises — failures are silent.
    """
    if not profile_name:
        return
    try:
        profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
        profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
        profile = profiles.get("profiles", {}).get(profile_name, {})
        if not profile:
            return
        h = profile.get("_health", {})
        now = datetime.now(timezone.utc).isoformat()[:10]

        # Weighted success rate (90% old + 10% new)
        old_rate = h.get("success_rate", 1.0)
        new_point = 1.0 if ok else 0.0
        h["success_rate"] = round(old_rate * 0.9 + new_point * 0.1, 3)

        # Weighted avg latency
        old_lat = h.get("avg_latency_s", elapsed_s)
        h["avg_latency_s"] = round(old_lat * 0.9 + elapsed_s * 0.1, 1)

        # Timeout tracking
        if error_type == "timeout":
            h["last_timeout"] = now

        # Consecutive failures
        if ok:
            h["consecutive_failures"] = 0
        else:
            h["consecutive_failures"] = h.get("consecutive_failures", 0) + 1

        h["_updated"] = now
        profile["_health"] = h

        # Write back atomically
        tmp = str(profiles_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
        os.replace(tmp, profiles_path)
    except Exception:
        pass  # Health tracking is best-effort, never block on failure

_MAX_ESCALATION_DEPTH = 1  # Prevent infinite re-invocation loops

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
                         "reasoning_checker"}


def _check_quality_escalation(payload: dict, current_profile: str, task: str,
                               cjk_ratio: float = 0.0) -> str | None:
    """Determine if quality signals warrant escalating to a more capable profile.

    Returns the next profile name, or None if no escalation is needed.
    """
    chain = _ESCALATION_CHAIN.get(task, [])
    if current_profile not in chain or len(chain) < 2:
        return None
    idx = chain.index(current_profile)
    error_type = (payload.get("error_type") or "").lower()
    confidence = (payload.get("confidence") or "medium").lower()
    uncertain_count = len(payload.get("uncertain_points") or [])

    # Timeout → step down to a lighter/faster model
    if error_type == "timeout":
        if idx > 0:
            print(f"MCP: quality escalation — timeout, downgrading {current_profile} → {chain[0]}", file=sys.stderr)
            return chain[0]
        return None

    # Low confidence → escalate to next tier (prefer CJK-capable if CJK detected)
    if confidence == "low":
        target = None
        if cjk_ratio > 0.1 and current_profile not in _CJK_CAPABLE_PROFILES:
            target = _prefer_cjk_profile(current_profile, task)
        if target is None and idx + 1 < len(chain):
            target = chain[idx + 1]
        if target:
            print(f"MCP: quality escalation — confidence=low, upgrading {current_profile} → {target}", file=sys.stderr)
            return target
        return None

    # Many uncertain points → escalate
    if uncertain_count > 3:
        if idx + 1 < len(chain):
            target = chain[idx + 1]
            # If CJK detected and target is not CJK-capable, skip to first CJK-capable
            if cjk_ratio > 0.1 and target not in _CJK_CAPABLE_PROFILES:
                cjk_target = _prefer_cjk_profile(current_profile, task)
                if cjk_target:
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
            "required": ["task", "prompt"],
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


def run_subprocess(cmd: list[str], stdin_data: str | None = None,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a subprocess and return a structured result.

    Forces UTF-8 decoding with `errors="replace"` so non-ASCII output (e.g.
    Chinese in worker stderr / em-dashes in summaries) cannot trip a GBK
    locale UnicodeDecodeError on Windows. Also force the child's
    PYTHONIOENCODING to utf-8 so the worker writes UTF-8 to its own stdout.

    Uses the effective project root (LOCAL_LLM_TARGET_PROJECT when set) as
    cwd so output lands in the correct project's .local_llm_out/.
    """
    start = time.time()
    effective_root = _get_effective_project_root()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Direct worker output to the effective project's .local_llm_out/
    env.setdefault("LOCAL_LLM_OUTPUT_DIR", str(effective_root / ".local_llm_out"))
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
                              timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a subprocess with real-time progress via MCP $/progress notifications.

    Reads stdout line-by-line. Lines prefixed ``DATA:`` are treated as
    streaming content tokens and forwarded as progress notifications.
    Lines prefixed ``JSON:`` are the final output marker (same as batch mode).
    """
    start = time.time()
    effective_root = _get_effective_project_root()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("LOCAL_LLM_OUTPUT_DIR", str(effective_root / ".local_llm_out"))

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


def truncate_output(data: dict, max_keys: int = 500) -> dict:
    """Truncate large outputs to keep MCP responses manageable."""
    raw = json.dumps(data, ensure_ascii=False)
    if len(raw) <= 50000:
        return data
    truncated = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > 5000:
            truncated[k] = v[:5000] + "... [truncated]"
        elif isinstance(v, list) and len(v) > 50:
            truncated[k] = v[:50] + ["... [truncated]"]
        else:
            truncated[k] = v
    return truncated


def _wrap_worker_call(tool: str, cmd: list[str], stdin_data: str | None = None,
                      timeout: int = DEFAULT_TIMEOUT, task: str | None = None,
                      auto_escalate: bool = True, _depth: int = 0,
                      cjk_ratio: float = 0.0) -> dict:
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

    result = run_subprocess(cmd, stdin_data=stdin_data, timeout=timeout)
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
        if auto_escalate and task and _depth < _MAX_ESCALATION_DEPTH:
            current_profile = payload.get("profile", "")
            escalated = _check_quality_escalation(payload, current_profile, task, cjk_ratio=cjk_ratio)
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
                # Add escalated profile as a marker to skip further escalation for this profile
                print(f"MCP: re-running {task} with escalated profile: {escalated}", file=sys.stderr)
                return _wrap_worker_call(
                    tool, escalated_cmd, stdin_data=stdin_data,
                    timeout=timeout, task=task, auto_escalate=auto_escalate,
                    _depth=_depth + 1,
                )

        return build_success_response(tool, payload, result["elapsed_seconds"], request_id)

    return coerce_failure_response(tool, payload, result["stderr"], result["elapsed_seconds"], request_id)


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

    cmd = build_router_cmd("summarize-file", path_str, None, max_chars,
                           params.get("profile"), params.get("model"))
    return _wrap_worker_call("local_summarize_file", cmd, task="summarize-file")


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

    cmd = build_router_cmd("summarize-tree", path_str, max_files, max_chars,
                           params.get("profile"), params.get("model"))
    return _wrap_worker_call("local_summarize_tree", cmd, task="summarize-tree")


def call_generate_test_plan(params: dict) -> dict:
    path_str = params.get("path", "")
    ok, err = validate_path(path_str)
    if not ok:
        return build_error_response(
            tool="local_generate_test_plan", error_type="blocked_path", error=err,
            suggestion="use a file path that is not in the blocked list",
            profile=params.get("profile"), model=params.get("model"),
        )

    cmd = build_router_cmd("generate-test-plan", path_str, None, None,
                           params.get("profile"), params.get("model"))
    return _wrap_worker_call("local_generate_test_plan", cmd, task="generate-test-plan")


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
        if line_count > 100 or file_count >= 3 or (has_logic and file_count >= 2):
            return call_debate_review_diff(params)

    # C2: Security-sensitive patterns auto-trigger reasoning_checker (v0.9.6)
    reasoning_override = None
    if not commit_gate and _has_security_sensitive_patterns(diff_text):
        reasoning_override = "reasoning_checker"
        print("MCP: security-sensitive patterns detected — escalating to reasoning_checker", file=sys.stderr)

    # Phase 3A: CJK-aware routing — detect CJK content, prefer CJK-capable profiles
    cjk_ratio = _detect_cjk_ratio(diff_text)
    cjk_override = None
    if cjk_ratio > 0.1 and not commit_gate:
        user_profile = params.get("profile", "")
        if user_profile not in _CJK_CAPABLE_PROFILES:
            cjk_override = "qwen3.6_27b_mtp"  # Strong CJK capability, good for diff review
            print(f"MCP: CJK content detected ({cjk_ratio:.1%} CJK chars) — using CJK-capable profile", file=sys.stderr)

    # Use the caller's profile if provided, otherwise router picks commit_reviewer default
    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"), "review-diff", "--stdin"]
    if reasoning_override:
        cmd.extend(["--profile", reasoning_override])
    elif cjk_override:
        cmd.extend(["--profile", cjk_override])
    elif params.get("profile"):
        cmd.extend(["--profile", params["profile"]])
    if params.get("model"):
        cmd.extend(["--model", params["model"]])

    request_id = _make_request_id()
    result = run_subprocess(cmd, stdin_data=diff_text, timeout=REVIEW_TIMEOUT)

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

    # Use the router for model resolution, then worker for actual analysis
    cmd = build_router_cmd("suggest-improvements", path_str, None, max_chars,
                           params.get("profile"), params.get("model"))
    return _wrap_worker_call("local_contextual_analyze", cmd, stdin_data=stdin_data, task="contextual-analyze")


def call_draft_code(params: dict) -> dict:
    task = params.get("task", "draft-fix")
    prompt = params.get("prompt", "")
    context_file = params.get("context_file", "")

    if not prompt.strip():
        return build_error_response(
            tool="local_draft_code", error_type="empty_input",
            error="prompt is empty",
            suggestion="describe the fix/feature/refactor in the prompt",
            profile=params.get("profile"), model=params.get("model"), task=task,
        )

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

    if params.get("profile"):
        cmd.extend(["--profile", params["profile"]])
    if params.get("model"):
        cmd.extend(["--model", params["model"]])

    return _wrap_worker_call("local_draft_code", cmd, stdin_data=prompt, task=task)


TOOL_HANDLERS = {
    "local_check": call_local_check,
    "local_summarize_file": call_summarize_file,
    "local_summarize_tree": call_summarize_tree,
    "local_generate_test_plan": call_generate_test_plan,
    "local_contextual_analyze": call_contextual_analyze,
    "local_review_diff": call_review_diff,
    "local_debate_review_diff": call_debate_review_diff,
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
