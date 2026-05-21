#!/usr/bin/env python3
"""
Local LLM Worker — executes a single task against a local model.

Produces structured JSON + Markdown output in .local_llm_out/.
Read-only: never modifies source files.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"
TASKS_PATH = SCRIPT_DIR / "local_llm_tasks.json"

BLOCKED_PATHS = {
    ".git", ".env", ".env.local", ".env.production", ".env.development",
    "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    "target", ".local_llm_out",
}
BLOCKED_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".jks"}
BLOCKED_FILENAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".env"}

SYSTEM_PROMPT_BASE = """You are a local auxiliary worker, NOT the final decision-maker.
Rules:
- You CANNOT modify files.
- You CANNOT claim you ran tests.
- You CANNOT fabricate project facts.
- You can ONLY analyze based on the input text provided.
- When information is insufficient, you MUST explicitly say "INSUFFICIENT".
- Your output MUST be structured.
- Your output will be reviewed by the controller (Claude Code / Codex).
- Do NOT repeat the input verbatim.
- Do NOT produce overly long explanations.
- Prioritize: key files, risk points, test gaps, items requiring controller review.
"""

TASK_PROMPTS = {
    "summarize-file": """Summarize this file. Output:
1. File purpose (one sentence)
2. Key functions/classes/exports
3. Dependencies
4. Potential issues
5. Uncertain points
Keep under 800 words.""",

    "summarize-tree": """Summarize this directory listing and file contents. Output:
1. Directory purpose
2. Main modules
3. Key files list (with one-line description each)
4. Files that can be ignored
5. Suggested reading order for the controller
6. Uncertain points
Keep under 1500 words.""",

    "extract-todos": """Extract all TODO, FIXME, HACK, XXX, NOTE comments from this code. Output JSON array:
[{"file": "path", "line": N, "tag": "TODO", "text": "..."}]
Only report comments actually present. Do NOT invent any.""",

    "find-related-files": """Given this query and file listing, identify the most relevant files. Output:
1. Directly related files (with reason)
2. Possibly related files
3. Unrelated files to skip
Do NOT fabricate file paths.""",

    "generate-test-plan": """Generate a test plan for this code. Output:
1. Behaviors to cover
2. Normal paths
3. Boundary conditions
4. Error paths
5. Backward compatibility points
6. Recommended test file names
Do NOT claim any tests already pass.""",

    "generate-test-draft": """Draft test skeleton code for this code. Output:
1. Test file structure
2. Test function stubs with descriptive names
3. Assertions to add (as comments)
4. Edge cases to cover
Mark this as DRAFT — controller must finalize.""",

    "review-diff": """Review this git diff. Output:
1. Change overview (what changed, why it might have changed)
2. Candidate bugs
3. Compatibility risks
4. Test gaps
5. Locations the controller MUST inspect
6. Uncertain points
Do NOT approve or reject. Only report findings.""",

    "deep-code-review": """Deep review this code. Output:
1. Architecture observations
2. Code quality issues
3. Security concerns
4. Performance concerns
5. Maintainability issues
6. Items requiring controller verification
Do NOT approve. Advisory only.""",

    "architecture-review": """Review this architecture / design. Output:
1. Strengths
2. Weaknesses
3. Alternative approaches
4. Tradeoffs
5. Risks
6. Questions for the controller
Advisory only.""",

    "risk-analysis": """Analyze risks in this code/plan. Output:
1. Failure modes
2. Worst case scenarios
3. Overlooked edge cases
4. Counter-examples
5. Items requiring controller confirmation
Do NOT make final decisions.""",

    "logic-check": """Check the logical consistency of this code/plan. Output:
1. Logical issues found
2. Contradictions
3. Implicit assumptions
4. Missing validations
5. Uncertain areas""",

    "failure-mode-analysis": """Enumerate failure modes. Output:
1. Each failure mode with: trigger, impact, likelihood
2. Cascade failures
3. Recovery gaps
4. Items the controller must verify
Do NOT claim exhaustive coverage.""",

    "translate-text": """Translate the following text. Preserve formatting and technical terms.
Target language: {target_language}
Style: {style}""",

    "rewrite-text": """Rewrite/improve this text. Preserve technical meaning.
Style: {style}
Keep it concise.""",

    "draft-fix": """Draft a code fix for the described issue. Output:
1. Problem restatement (one sentence — confirm you understood)
2. Files to modify
3. Draft code changes (with enough context to locate the insertion point)
4. Why this fix addresses the issue
5. Risks or side effects of this fix
6. Items for controller to verify
This is a DRAFT. The controller will review, possibly modify, and apply manually.
Do NOT claim the fix is complete or correct. The controller makes the final decision.""",

    "draft-feature": """Draft an implementation for the described feature. Output:
1. Feature restatement (one sentence)
2. Files to create or modify
3. Draft code (with function/class signatures and key logic)
4. Integration points (where this touches existing code)
5. Edge cases the draft handles
6. Edge cases the draft does NOT handle (let controller decide)
This is a DRAFT. The controller decides whether to implement, modify, or discard.
Do NOT claim completeness. Draft only — the controller writes the final code.""",

    "draft-refactor": """Draft a refactoring plan for the described issue. Output:
1. What is being refactored and why
2. Files affected
3. Draft refactored code (show the key structural changes)
4. Migration path (how to apply incrementally)
5. Backward compatibility risks
6. Items the controller must verify before applying
This is a DRAFT. The controller decides whether and how to apply the changes.
Never suggest deleting code the controller hasn't explicitly marked for removal.""",

    "suggest-improvements": """Proactively suggest improvements for this code. Output:
1. Quick wins (small, safe changes with clear benefit)
2. Structural improvements (larger changes worth considering)
3. Code quality improvements (naming, comments, error handling)
4. Performance opportunities
5. Things that should NOT be changed (and why)
6. Priority order (what to do first)
This is ADVISORY ONLY. The controller decides which suggestions to pursue.
Do NOT claim urgency. Each suggestion must stand on its own merit.""",
}


# MCP Cost Discipline P2-C1.0: callers (MCP server / hook) may stamp per-call
# cost-discipline context for the call ledger via the LOCAL_LLM_LEDGER_EXTRA
# env var. This helper reads it, intersects with the P2-B allowlist, and
# returns a dict ready to be passed as `extra=` to call_ledger.build_record.
#
# Contract:
#   - Never raises.
#   - Never mutates os.environ.
#   - Returns {} on: unset env, empty string, malformed JSON, non-dict JSON,
#     missing call_ledger module, or any unexpected failure.
#   - Only allowlisted keys (KNOWN_EXTRA_KEYS) are returned. Unknown keys —
#     including secret-shaped keys like api_key / token / password / secret /
#     authorization — are dropped at this layer. Defence-in-depth: the ledger
#     itself also strips _FORBIDDEN_KEYS in build_record.
#
# P2-C1.1 / P2-C1.2 will *set* this env var from the MCP server and the
# auto-hook respectively. P2-C1.0 only consumes it.
def _load_ledger_extra_from_env() -> dict:
    raw = os.environ.get("LOCAL_LLM_LEDGER_EXTRA")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    try:
        script_dir_str = str(SCRIPT_DIR)
        if script_dir_str not in sys.path:
            sys.path.insert(0, script_dir_str)
        from call_ledger import KNOWN_EXTRA_KEYS
    except Exception:
        return {}
    return {k: v for k, v in data.items() if k in KNOWN_EXTRA_KEYS}


@dataclass
class WorkerConfig:
    provider: str = "ollama"
    model: str = ""
    profile: str = ""
    base_url: str = ""
    timeout: int = 300
    max_chars: int = 60000
    max_output_chars: int = 3000
    output_dir: str = ".local_llm_out"
    target_language: str = "zh-CN"
    style: str = "concise"
    json_only: bool = False
    no_markdown: bool = False
    stream: bool = False


@dataclass
class WorkerOutput:
    task: str = ""
    tool: str = ""
    profile: str = ""
    model: str = ""
    provider: str = ""
    base_url: str = ""
    input: dict = field(default_factory=dict)
    ok: bool = False
    summary: str = ""
    key_files: list = field(default_factory=list)
    must_read: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    test_gaps: list = field(default_factory=list)
    uncertain_points: list = field(default_factory=list)
    confirmed_by_worker: list = field(default_factory=list)
    not_verified: list = field(default_factory=list)
    confidence: str = "low"
    result: str = ""
    warnings: list = field(default_factory=list)
    error: Optional[str] = None
    error_type: Optional[str] = None
    suggestion: Optional[str] = None
    retries: int = 0
    created_at: str = ""
    truncated_files: list = field(default_factory=list)
    truncation_report: list = field(default_factory=list)
    total_input_chars: int = 0
    included_input_chars: int = 0
    # Prompt-registry traceability (v0.9.3)
    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    request_id: Optional[str] = None
    cache_hit: bool = False


def is_blocked_path(path: Path) -> bool:
    parts = path.parts
    for part in parts:
        if part in BLOCKED_PATHS:
            return True
    if path.suffix in BLOCKED_EXTENSIONS:
        return True
    if path.name in BLOCKED_FILENAMES:
        return True
    # Block .env.* variants
    if path.name.startswith(".env."):
        return True
    return False


def read_file_safe(path: Path, max_chars: int) -> tuple[str, list[str]]:
    warnings = []
    if is_blocked_path(path):
        return "", [f"BLOCKED: {path} is in the restricted path list"]
    if not path.exists():
        return "", [f"NOT FOUND: {path}"]
    if not path.is_file():
        return "", [f"NOT A FILE: {path}"]
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            warnings.append(f"TRUNCATED: {path} from {len(content)} to {max_chars} chars")
            content = content[:max_chars] + f"\n\n[TRUNCATED at {max_chars} chars]"
        return content, warnings
    except Exception as e:
        return "", [f"READ ERROR: {path}: {e}"]


HIGH_PRIORITY_NAMES = {
    "readme.md", "agents.md", "claude.md", "package.json", "pyproject.toml",
    "makefile", "cargo.toml", "go.mod", "main.py", "app.py", "index.ts",
    "server.ts", "index.js", "server.js",
}
HIGH_PRIORITY_PATTERNS = ["_router.", "_worker.", "_tasks.", "_profiles.", "_check."]
LOW_PRIORITY_EXTENSIONS = {".lock", ".sum", ".log", ".csv"}


def _file_priority(path: Path) -> int:
    name_lower = path.name.lower()
    if name_lower in HIGH_PRIORITY_NAMES:
        return 0
    for pat in HIGH_PRIORITY_PATTERNS:
        if pat in name_lower:
            return 1
    if path.suffix in LOW_PRIORITY_EXTENSIONS:
        return 3
    return 2


@dataclass
class _FileEntry:
    path: Path
    rel: str
    size: int
    priority: int


def collect_tree(root: Path, max_files: int, max_chars: int) -> tuple[str, list[str], list[dict]]:
    """Collect files with adaptive budget allocation. Returns (content, warnings, truncation_report)."""
    warnings = []
    truncation_report = []

    candidates: list[_FileEntry] = []
    for dirpath_str, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath_str)
        dirnames[:] = [d for d in dirnames if d not in BLOCKED_PATHS]
        for fname in sorted(filenames):
            fpath = dirpath / fname
            if is_blocked_path(fpath):
                continue
            if not fpath.is_file():
                continue
            try:
                raw = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = str(fpath.relative_to(root)) if fpath.is_relative_to(root) else str(fpath)
            candidates.append(_FileEntry(
                path=fpath, rel=rel, size=len(raw), priority=_file_priority(fpath)
            ))

    candidates.sort(key=lambda e: (e.priority, -e.size))
    selected = candidates[:max_files]
    if len(candidates) > max_files:
        warnings.append(f"MAX FILES REACHED: selected {max_files} of {len(candidates)} candidates")

    selected.sort(key=lambda e: e.size)

    budget = max_chars
    parts = []
    for entry in selected:
        raw = entry.path.read_text(encoding="utf-8", errors="replace")
        header = f"=== FILE: {entry.rel} ===\n"
        header_cost = len(header) + 2  # newline separators

        if len(raw) + header_cost <= budget:
            parts.append(header + raw)
            budget -= len(raw) + header_cost
        elif budget > header_cost + 200:
            allowed = budget - header_cost - 50
            parts.append(header + raw[:allowed] + f"\n\n[TRUNCATED at {allowed} chars of {len(raw)}]")
            truncation_report.append({
                "path": entry.rel,
                "original_chars": len(raw),
                "included_chars": allowed,
                "reason": "global_budget_limit",
            })
            warnings.append(f"TRUNCATED: {entry.rel} from {len(raw)} to {allowed} chars")
            budget = 0
        else:
            truncation_report.append({
                "path": entry.rel,
                "original_chars": len(raw),
                "included_chars": 0,
                "reason": "budget_exhausted",
            })
            warnings.append(f"SKIPPED: {entry.rel} ({len(raw)} chars) — budget exhausted")

    return "\n\n".join(parts), warnings, truncation_report


def build_prompt(task: str, content: str, config: WorkerConfig) -> tuple[str, str, dict]:
    """Build the (system, user) prompt pair plus a metadata dict.

    Metadata dict keys: prompt_id, prompt_version, prompt_hash. Values are None
    when the prompt came from the hardcoded fallback.
    """
    meta: dict = {"prompt_id": None, "prompt_version": None, "prompt_hash": None}
    try:
        from local_llm_prompt_registry import load_prompt
        p = load_prompt(task)
        if p:
            task_prompt = p.text
            meta["prompt_id"] = p.prompt_id
            meta["prompt_version"] = p.version
            meta["prompt_hash"] = p.hash
        else:
            task_prompt = TASK_PROMPTS.get(task, f"Analyze the following content for task: {task}")
    except Exception:
        task_prompt = TASK_PROMPTS.get(task, f"Analyze the following content for task: {task}")

    if "{target_language}" in task_prompt:
        task_prompt = task_prompt.replace("{target_language}", config.target_language)
    if "{style}" in task_prompt:
        task_prompt = task_prompt.replace("{style}", config.style)

    system = SYSTEM_PROMPT_BASE + f"\nTask: {task}\n"
    user = f"{task_prompt}\n\n---\n\n{content}"
    return system, user, meta


def call_ollama(system: str, user: str, config: WorkerConfig) -> "ModelCallResult":
    from model_call_result import ModelCallResult, normalize_usage
    url = f"{config.base_url}/api/chat"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "num_predict": config.max_output_chars,
        },
    }
    resp = requests.post(url, json=payload, timeout=config.timeout)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("message", {}).get("content", "") if isinstance(data, dict) else ""
    usage = normalize_usage("ollama", data) if isinstance(data, dict) else None
    return ModelCallResult(content=content, usage=usage, raw_provider="ollama")


def call_openai_compat(system: str, user: str, config: WorkerConfig) -> "ModelCallResult":
    from model_call_result import ModelCallResult, normalize_usage
    url = f"{config.base_url}/chat/completions"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": config.max_output_chars,
        "stream": False,
    }
    resp = requests.post(url, json=payload, timeout=config.timeout)
    resp.raise_for_status()
    data = resp.json()
    content = ""
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            content = choices[0].get("message", {}).get("content", "") or ""
    usage = normalize_usage("openai-compatible", data) if isinstance(data, dict) else None
    return ModelCallResult(content=content, usage=usage, raw_provider="openai-compatible")


def call_ollama_stream(system: str, user: str, config: WorkerConfig):
    """Yield content chunks from Ollama streaming /api/chat (NDJSON)."""
    url = f"{config.base_url}/api/chat"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
        "options": {"num_predict": config.max_output_chars},
    }
    resp = requests.post(url, json=payload, timeout=config.timeout, stream=True)
    resp.raise_for_status()
    for line in resp.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        if chunk.get("done"):
            break
        token = chunk.get("message", {}).get("content", "")
        if token:
            yield token


def call_openai_compat_stream(system: str, user: str, config: WorkerConfig):
    """Yield content deltas from OpenAI-compatible streaming /v1/chat/completions (SSE)."""
    url = f"{config.base_url}/chat/completions"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": config.max_output_chars,
        "stream": True,
    }
    resp = requests.post(url, json=payload, timeout=config.timeout, stream=True)
    resp.raise_for_status()
    for line in resp.iter_lines():
        if not line or line.startswith(b":"):
            continue
        if line.startswith(b"data: "):
            data = line[6:]
            if data == b"[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    yield delta
            except json.JSONDecodeError:
                continue


# Tasks that should NOT be retried (long-running, expensive, or draft-generating)
NO_RETRY_TASKS = {
    "debate-review-diff", "debate-risk-analysis",
    "debate-architecture-review", "debate-failure-mode-analysis",
    "draft-fix", "draft-feature", "draft-refactor",
    "benchmark",
}

MAX_RETRIES = 1
RETRY_DELAY_SECONDS = 2.0


def classify_error(exc: Exception, task: str) -> tuple[str, str]:
    """Classify an exception into an error_type and a user-facing suggestion."""
    msg = str(exc).lower() if str(exc) else ""

    if isinstance(exc, requests.Timeout):
        return ("timeout",
                f"model call timed out after {getattr(exc, 'timeout', '?')}s — "
                f"try a smaller input, a faster profile, or increase timeout")

    if isinstance(exc, requests.ConnectionError):
        return ("backend_unreachable",
                "Ollama backend is not reachable — check that Ollama is running "
                "and OLLAMA_HOST / LOCAL_LLM_BASE_URL is correct")

    if "timeout" in msg or "timed" in msg:
        return ("timeout",
                "model call timed out — try a smaller input or increase timeout")

    if "connection" in msg or "refused" in msg or "unreachable" in msg:
        return ("backend_unreachable",
                "backend connection failed — verify the backend is running")

    if "empty" in msg or "no content" in msg:
        return ("empty_response",
                "model returned empty response — the model may be overloaded or "
                "the prompt may be incompatible")

    if "json" in msg or "decode" in msg or "parse" in msg:
        return ("invalid_json",
                "model response could not be parsed — the output format may be invalid")

    if "500" in msg or "server error" in msg:
        return ("backend_error",
                "backend returned a server error — the model may be overloaded, "
                "try a smaller model or retry later")

    return ("unknown_error",
            "an unexpected error occurred — check the error details above")


def call_model_with_retry(system: str, user: str, config: WorkerConfig,
                          task: str = ""):
    """Call model with optional retry for transient failures.

    Returns (ModelCallResult | None, error_info).
      - On success: (ModelCallResult, {})
      - On failure: (None, {"error_type": ..., "error": ..., ...})

    v2-A: stream path is not routed through this function (worker handles
    streaming inline). This function is for non-stream calls only.
    """
    should_retry = task not in NO_RETRY_TASKS
    last_error = None
    retries = 0

    for attempt in range(MAX_RETRIES + 1):
        try:
            result = call_model(system, user, config)
            content = result.content if result is not None else ""
            # Check for empty response
            if not content or not content.strip():
                error_type, suggestion = classify_error(
                    ValueError("empty response from model"), task)
                if should_retry and attempt < MAX_RETRIES:
                    retries += 1
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                return None, {"error_type": error_type,
                              "error": "model returned empty response",
                              "suggestion": suggestion, "retries": retries}
            return result, {}
        except Exception as e:
            last_error = e
            error_type, suggestion = classify_error(e, task)
            if should_retry and attempt < MAX_RETRIES:
                retries += 1
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            return None, {"error_type": error_type, "error": str(e)[:300],
                          "suggestion": suggestion, "retries": retries}

    # Should never reach here, but just in case
    error_type, suggestion = classify_error(last_error or Exception("unknown"), task)
    return None, {"error_type": error_type,
                  "error": str(last_error)[:300] if last_error else "unknown",
                  "suggestion": suggestion, "retries": retries}


def call_model(system: str, user: str, config: WorkerConfig):
    """Dispatch to the appropriate provider call.

    v2-A:
      - non-stream path returns ModelCallResult.
      - stream path returns a Generator[str] (unchanged from v1).

    Callers already branch on `config.stream` before consuming the result,
    so the mode-dependent return type does not leak. Streaming is deferred
    to v2-B; see docs/CALL_LEDGER_V2_PLAN.md §3.5.
    """
    if config.stream:
        return call_model_stream(system, user, config)
    if config.provider == "ollama":
        return call_ollama(system, user, config)
    elif config.provider == "openai-compatible":
        return call_openai_compat(system, user, config)
    else:
        raise ValueError(f"Unknown provider: {config.provider}")


def call_model_stream(system: str, user: str, config: WorkerConfig):
    """Stream tokens from the model. Returns a generator yielding content chunks."""
    if config.provider == "ollama":
        return call_ollama_stream(system, user, config)
    elif config.provider == "openai-compatible":
        return call_openai_compat_stream(system, user, config)
    else:
        raise ValueError(f"Unknown provider: {config.provider}")


def parse_structured(raw: str, task: str) -> dict:
    """Parse LLM output into structured fields using keyword matching.

    v0.9.5: expanded to cover Chinese keywords (models often emit mixed-language
    output) and weaker signal phrases that older logic missed.
    """
    parsed = {
        "key_files": [],
        "must_read": [],
        "risks": [],
        "test_gaps": [],
        "uncertain_points": [],
    }

    lines = raw.split("\n")
    for line in lines:
        lower = line.lower().strip()

        # Must-read signals
        if any(kw in lower for kw in [
            "must read", "must inspect", "controller must",
            "务必检查", "必须审查", "关键文件", "重要文件",
            "pay attention", "important to read",
            "should be reviewed", "needs manual check",
        ]):
            parsed["must_read"].append(line.strip())

        # Risk signals
        if any(kw in lower for kw in [
            "risk", "danger", "warning", "concern",
            "风险", "危险", "警告", "潜在问题",
            "vulnerable", "unsafe", "could fail",
            "might cause", "breaking change",
            "security issue", "brittle", "fragile",
        ]):
            parsed["risks"].append(line.strip())

        # Test gap signals
        if any(kw in lower for kw in [
            "test gap", "missing test", "untested", "no test",
            "缺少测试", "未测试", "测试不足", "没有测试",
            "not covered", "coverage gap",
            "should test", "needs a test",
        ]):
            parsed["test_gaps"].append(line.strip())

        # Uncertainty signals
        if any(kw in lower for kw in [
            "uncertain", "unclear", "insufficient", "unknown", "unsure",
            "不确定", "不清楚", "信息不足", "未知", "难以判断",
            "ambiguous", "vague", "lacks detail",
            "needs more context", "should verify",
            "possibly", "might be", "could be",
        ]):
            parsed["uncertain_points"].append(line.strip())

    file_pattern = re.compile(r'[\w./\\-]+\.\w{1,10}')
    for match in file_pattern.finditer(raw):
        candidate = match.group()
        if candidate not in parsed["key_files"] and ("/" in candidate or "\\" in candidate):
            parsed["key_files"].append(candidate)

    # Deduplicate while preserving order
    for key in parsed:
        seen = set()
        deduped = []
        for item in parsed[key]:
            normalized = item.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                deduped.append(item)
        parsed[key] = deduped

    return parsed


def save_output(output: WorkerOutput, config: WorkerConfig) -> tuple[Path, Path]:
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{ts}_{output.task}"

    json_path = out_dir / f"{base_name}.json"
    md_path = out_dir / f"{base_name}.md"

    json_path.write_text(json.dumps(asdict(output), indent=2, ensure_ascii=False), encoding="utf-8")

    if not config.no_markdown:
        md_content = f"# Local Worker Output: {output.task}\n\n"
        md_content += f"- **Model**: {output.model}\n"
        md_content += f"- **Profile**: {output.profile}\n"
        md_content += f"- **Provider**: {output.provider}\n"
        md_content += f"- **Confidence**: {output.confidence}\n"
        md_content += f"- **Time**: {output.created_at}\n\n"

        if output.summary:
            md_content += f"## Summary\n\n{output.summary}\n\n"
        if output.must_read:
            md_content += "## Controller Must Read\n\n"
            for item in output.must_read:
                md_content += f"- {item}\n"
            md_content += "\n"
        if output.risks:
            md_content += "## Risks\n\n"
            for item in output.risks:
                md_content += f"- {item}\n"
            md_content += "\n"
        if output.test_gaps:
            md_content += "## Test Gaps\n\n"
            for item in output.test_gaps:
                md_content += f"- {item}\n"
            md_content += "\n"
        if output.uncertain_points:
            md_content += "## Uncertain Points\n\n"
            for item in output.uncertain_points:
                md_content += f"- {item}\n"
            md_content += "\n"
        if output.warnings:
            md_content += "## Warnings\n\n"
            for item in output.warnings:
                md_content += f"- {item}\n"
            md_content += "\n"

        md_content += "## Full Result\n\n"
        md_content += output.result + "\n"

        md_content += "\n---\n\n"
        md_content += "**Not verified by worker:**\n\n"
        for item in output.not_verified:
            md_content += f"- {item}\n"

        md_path.write_text(md_content, encoding="utf-8")

    return json_path, md_path


def load_profile(profile_name: str) -> dict:
    if not PROFILES_PATH.exists():
        return {}
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    profiles = data.get("profiles", {})
    return profiles.get(profile_name, {})


def load_task_config(task_name: str) -> dict:
    if not TASKS_PATH.exists():
        return {}
    data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    tasks = data.get("tasks", {})
    return tasks.get(task_name, {})


def resolve_config(args: argparse.Namespace) -> WorkerConfig:
    task_conf = load_task_config(args.task)
    profile_name = args.profile or task_conf.get("default_profile", "fast_summary")
    profile = load_profile(profile_name)

    config = WorkerConfig()
    # Auto-detect provider: when LOCAL_LLM_BASE_URL points to a non-Ollama
    # endpoint (e.g. llama.cpp on ports 8080-8083), switch to openai-compatible.
    env_base = os.environ.get("LOCAL_LLM_BASE_URL", "")
    auto_provider = "ollama"
    if env_base and ":11434" not in env_base:
        auto_provider = "openai-compatible"
    config.provider = (
        args.provider
        or os.environ.get("LOCAL_LLM_PROVIDER")
        or auto_provider
    )
    config.model = (
        args.model
        or os.environ.get("LOCAL_LLM_MODEL")
        or profile.get("model", "")
    )
    config.profile = profile_name

    if config.provider == "ollama":
        ollama_host = os.environ.get("OLLAMA_HOST", "")
        if ollama_host and not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"
        config.base_url = args.base_url or env_base or ollama_host or "http://localhost:11434"
    else:
        config.base_url = args.base_url or env_base or "http://localhost:8080/v1"

    config.timeout = int(
        args.timeout
        or os.environ.get("LOCAL_LLM_TIMEOUT")
        or profile.get("timeout", 300)
    )
    config.max_chars = int(
        args.max_chars
        or os.environ.get("LOCAL_LLM_MAX_CHARS")
        or profile.get("max_chars", 60000)
    )
    config.max_output_chars = int(
        args.max_output_chars
        or task_conf.get("max_output_chars")
        or profile.get("max_output_chars", 3000)
    )
    config.output_dir = (
        os.environ.get("LOCAL_LLM_OUTPUT_DIR")
        or args.output_dir
        or ".local_llm_out"
    )
    config.target_language = args.target_language or "zh-CN"
    config.style = args.style or "concise"
    config.json_only = args.json_only
    config.no_markdown = args.no_markdown
    config.stream = getattr(args, "stream", False)
    return config


def collect_tree_entries(root: Path, max_files: int) -> list[dict]:
    """Walk a directory and return [{path, size, mtime_ns}, ...] for cache keying.

    Mirrors collect_tree's filtering rules so the cache key reflects what the
    LLM actually saw. Never raises; returns empty list on irrecoverable error.
    """
    entries: list[dict] = []
    try:
        for dirpath_str, dirnames, filenames in os.walk(root):
            dp = Path(dirpath_str)
            dirnames[:] = [d for d in dirnames if d not in BLOCKED_PATHS]
            for fname in sorted(filenames):
                fp = dp / fname
                if is_blocked_path(fp) or not fp.is_file():
                    continue
                try:
                    stat = fp.stat()
                except OSError:
                    continue
                rel = str(fp.relative_to(root)) if fp.is_relative_to(root) else str(fp)
                entries.append({
                    "path": rel,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                })
        # Match collect_tree: take up to max_files highest-priority items
        if len(entries) > max_files:
            entries = entries[:max_files]
    except Exception:
        return []
    return entries


def gather_input(args: argparse.Namespace, config: WorkerConfig) -> tuple[str, dict, list[str], list[dict]]:
    """Returns (content, input_meta, warnings, truncation_report).

    For summarize-tree, input_meta carries `tree_entries` so cache keying does
    not have to re-derive directory listings from a flat string blob.
    """
    warnings = []
    truncation_report = []
    input_meta = {"path": None, "stdin": False, "max_files": None, "max_chars": config.max_chars}

    if args.stdin:
        content = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if len(content) > config.max_chars:
            warnings.append(f"STDIN truncated from {len(content)} to {config.max_chars} chars")
            content = content[:config.max_chars]
        input_meta["stdin"] = True
        return content, input_meta, warnings, truncation_report

    target = args.target
    if not target:
        return "", input_meta, ["No target specified and --stdin not used"], truncation_report

    target_path = Path(target)
    input_meta["path"] = str(target_path)

    if target_path.is_file():
        content, file_warnings = read_file_safe(target_path, config.max_chars)
        warnings.extend(file_warnings)
        return content, input_meta, warnings, truncation_report

    if target_path.is_dir():
        max_files = args.max_files or 30
        input_meta["max_files"] = max_files
        content, tree_warnings, tree_truncation = collect_tree(target_path, max_files, config.max_chars)
        warnings.extend(tree_warnings)
        truncation_report.extend(tree_truncation)
        input_meta["tree_entries"] = collect_tree_entries(target_path, max_files)
        return content, input_meta, warnings, truncation_report

    return "", input_meta, [f"Target not found: {target}"], truncation_report


def _compute_cache_key_safe(task: str, target: str | None, input_meta: dict,
                             max_files: int | None, profile: str, model: str):
    """Compute the cache key for a cacheable task. Returns (key, warning_or_None).

    Never raises; on any failure returns (None, message) so the caller can skip
    cache instead of crashing the whole worker run.
    """
    try:
        from local_llm_cache import compute_file_key, compute_tree_key
        if task == "summarize-file" and target:
            return compute_file_key(target, profile, model), None
        if task == "summarize-tree" and target:
            entries = input_meta.get("tree_entries") or []
            return compute_tree_key(target, max_files or 30, entries, profile, model), None
    except Exception as exc:
        return None, f"cache-key computation skipped: {exc}"
    return None, None


def _emit_failure(output: WorkerOutput, config: WorkerConfig,
                  *, return_code: int = 1) -> int:
    """Persist a failure WorkerOutput and emit the standard stderr/stdout markers.

    Always prints a `JSON: <path>` line so the MCP wrapper (or any other
    consumer that parses subprocess output) can locate this exact result file
    instead of falling back to whatever happens to be the latest file in
    .local_llm_out/.
    """
    output.ok = False
    if not output.created_at:
        output.created_at = datetime.now(timezone.utc).isoformat()
    try:
        json_path, _ = save_output(output, config)
    except Exception as exc:
        # Last-resort fallback: write a minimal JSON so the wrapper isn't blind.
        out_dir = Path(config.output_dir or ".local_llm_out")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / f"{ts}_{output.task or 'unknown'}.json"
        try:
            json_path.write_text(json.dumps({
                "task": output.task,
                "ok": False,
                "error": output.error or str(exc),
                "error_type": output.error_type or "save_failed",
                "suggestion": output.suggestion or "",
                "request_id": output.request_id,
                "prompt_id": output.prompt_id,
                "prompt_version": output.prompt_version,
                "prompt_hash": output.prompt_hash,
                "created_at": output.created_at,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    print(f"ERROR: [{output.error_type or 'unknown_error'}] {output.error}", file=sys.stderr)
    if output.suggestion:
        print(f"SUGGESTION: {output.suggestion}", file=sys.stderr)
    print(f"JSON: {json_path}")
    return return_code


def run(args: argparse.Namespace) -> int:
    """Top-level worker entry. Wraps _run_inner so an unexpected exception
    still produces a structured JSON file plus a `JSON:` marker on stdout.
    A traceback that escapes here would (a) hide the bug from any subprocess
    parent, and (b) cause the MCP wrapper to fall back to a stale result —
    both of which v0.9.2 actually did. Don't let that happen again.
    """
    try:
        return _run_inner(args)
    except SystemExit:
        raise
    except BaseException as exc:
        import traceback as _tb
        tb_text = _tb.format_exc()
        try:
            config = resolve_config(args)
        except Exception:
            config = WorkerConfig()
        last_line = (tb_text.strip().splitlines() or [""])[-1][:300]
        output = WorkerOutput(
            task=getattr(args, "task", "") or "unknown",
            tool=getattr(args, "task", "") or "unknown",
            profile=config.profile,
            model=config.model,
            provider=config.provider,
            base_url=config.base_url,
            error=f"internal worker error: {exc}"[:300],
            error_type="internal_error",
            suggestion="check stderr traceback or report a v0.9.3 bug",
            warnings=[last_line] if last_line else [],
            created_at=datetime.now(timezone.utc).isoformat(),
            not_verified=[
                "Worker did not run tests",
                "Worker did not read full project context",
                "Worker did not verify file existence",
                "Worker output is advisory only",
            ],
        )
        # Print full traceback to stderr so subprocess parents can capture it.
        print(tb_text, file=sys.stderr)
        return _emit_failure(output, config)


def _run_inner(args: argparse.Namespace) -> int:
    config = resolve_config(args)

    from local_llm_logging import _make_request_id
    request_id = _make_request_id()

    output = WorkerOutput(
        task=args.task,
        tool=args.task,
        profile=config.profile,
        model=config.model,
        provider=config.provider,
        base_url=config.base_url,
        request_id=request_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        not_verified=[
            "Worker did not run tests",
            "Worker did not read full project context",
            "Worker did not verify file existence",
            "Worker output is advisory only",
        ],
    )

    if not config.model:
        output.error = "No model specified. Check profiles or pass --model."
        output.error_type = "no_model"
        output.suggestion = "set LOCAL_LLM_MODEL or pass --model / --profile"
        output.warnings.append("No model available")
        return _emit_failure(output, config)

    content, input_meta, gather_warnings, trunc_report = gather_input(args, config)
    output.input = input_meta
    output.warnings.extend(gather_warnings)
    output.truncation_report = trunc_report
    output.truncated_files = [r["path"] for r in trunc_report]
    output.total_input_chars = len(content) + sum(r.get("original_chars", 0) - r.get("included_chars", 0) for r in trunc_report)
    output.included_input_chars = len(content)

    if not content:
        output.error = "No input content to analyze"
        output.error_type = "empty_input"
        output.suggestion = "pass a non-empty file/dir or feed --stdin with content"
        output.warnings.append("Empty input")
        return _emit_failure(output, config)

    system, user, prompt_meta = build_prompt(args.task, content, config)
    output.prompt_id = prompt_meta.get("prompt_id")
    output.prompt_version = prompt_meta.get("prompt_version")
    output.prompt_hash = prompt_meta.get("prompt_hash")

    # Cache check for cacheable tasks (never let a cache failure crash the run).
    from local_llm_cache import CACHEABLE_TASKS, get_cache, put_cache
    from local_llm_logging import log_success as ls, log_failure as lf
    try:
        from call_ledger import (
            build_record as _ledger_build,
            record_call as _ledger_record,
            git_state as _ledger_git_state,
        )
    except Exception:
        _ledger_build = _ledger_record = _ledger_git_state = None  # ledger disabled

    _ledger_commit_before, _ledger_dirty_before = (
        _ledger_git_state() if _ledger_git_state else (None, None)
    )
    if input_meta.get("stdin"):
        _ledger_files = []
    elif input_meta.get("path"):
        _ledger_files = [input_meta["path"]]
    else:
        _ledger_files = []

    def _emit_ledger(*, output_chars: int, duration_ms: int,
                     success: bool, cache_hit: bool,
                     failure_reason: str | None,
                     result_summary: str | None,
                     usage: dict | None = None) -> None:
        if not (_ledger_build and _ledger_record):
            return
        commit_after, dirty_after = (
            _ledger_git_state() if _ledger_git_state else (None, None)
        )
        # Pull real provider tokens out of the normalized usage block when
        # present; ledger will set tokens_estimated=False automatically.
        input_tokens = None
        output_tokens = None
        cached_tokens = None
        cache_miss_tokens = None
        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            cached_tokens = usage.get("cached_tokens")
            cache_miss_tokens = usage.get("cache_miss_tokens")
        # P2-C1.0: pull per-call cost-discipline extras from env (allowlist-
        # filtered). When unset, returns {} and the record looks the same as
        # before this phase. config.profile flows into the P2-B top-level slot.
        ledger_extra = _load_ledger_extra_from_env()
        try:
            rec = _ledger_build(
                task_type=args.task,
                tool_name=args.task,
                profile=config.profile or None,
                model=config.model,
                provider=config.provider,
                base_url=config.base_url,
                input_chars=len(user),
                output_chars=output_chars,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                cache_miss_tokens=cache_miss_tokens,
                duration_ms=duration_ms,
                success=success,
                cache_hit=cache_hit,
                failure_reason=failure_reason,
                result_summary=result_summary,
                files_referenced=_ledger_files,
                git_commit_before=_ledger_commit_before,
                git_dirty_before=_ledger_dirty_before,
                git_commit_after=commit_after,
                git_dirty_after=dirty_after,
                request_id=request_id,
                extra=ledger_extra or None,
            )
            _ledger_record(rec)
        except Exception:
            pass  # ledger must never crash the call

    cache_hit = False
    cache_key, cache_warn = (None, None)
    if args.task in CACHEABLE_TASKS:
        cache_key, cache_warn = _compute_cache_key_safe(
            args.task, args.target, input_meta, args.max_files,
            config.profile, config.model,
        )
        if cache_warn:
            output.warnings.append(cache_warn)

        if cache_key:
            try:
                cached = get_cache(cache_key)
            except Exception as exc:
                cached = None
                output.warnings.append(f"cache read skipped: {exc}")
            if cached:
                cache_hit = True
                output.ok = True
                output.cache_hit = True
                output.result = cached.get("result", "")
                output.summary = cached.get("summary", "")[:500]
                output.confidence = "medium"
                # Prefer cached prompt metadata when available (older cache
                # entries from v0.9.2 may not have it).
                output.prompt_id = cached.get("prompt_id") or output.prompt_id
                output.prompt_version = cached.get("prompt_version") or output.prompt_version
                output.prompt_hash = cached.get("prompt_hash") or output.prompt_hash
                output.created_at = datetime.now(timezone.utc).isoformat()
                json_path, md_path = save_output(output, config)
                ls("cli", output.task, output.task, config.profile, config.model,
                   config.provider, 0.0, len(user), len(output.result),
                   cache_hit=True, retries=0, request_id=request_id,
                   prompt_id=output.prompt_id, prompt_version=output.prompt_version,
                   prompt_hash=output.prompt_hash)
                _emit_ledger(output_chars=len(output.result), duration_ms=0,
                             success=True, cache_hit=True,
                             failure_reason=None,
                             result_summary=output.summary)
                print(f"OK (cache hit): {args.task} completed", file=sys.stderr)
                print(f"JSON: {json_path}")
                return 0

    log_start = time.time()
    print(f"Calling {config.provider} model {config.model}...", file=sys.stderr)

    # v2-A: non-stream path returns ModelCallResult (with content + usage).
    # Stream path still yields plain str chunks; usage capture for streaming
    # is deferred to v2-B (see docs/CALL_LEDGER_V2_PLAN.md §6).
    call_usage: dict | None = None
    if config.stream:
        # Streaming mode: emit tokens as they arrive, accumulate for output
        raw_result = []
        try:
            for token in call_model_stream(system, user, config):
                raw_result.append(token)
                sys.stdout.write(f"DATA: {token}\n")
                sys.stdout.flush()
            raw_result = "".join(raw_result)
            error_info = {}
        except Exception as exc:
            raw_result = "".join(raw_result) if isinstance(raw_result, list) else ""
            error_type, suggestion = classify_error(exc, args.task)
            error_info = {"error_type": error_type, "error": str(exc)[:300],
                          "suggestion": suggestion, "retries": 0}
    else:
        result, error_info = call_model_with_retry(system, user, config, task=args.task)
        if result is not None:
            raw_result = result.content
            call_usage = result.usage
        else:
            raw_result = ""
    log_duration = time.time() - log_start

    if error_info:
        output.error = error_info.get("error", "unknown error")
        output.error_type = error_info.get("error_type", "unknown_error")
        output.suggestion = error_info.get("suggestion", "")
        output.retries = error_info.get("retries", 0)
        lf("cli", output.task, output.task, config.profile, config.model,
           config.provider, log_duration,
           output.error_type or "unknown_error",
           output.error or "unknown error",
           len(user), output.retries, request_id=request_id,
           prompt_id=output.prompt_id, prompt_version=output.prompt_version,
           prompt_hash=output.prompt_hash)
        _emit_ledger(output_chars=0, duration_ms=int(log_duration * 1000),
                     success=False, cache_hit=False,
                     failure_reason=output.error_type or output.error or "unknown_error",
                     result_summary=None)
        return _emit_failure(output, config)

    output.ok = True
    output.result = raw_result
    output.confidence = "medium"

    parsed = parse_structured(raw_result, args.task)
    output.key_files = parsed["key_files"]
    output.must_read = parsed["must_read"]
    output.risks = parsed["risks"]
    output.test_gaps = parsed["test_gaps"]
    output.uncertain_points = parsed["uncertain_points"]

    lines = raw_result.strip().split("\n")
    output.summary = lines[0][:500] if lines else ""

    json_path, md_path = save_output(output, config)

    # Write cache for cacheable tasks (best-effort).
    if args.task in CACHEABLE_TASKS and cache_key and not cache_hit:
        try:
            put_cache(cache_key, {
                "task": args.task,
                "profile": config.profile,
                "model": config.model,
                "result": raw_result,
                "summary": output.summary,
                "prompt_id": output.prompt_id,
                "prompt_version": output.prompt_version,
                "prompt_hash": output.prompt_hash,
            })
        except Exception:
            pass

    ls("cli", output.task, output.task, config.profile, config.model,
       config.provider, log_duration, len(user),
       len(raw_result), cache_hit=False, retries=0, request_id=request_id,
       prompt_id=output.prompt_id, prompt_version=output.prompt_version,
       prompt_hash=output.prompt_hash)
    _emit_ledger(output_chars=len(raw_result),
                 duration_ms=int(log_duration * 1000),
                 success=True, cache_hit=False,
                 failure_reason=None,
                 result_summary=output.summary,
                 usage=call_usage)

    print(f"OK: {args.task} completed", file=sys.stderr)
    print(f"JSON: {json_path}")
    if not config.no_markdown:
        print(f"MD:   {md_path}")

    if config.json_only:
        print(json.dumps(asdict(output), indent=2, ensure_ascii=False))

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Local LLM Worker — run a single task against a local model"
    )
    parser.add_argument("task", help="Task type (e.g., summarize-file, review-diff)")
    parser.add_argument("target", nargs="?", default=None, help="File or directory path")
    parser.add_argument("--provider", default=None, help="ollama or openai-compatible")
    parser.add_argument("--model", default=None, help="Model name override")
    parser.add_argument("--profile", default=None, help="Profile name from profiles.json")
    parser.add_argument("--base-url", default=None, help="API base URL")
    parser.add_argument("--stdin", action="store_true", help="Read input from stdin")
    parser.add_argument("--max-files", type=int, default=None, help="Max files for tree tasks")
    parser.add_argument("--max-chars", type=int, default=None, help="Max input chars")
    parser.add_argument("--max-output-chars", type=int, default=None, help="Max output chars")
    parser.add_argument("--timeout", type=int, default=None, help="API timeout seconds")
    parser.add_argument("--target-language", default=None, help="Target language for translation")
    parser.add_argument("--style", default=None, help="Style hint (concise, detailed, etc.)")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--json-only", action="store_true", help="Print JSON to stdout")
    parser.add_argument("--no-markdown", action="store_true", help="Skip Markdown output")
    parser.add_argument("--stream", action="store_true", help="Stream tokens to stdout in real time")

    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
