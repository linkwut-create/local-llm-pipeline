r"""MCP gate hook — repository-local source of truth (Phase 2A.1).

All core logic lives here so tests can import without depending on
~/.claude/hooks/mcp_gate.py. The user-level hook file is a thin wrapper
that imports this module and calls main() with a config dir.

Session boundary: SessionStart clears per-session state (mcp_calls)
so previous sessions don't contaminate the Stop hook summary.

Hook events:
- SessionStart: clear per-session MCP tracking, set session_id.
- PreToolUse:  block git commit without prior local review.
- PostToolUse: track review state, dirty flag, MCP usage.
- Stop:        advisory session summary via stderr (never blocks).
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REVIEW_TOOLS = {
    "mcp__local-llm__local_review_diff",
    "mcp__local-llm__local_debate_review_diff",
}

_DIRTY_TOOLS = {"Edit", "Write", "MultiEdit"}

_MCP_TOOLS = {
    "mcp__local-llm__local_check",
    "mcp__local-llm__local_summarize_file",
    "mcp__local-llm__local_summarize_tree",
    "mcp__local-llm__local_review_diff",
    "mcp__local-llm__local_debate_review_diff",
    "mcp__local-llm__local_generate_test_plan",
    "mcp__local-llm__local_draft_code",
    "mcp__local-llm__local_contextual_analyze",
}

_REDACT_RE = re.compile(
    r'(sk-[a-zA-Z0-9_-]{20,})'
    r'|(Bearer\s+[a-zA-Z0-9_\-\.]+)'
    r'|(api_key[=:]\s*["\']?[a-zA-Z0-9_\-]+)'
    r'|("token"\s*:\s*"[a-zA-Z0-9_\-]{10,}")'
    r'|("api_key"\s*:\s*"[a-zA-Z0-9_\-]{10,}")'
    r'|("password"\s*:\s*"[^"]+")'
    r'|("secret"\s*:\s*"[^"]+")'
)

_GIT_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}

# Fallback regex for git subcommand detection when shlex.split fails
# (e.g. PowerShell here-string @'...'@ confuses shlex quoting).
# Matches: git [optional -C/-c/--flags] <subcommand>
_GIT_SUBCMD_FALLBACK_RE = re.compile(
    r'^git\s+(?:[-]C\s+\S+\s+|[-]c\s+\S+\s+|--\S+(?:=\S+)?\s+)*'
    r'(commit|tag|push)\b'
)

# Phase MCP-GATE-1B: subprocess git commit bypass risk patterns.
# These detect when a language runtime is used to invoke git commit indirectly.
# Each entry is (pattern, description, language).
_BYPASS_RISK_PATTERNS = [
    # Python subprocess.run(['git', 'commit', ...]) — must contain git in the args
    (r"subprocess\.(?:run|call|check_call|check_output|Popen)\s*\(\s*\[[^\]]*\bgit\b[^\]]*\bcommit\b",
     "Python subprocess git commit (list form)", "python"),
    (r"subprocess\.(?:run|call|check_call|check_output|Popen)\s*\([^)]*\bgit\s+commit",
     "Python subprocess git commit (string form)", "python"),
    # Python os.system / os.popen git commit
    (r"os\.(?:system|popen)\s*\(\s*[\"'][^\"']*\bgit\s+commit",
     "Python os.system git commit", "python"),
    # Node.js: child_process.execSync('git commit ...') — dotted form
    (r"child_process[.\w]*\.(?:exec|execSync|execFile|execFileSync|spawn|spawnSync)\s*\([^)]*\bgit\s+commit",
     "Node child_process git commit (dotted form)", "node"),
    # Node.js: destructured execSync('git commit ...') — when child_process AND execSync + git commit both present
    (r"\bexec(?:Sync)?\s*\(\s*[\"'][^\"']*\bgit\s+commit",
     "Node destructured git commit", "node"),
    # Ruby system / backticks / exec
    (r"system\s*\(\s*[\"'][^\"']*git[\"']\s*,\s*[\"']commit",
     "Ruby system git commit", "ruby"),
    (r"`\s*git\s+commit",
     "Ruby backtick git commit", "ruby"),
    # Perl system / backticks / exec
    (r"system\s*\(\s*[\"'][^\"']*\bgit\s+commit",
     "Perl system git commit", "perl"),
    (r"`\s*git\s+commit.*`",
     "Perl backtick git commit", "perl"),
]

_BENIGN_OUTPUT_COMMANDS = {"echo", "printf", "Write-Output", "Write-Host"}

# Phase 2B: dangerous shell command patterns. Each entry is (pattern, description).
# Patterns use word-boundary anchors where possible.
_DANGEROUS_PATTERNS = [
    # git destructive
    (r'\bgit\s+reset\s+.*--hard', "git reset --hard (irreversible working tree reset)"),
    (r'\bgit\s+clean\s+.*-[-xfd]*[df]', "git clean -fd/-xdf (deletes untracked files)"),
    (r'\bgit\s+push\s+.*(--force|-f)\b', "git push --force (overwrites remote history)"),
    # Unix destructive (rm must appear at command start or after separator,
    # not inside quotes — avoids matching echo 'rm -rf is dangerous')
    (r'(?:^|[\s;&|]+)rm\s+-r[fw]?\s', "rm -rf (recursive force delete)"),
    # Windows cmd destructive
    (r'\bdel\s+/[fsq]', "del /s /q (recursive silent delete)"),
    (r'\brmdir\s+/s', "rmdir /s (recursive directory delete)"),
    # PowerShell destructive
    (r'Remove-Item\s+.*-Recurse\s+.*-Force', "Remove-Item -Recurse -Force (force recursive delete)"),
    (r'Remove-Item\s+.*-Force\s+.*-Recurse', "Remove-Item -Force -Recurse (force recursive delete)"),
    (r'rm\s+-r\s+-fo\b', "rm -r -fo (PowerShell force recursive delete)"),
    (r'ri\s+-r\s+-fo\b', "ri -r -fo (PowerShell Remove-Item alias)"),
]

# Phase 2C: release / tag / push patterns. Each entry is (pattern, description).
# Git tag and git push are detected by dedicated helpers (see _is_git_tag_creation,
# _is_git_push). npm/twine/release scripts use regex patterns below.
_RELEASE_PATTERNS = [
    (r'^npm\s+publish\b', "npm publish (publishes to npm registry)"),
    (r'^npm\s+run\s+release\b', "npm run release (executes release script)"),
    (r'\btwine\s+upload\b', "twine upload (publishes to PyPI)"),
    (r'\bpython\s+-m\s+twine\s+upload\b', "python -m twine upload (publishes to PyPI)"),
]

_STATE_DEFAULTS = {
    "diff_reviewed": False,
    "dirty_since_review": False,
    "touched_files": [],
    "reviewed_at": None,
    "reviewed_by": None,
    "reviewed_repo": None,
    "reviewed_head": None,
    "reviewed_diff_hash": None,
    "mcp_calls": {},
    "session_id": None,
    "session_started_at": None,
    # Phase 3E: real-time default participation
    "session_needs_local_check": True,
    "local_check_done": False,
    "needs_summarize": [],
    "needs_review": False,
    "needs_debate": False,
    "needs_test_plan": False,
    "session_recommendations": [],
    "session_large_reads": [],
    "session_touched_files": [],
    "diff_line_count": 0,
}


# ---------------------------------------------------------------------------
# public helpers (imported by tests and user-level wrapper)
# ---------------------------------------------------------------------------

def _extract_mcp_response_text(resp) -> str:
    """Extract JSON text from MCP tool_response in either format.

    MCP tools return an array of content blocks:
        [{"type": "text", "text": "{...}"}]
    Legacy tools may return a single dict:
        {"type": "text", "text": "{...}"}
    """
    if isinstance(resp, list):
        for item in resp:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text", "")
        return ""
    if isinstance(resp, dict):
        return resp.get("text", "")
    return ""


def review_tool_succeeded(payload: dict) -> bool:
    """Return True only if the MCP review tool call clearly succeeded.

    Handles both MCP array format [{"type": "text", "text": "..."}] and
    legacy dict format {"type": "text", "text": "..."}.

    Returns True when ok is truthy AND no error is present.
    Case-insensitive on error_type and keyword checks.
    """
    text = _extract_mcp_response_text(payload.get("tool_response"))
    if not text:
        return False
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(result, dict):
        return False
    # Explicit ok=false → failure
    if result.get("ok") is False:
        return False
    # Non-null error field → failure
    if result.get("error"):
        return False
    # Non-null, non-empty error_type → failure
    error_type = result.get("error_type")
    if error_type is not None and str(error_type).strip().lower() not in ("", "none", "null"):
        return False
    # Warnings containing known failure keywords → failure
    warnings = result.get("warnings", [])
    if isinstance(warnings, list):
        for w in warnings:
            w_str = str(w).lower()
            if any(kw in w_str for kw in (
                "traceback", "unicode", "decodeerror", "encodeerror",
                "can't decode", "can't encode",
            )):
                return False
    # Explicit ok=true with clean error_type → success
    if result.get("ok") is True:
        return True
    # Fall back to truthiness of ok
    return bool(result.get("ok"))


def is_git_commit(payload: dict) -> bool:
    """Detect git commit even with global options and chained commands."""
    name = payload.get("tool_name", "")
    if name not in ("Bash", "PowerShell"):
        return False
    cmd = str(payload.get("tool_input", {}).get("command", ""))
    if not re.search(r"\bgit\b", cmd) or not re.search(r"\bcommit\b", cmd):
        return False
    if "git commit-tree" in cmd:
        return False
    for sub in _split_command_chain(cmd):
        if _single_cmd_is_git_commit(sub):
            return True
    return False


def is_git_commit_bypass_risk(payload: dict) -> tuple[bool, str, str]:
    """Detect subprocess/language-based git commit bypass attempts.

    Checks if a Bash/PowerShell command uses a language runtime (python, node,
    ruby, perl) to indirectly invoke git commit. Only triggers when BOTH the
    language runtime AND a git-commit-like subprocess pattern are present.

    Returns (is_risk, description, language) or (False, "", "").
    """
    name = payload.get("tool_name", "")
    if name not in ("Bash", "PowerShell"):
        return False, "", ""
    cmd = str(payload.get("tool_input", {}).get("command", ""))

    # Must contain a language runtime invocation
    has_lang = False
    lang = ""
    if re.search(r'\bpython3?(?:\.\d+)?\b', cmd):
        has_lang = True
        lang = "python"
    elif re.search(r'\bnode\b', cmd):
        has_lang = True
        lang = "node"
    elif re.search(r'\bruby\b', cmd):
        has_lang = True
        lang = "ruby"
    elif re.search(r'\bperl\b', cmd):
        has_lang = True
        lang = "perl"

    if not has_lang:
        return False, "", ""

    # Must contain a subprocess git commit pattern
    for pattern, desc, pat_lang in _BYPASS_RISK_PATTERNS:
        if pat_lang == lang and re.search(pattern, cmd, re.IGNORECASE):
            return True, desc, lang

    return False, "", ""


def is_dangerous_command(payload: dict) -> tuple[bool, str]:
    """Check if a Bash/PowerShell command matches known dangerous patterns.

    Returns (is_dangerous, matched_description) or (False, "").
    Only checks Bash and PowerShell tool calls.

    Splits chained commands and skips benign sub-commands:
    - git commit (commit gate handles blocking; message body may contain
      dangerous-looking strings that are harmless)
    - echo, printf, Write-Output, Write-Host (output-only commands)
    """
    name = payload.get("tool_name", "")
    if name not in ("Bash", "PowerShell"):
        return False, ""
    cmd = str(payload.get("tool_input", {}).get("command", ""))

    for sub in _split_command_chain(cmd):
        # git commit sub-commands are handled by the commit gate — skip
        # dangerous pattern checking so that commit messages mentioning
        # dangerous command names (e.g. "docs: avoid git reset --hard")
        # aren't falsely blocked.
        if _single_cmd_is_git_commit(sub):
            continue
        # Benign output commands can echo/print any text safely.
        if _sub_cmd_is_benign_output(sub):
            continue
        for pattern, description in _DANGEROUS_PATTERNS:
            if re.search(pattern, sub):
                return True, description
    return False, ""


def is_release_command(payload: dict) -> tuple[bool, str]:
    """Check if a Bash/PowerShell command is a release/publish action.

    Returns (is_release, description) or (False, "").
    Only checks Bash and PowerShell tool calls.

    Splits chained commands and skips benign sub-commands:
    - git commit (commit gate handles blocking; commit message body may
      contain release-related text that is harmless)
    - echo, printf, Write-Output, Write-Host (output-only commands)

    Detects:
    - git tag creation (not listing)
    - git push (non-force; force pushes caught by dangerous guard)
    - npm publish, twine upload, release scripts
    """
    name = payload.get("tool_name", "")
    if name not in ("Bash", "PowerShell"):
        return False, ""
    cmd = str(payload.get("tool_input", {}).get("command", ""))

    for sub in _split_command_chain(cmd):
        if _single_cmd_is_git_commit(sub):
            continue
        if _sub_cmd_is_benign_output(sub):
            continue
        if _is_git_tag_creation(sub):
            return True, "git tag creation (creates a tag in the repository)"
        if _is_git_push(sub):
            return True, "git push (publishes commits/refs to remote repository)"
        for pattern, description in _RELEASE_PATTERNS:
            if re.search(pattern, sub):
                return True, description
    return False, ""


def run_git(args, cwd=None):
    """Run a git command, return stripped stdout or None on failure."""
    try:
        r = subprocess.run(
            ["git"] + args, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=10, cwd=cwd,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def get_repo_root(cwd=None):
    return run_git(["rev-parse", "--show-toplevel"], cwd=cwd)


def get_head(cwd=None):
    return run_git(["rev-parse", "HEAD"], cwd=cwd)


def get_diff_hash(cwd=None):
    """SHA256 hex of staged diff (falls back to unstaged if nothing staged)."""
    diff = run_git(["diff", "--cached"], cwd=cwd)
    if diff is None:
        return None
    if not diff:
        diff = run_git(["diff"], cwd=cwd) or ""
    return hashlib.sha256(diff.encode()).hexdigest()


def get_repo_fingerprint(cwd=None):
    """Return {repo, head, diff_hash} or None if git rev-parse fails."""
    repo = get_repo_root(cwd)
    if not repo:
        return None
    return {
        "repo": repo,
        "head": get_head(cwd),
        "diff_hash": get_diff_hash(cwd),
    }


def extract_git_c_path(cmd: str):
    """Extract the -C <path> argument from a git command, or None."""
    try:
        tokens = shlex.split(cmd, posix=False)
    except ValueError:
        return None
    tokens = [t.strip('"').strip("'") for t in tokens]
    if not tokens or tokens[0] != "git":
        return None
    i = 1
    while i < len(tokens) - 1:
        if tokens[i] == "-C":
            return tokens[i + 1]
        if tokens[i] in _GIT_ARG_OPTS:
            i += 2
        elif tokens[i].startswith("-"):
            i += 1
        else:
            break
    return None


def classify_diff_risk(diff_text: str, touched_files: list[str] | None = None) -> str:
    """Classify diff risk level: 'low', 'medium', or 'high'.

    Returns 'high' if hook/gate files or release scripts are touched,
    'medium' if >100 lines changed, 'low' otherwise.
    """
    touched = touched_files or []
    for f in touched:
        fn = f.replace("\\", "/")
        if "tools/claude_hooks/" in fn or "mcp_gate" in fn or "mcp_doctor" in fn:
            return "high"
        if "release" in fn.lower() or "publish" in fn.lower():
            return "high"

    lines = diff_text.count("\n")
    if lines > 100:
        return "medium"
    return "low"


def recommend_mcp_action(risk: str, touched_files: list[str] | None = None,
                         diff_text: str = "") -> list[str]:
    """Return recommended MCP actions based on risk level and file types.

    Never returns empty — always recommends at least local_review_diff.
    """
    touched = touched_files or []
    nt = [f.replace("\\", "/") for f in touched]
    actions = []

    has_tests = any("tests/" in f or f.endswith("_test.py") for f in nt)
    has_docs_only = all("docs/" in f or f.endswith(".md") for f in nt) if nt else False
    has_hook_files = any("tools/claude_hooks/" in f or "mcp_gate" in f for f in nt)

    if risk == "high" or has_hook_files:
        actions.append("local_debate_review_diff")
    if has_tests:
        actions.append("local_generate_test_plan")
    if has_docs_only:
        actions.append("local_summarize_file")

    # Always include review
    if "local_debate_review_diff" not in actions:
        actions.append("local_review_diff")

    return actions


def _extract_read_info(payload: dict) -> tuple[str | None, int | None]:
    """Extract (file_path, num_lines) from a Read tool PostToolUse payload.

    Handles multiple response formats:
    - {"type":"text","text":"..."}
    - [{"type":"text","text":"..."}]
    - {"type":"text","file":{"filePath":"...","content":"...","numLines":N}}
    - {"file":{"content":"...","numLines":N}}
    Returns (file_path, num_lines) where num_lines may be None if unknown.
    """
    resp = payload.get("tool_response", {})
    file_path = str(payload.get("tool_input", {}).get("file_path", ""))

    num_lines = None
    content = ""

    # Normalize to a flat dict if it's a list (MCP array format)
    if isinstance(resp, list):
        for item in resp:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    content = item.get("text", "")
                    # Also check for nested file info
                    if "file" in item:
                        fi = item["file"]
                        if isinstance(fi, dict):
                            file_path = fi.get("filePath", file_path)
                            if "numLines" in fi:
                                num_lines = fi["numLines"]
                            if not content:
                                content = fi.get("content", "")
                    break
    elif isinstance(resp, dict):
        # Check for file wrapper
        if "file" in resp:
            fi = resp["file"]
            if isinstance(fi, dict):
                file_path = fi.get("filePath", file_path)
                if "numLines" in fi:
                    num_lines = fi["numLines"]
                content = fi.get("content", content)
        if "text" in resp and not content:
            content = resp.get("text", "")

    # Compute num_lines from content if not explicitly provided
    if num_lines is None and content:
        num_lines = content.count("\n")

    return file_path if file_path else None, num_lines


def tool_name(payload: dict) -> str:
    return payload.get("tool_name", "")


# ---------------------------------------------------------------------------
# state file helpers
# ---------------------------------------------------------------------------

def _state_file_path(config_dir: str) -> Path:
    return Path(config_dir) / "state.json"


def _log_file_path(config_dir: str) -> Path:
    return Path(config_dir) / "hook-events.jsonl"


def load_state(config_dir: str) -> dict:
    state = dict(_STATE_DEFAULTS)
    try:
        sf = _state_file_path(config_dir)
        if sf.exists():
            raw = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state.update(raw)
    except Exception:
        pass
    return state


def save_state(config_dir: str, state: dict):
    try:
        _state_file_path(config_dir).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB


def _rotate_log(log_path: Path):
    """Archive oversized log file to .mcp_audit/archive/ with timestamp."""
    try:
        archive_dir = log_path.parent / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"hook-events-{ts}.jsonl"
        log_path.rename(archive_dir / archive_name)
    except Exception:
        pass

def log_event(config_dir: str, payload: dict):
    try:
        log_path = _log_file_path(config_dir)
        if log_path.exists() and log_path.stat().st_size > MAX_LOG_SIZE:
            _rotate_log(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# MCP-GATE-1B: per-repo state isolation
# ---------------------------------------------------------------------------

def _repo_state_key(repo_root: str) -> str:
    """Stable short key derived from repo root path."""
    return hashlib.sha256(repo_root.encode()).hexdigest()[:12]


# Fields that are per-repo (saved/restored on repo switch)
_REPO_SCOPED_FIELDS = [
    "diff_reviewed", "dirty_since_review", "touched_files",
    "reviewed_at", "reviewed_by", "reviewed_repo", "reviewed_head",
    "reviewed_diff_hash",
    # Phase 2C: release guard per-repo state
    "debate_reviewed", "debate_head", "dirty_since_debate", "debate_completed_at",
]


def _ensure_repo_state(state: dict, repo_root: str):
    """Swap flat state fields to/from per-repo storage when repo changes.

    The flat top-level fields always reflect the CURRENT active repo.
    On repo change, the current flat values are saved to the old repo's
    per-repo store, and the new repo's values are loaded into flat fields.
    On first access to a new repo, it starts with clean defaults.
    On very first call (no prior active repo), the current flat state is
    preserved as the initial state for that repo.
    """
    if not repo_root:
        return
    if "repos" not in state:
        state["repos"] = {}
    key = _repo_state_key(repo_root)
    current_repo = state.get("_active_repo_key")

    if current_repo == key:
        return  # Same repo, no swap needed

    # Save current flat state to old repo's per-repo storage
    if current_repo:
        entry = state["repos"].setdefault(current_repo, {"repo_root": ""})
        for field in _REPO_SCOPED_FIELDS:
            entry[field] = state.get(field)
    else:
        # Very first call: persist current flat state as initial state for this repo
        state["repos"][key] = {
            "repo_root": repo_root,
            "diff_reviewed": state.get("diff_reviewed", False),
            "dirty_since_review": state.get("dirty_since_review", False),
            "touched_files": list(state.get("touched_files", [])),
            "reviewed_at": state.get("reviewed_at"),
            "reviewed_by": state.get("reviewed_by"),
            "reviewed_repo": state.get("reviewed_repo"),
            "reviewed_head": state.get("reviewed_head"),
            "reviewed_diff_hash": state.get("reviewed_diff_hash"),
        }
        state["_active_repo_key"] = key
        return  # Don't overwrite flat fields — keep what's already there

    # Load new repo's state (or use defaults for first access)
    if key in state["repos"]:
        for field in _REPO_SCOPED_FIELDS:
            state[field] = state["repos"][key].get(field, _STATE_DEFAULTS.get(field))
    else:
        # First time accessing this repo after a swap: use clean defaults
        state["repos"][key] = {"repo_root": repo_root}
        for field in _REPO_SCOPED_FIELDS:
            state[field] = _STATE_DEFAULTS.get(field)

    state["_active_repo_key"] = key


# ---------------------------------------------------------------------------
# MCP-GATE-1B: audit logger integration (best-effort)
# ---------------------------------------------------------------------------

def _try_audit_event(event: dict):
    """Write an audit event via mcp_audit_logger if available. Never raises."""
    try:
        from mcp_audit_logger import write_audit_event
        write_audit_event(None, event)
    except Exception:
        pass


def _try_audit_failure(failure: dict):
    """Write an audit failure via mcp_audit_logger if available. Never raises."""
    try:
        from mcp_audit_logger import write_failure_event
        write_failure_event(None, failure)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# per-session state helpers
# ---------------------------------------------------------------------------

def _check_release_prerequisites(config_dir: str, cwd: str = "") -> tuple[bool, str]:
    """Check if release prerequisites are met for the current HEAD.

    Release requires:
    1. local_debate_review_diff completed on current HEAD
    2. No dirty files since debate review

    Returns (ok, reason_description).
    """
    state = load_state(config_dir)
    repo_root = get_repo_root(cwd) if cwd else None
    if repo_root:
        _ensure_repo_state(state, repo_root)

    # Check debate review completed on current HEAD (flat state managed by _ensure_repo_state)
    debate_done = state.get("debate_reviewed", False)
    debate_head = state.get("debate_head", "")
    current_head = get_head(cwd) if cwd else None

    if not debate_done or not debate_head:
        return False, "debate review not completed on this HEAD"
    if current_head and debate_head != current_head:
        return False, f"debate review was on HEAD {debate_head[:8]}, current HEAD is {current_head[:8]}"

    # Check no dirty files since debate review
    if state.get("dirty_since_debate", False):
        return False, "files have been modified since debate review — re-run debate review"

    return True, f"debate review completed on {debate_head[:12]}"


def _ensure_session(config_dir: str):
    """If no session is active, create one (clear mcp_calls, set session_id)."""
    state = load_state(config_dir)
    if not state.get("session_id"):
        state["session_id"] = uuid.uuid4().hex[:12]
        state["session_started_at"] = datetime.now(timezone.utc).isoformat()
        state["mcp_calls"] = {"_last_mcp_failed": False}
        save_state(config_dir, state)


def _clear_session(config_dir: str):
    """Start a fresh session: new id, clear per-session tracking."""
    state = load_state(config_dir)
    # Keep persistent fields (commit gate state crosses sessions)
    # Clear only per-session MCP tracking
    state["session_id"] = uuid.uuid4().hex[:12]
    state["session_started_at"] = datetime.now(timezone.utc).isoformat()
    state["mcp_calls"] = {"_last_mcp_failed": False}
    state["touched_files"] = []
    state["session_needs_local_check"] = True
    state["local_check_done"] = False
    state["needs_summarize"] = []
    state["needs_review"] = False
    state["needs_debate"] = False
    state["needs_test_plan"] = False
    state["session_recommendations"] = []
    state["session_large_reads"] = []
    state["session_touched_files"] = []
    state["diff_line_count"] = 0
    save_state(config_dir, state)


# ---------------------------------------------------------------------------
# hook event handlers
# ---------------------------------------------------------------------------

def _get_diff_line_count(cwd: str | None = None) -> int:
    """Return total changed lines from git diff --numstat, or 0 on failure."""
    try:
        output = run_git(["diff", "--numstat"], cwd=cwd)
        if not output:
            return 0
        total = 0
        for line in output.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 2:
                added = int(parts[0]) if parts[0] not in ("-", "") else 0
                removed = int(parts[1]) if parts[1] not in ("-", "") else 0
                total += added + removed
        return total
    except Exception:
        return 0


def _add_recommendation(state: dict, rec: str):
    """Add a recommendation to the session accumulator, avoiding duplicates."""
    recs = state.get("session_recommendations", [])
    if rec not in recs:
        recs.append(rec)
    state["session_recommendations"] = recs


def handle_post_tooluse(config_dir: str, payload: dict):
    """Track review state, dirty flag, MCP tool usage, and Phase 3E real-time participation."""
    _ensure_session(config_dir)
    name = tool_name(payload)

    # --- Review tools ---
    if name in _REVIEW_TOOLS:
        state = load_state(config_dir)
        cwd = payload.get("cwd", "")
        fp = get_repo_fingerprint(cwd=cwd) if cwd else None
        repo_root = fp["repo"] if fp else cwd or None
        if repo_root:
            _ensure_repo_state(state, repo_root)

        if review_tool_succeeded(payload):
            state["diff_reviewed"] = True
            state["dirty_since_review"] = False
            state["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            state["reviewed_by"] = name
            state["reviewed_repo"] = fp["repo"] if fp else None
            state["reviewed_head"] = fp["head"] if fp else None
            state["reviewed_diff_hash"] = fp["diff_hash"] if fp else None
            state.pop("last_review_error", None)
            # Phase 3E: clear review/debate recommendations on success
            if name == "mcp__local-llm__local_debate_review_diff":
                state["needs_debate"] = False
                # Phase 2C: track debate completion for release guard (flat state)
                state["debate_reviewed"] = True
                state["debate_head"] = fp["head"] if fp else None
                state["dirty_since_debate"] = False
                state["debate_completed_at"] = datetime.now(timezone.utc).isoformat()
            state["needs_review"] = False
            # Persist per-repo state on save
            if repo_root:
                _ensure_repo_state(state, repo_root)
            save_state(config_dir, state)
        else:
            state["diff_reviewed"] = False
            if repo_root:
                _ensure_repo_state(state, repo_root)
            state["last_review_error"] = datetime.now(timezone.utc).isoformat()
            save_state(config_dir, state)

    # --- Dirty tools (Edit/Write/MultiEdit) ---
    if name in _DIRTY_TOOLS:
        target = str(payload.get("tool_input", {}).get("file_path", ""))
        if "mcp-gate" not in target and ".claude/hooks" not in target and ".local_llm_out" not in target:
            state = load_state(config_dir)
            cwd = payload.get("cwd", "")
            repo_root = get_repo_root(cwd) if cwd else None
            if repo_root:
                _ensure_repo_state(state, repo_root)
            state["dirty_since_review"] = True
            state["needs_review"] = True
            # Phase 2C: also mark dirty since debate for release guard (flat state)
            state["dirty_since_debate"] = True
            if "touched_files" not in state:
                state["touched_files"] = []
            if target and target not in state["touched_files"]:
                state["touched_files"].append(target)
            if target and target not in state.get("session_touched_files", []):
                stf = state.get("session_touched_files", [])
                stf.append(target)
                state["session_touched_files"] = stf
            # Phase 3E: real-time risk classification
            norm = target.replace("\\", "/")
            if "tools/claude_hooks/" in norm or "mcp_gate" in norm or "mcp_doctor" in norm:
                state["needs_debate"] = True
                _add_recommendation(state, "local_debate_review_diff")
            elif "tests/" in norm or norm.endswith("_test.py"):
                state["needs_test_plan"] = True
                _add_recommendation(state, "local_generate_test_plan")
                _add_recommendation(state, "local_review_diff")
            else:
                _add_recommendation(state, "local_review_diff")

            # Phase 3E.1: real-time diff_line_count
            try:
                cwd = payload.get("cwd", "") or None
                dlc = _get_diff_line_count(cwd=cwd)
                state["diff_line_count"] = dlc
                if dlc > 100:
                    state["needs_debate"] = True
                    _add_recommendation(state, "local_debate_review_diff")
            except Exception:
                pass
            save_state(config_dir, state)

    # --- Read tool: large-file detection (Phase 3E.1: fixed parsing) ---
    if name == "Read":
        file_path, num_lines = _extract_read_info(payload)
        if file_path and num_lines is not None and num_lines > 300:
            state = load_state(config_dir)
            needs = state.get("needs_summarize", [])
            if file_path not in needs:
                needs.append(file_path)
            state["needs_summarize"] = needs
            if file_path not in state.get("session_large_reads", []):
                lr = state.get("session_large_reads", [])
                lr.append(file_path)
                state["session_large_reads"] = lr
            _add_recommendation(state, "local_summarize_file")
            save_state(config_dir, state)

    # --- MCP tools: track calls and clear recommendations on success ---
    if name in _MCP_TOOLS:
        state = load_state(config_dir)
        mcp_calls = state.get("mcp_calls", {})
        mcp_calls[name] = True
        mcp_calls["_last_mcp_ts"] = datetime.now(timezone.utc).isoformat()
        if not review_tool_succeeded(payload):
            mcp_calls["_last_mcp_failed"] = True
            mcp_calls["_last_mcp_error_ts"] = datetime.now(timezone.utc).isoformat()
        else:
            mcp_calls["_last_mcp_failed"] = False
            mcp_calls.pop("_last_mcp_error_ts", None)
            # Phase 3E: clear specific recommendations on MCP success
            if name == "mcp__local-llm__local_check":
                state["session_needs_local_check"] = False
                state["local_check_done"] = True
            elif name == "mcp__local-llm__local_summarize_file":
                state["needs_summarize"] = []
            elif name == "mcp__local-llm__local_generate_test_plan":
                state["needs_test_plan"] = False
        state["mcp_calls"] = mcp_calls
        save_state(config_dir, state)


def handle_pre_tooluse(config_dir: str, payload: dict) -> dict:
    """Check dangerous commands and commit gate. Returns {"allow": bool, "reason": str}."""
    _ensure_session(config_dir)

    # Phase 2B: dangerous command guard (runs before all other checks)
    is_dangerous, danger_desc = is_dangerous_command(payload)
    if is_dangerous:
        cmd = str(payload.get("tool_input", {}).get("command", ""))
        return {
            "allow": False,
            "reason": (
                f"BLOCKED: dangerous command detected ({danger_desc}).\n"
                f"Command: {cmd[:200]}\n"
                "If you intentionally need this, run it manually in a terminal."
            ),
        }

    # Phase 2C: release / tag / push guard (runs after dangerous, before commit gate)
    is_release, release_desc = is_release_command(payload)
    if is_release:
        cmd = str(payload.get("tool_input", {}).get("command", ""))
        cwd = payload.get("cwd", "")
        release_ok, release_reason = _check_release_prerequisites(config_dir, cwd)
        if not release_ok:
            return {
                "allow": False,
                "reason": (
                    f"BLOCKED: release/publish command detected ({release_desc}).\n"
                    f"Command: {cmd[:200]}\n"
                    f"Missing prerequisite: {release_reason}\n"
                    "Required before release:\n"
                    "  1. local_debate_review_diff (full 3-round) on current HEAD\n"
                    "  2. release_auditor review passed\n"
                    "  3. No dirty files since debate review\n"
                    "If you have met all prerequisites, re-run the command."
                ),
            }
        # Prerequisites met — allow the release
        print(f"\nRelease guard: prerequisites met ({release_reason}). Allowing {release_desc}.", file=sys.stderr)

    # --- MCP-GATE-1B: bypass risk detection (runs before normal commit gate) ---
    is_bypass, bypass_desc, bypass_lang = is_git_commit_bypass_risk(payload)
    if is_bypass:
        cmd = str(payload.get("tool_input", {}).get("command", ""))
        cwd = payload.get("cwd", "")
        repo_root = get_repo_root(cwd) if cwd else None

        # Record bypass risk to audit logger
        _try_audit_event({
            "event_type": "gate_subprocess_bypass",
            "task_type": "gate_boundary_audit",
            "tool_name": "commit_gate",
            "project_name": Path(repo_root).name if repo_root else "unknown",
            "project_path": repo_root,
            "command": cmd[:500],
            "gate_detected": True,
            "bypass_method": f"subprocess_{bypass_lang}",
            "bypass_detail": bypass_desc,
            "interception_boundary": (
                f"Detected {bypass_lang} subprocess git commit pattern. "
                "Commit via language runtime subprocess is blocked."
            ),
            "result_status": "blocked",
            "blocking": True,
            "severity": "high",
        })
        _try_audit_failure({
            "failure_type": "gate_subprocess_bypass",
            "severity": "high",
            "tool_name": "commit_gate",
            "project_name": Path(repo_root).name if repo_root else "unknown",
            "project_path": repo_root,
            "command": cmd[:500],
            "stderr_summary": f"Blocked: {bypass_desc}",
            "possible_causes": [
                f"git commit invoked via {bypass_lang} subprocess",
                "Direct Bash/PowerShell git commit is required",
            ],
            "resolved": False,
        })

        return {
            "allow": False,
            "reason": (
                f"BLOCKED: git commit via {bypass_lang} subprocess detected ({bypass_desc}).\n"
                f"Use a direct 'git commit' command via Bash or PowerShell.\n"
                f"Command: {cmd[:200]}\n"
                "This block is recorded in MCP audit log."
            ),
        }

    # --- Normal commit gate ---
    if is_git_commit(payload):
        state = load_state(config_dir)
        cmd = str(payload.get("tool_input", {}).get("command", ""))
        c_path = extract_git_c_path(cmd)
        target_cwd = c_path or payload.get("cwd", "")
        fp = get_repo_fingerprint(cwd=target_cwd) if target_cwd else None
        repo_root = fp["repo"] if fp else None
        project_name = Path(repo_root).name if repo_root else "unknown"

        # Sync flat state with per-repo storage for this repo
        if repo_root:
            _ensure_repo_state(state, repo_root)

        # Use flat state fields (now swapped to current repo)
        reviewed_ok = (
            state.get("diff_reviewed")
            and not state.get("dirty_since_review")
            and fp is not None
            and state.get("reviewed_repo") == fp["repo"]
            and state.get("reviewed_head") == fp["head"]
            and state.get("reviewed_diff_hash") == fp["diff_hash"]
        )

        if reviewed_ok:
            return {"allow": True, "reason": ""}
        else:
            parts = [
                "BLOCKED: git commit requires prior local model review.",
                "Call mcp__local-llm__local_review_diff with commit_gate=true.",
            ]
            mismatch_type = None
            if state.get("diff_reviewed"):
                if state.get("dirty_since_review"):
                    parts.append("Reason: files modified after review.")
                    mismatch_type = "dirty_since_review"
                elif fp is None:
                    parts.append("Reason: cannot determine current repo/HEAD.")
                elif state.get("reviewed_repo") != fp["repo"]:
                    parts.append(
                        f"Reason: review was for {state.get('reviewed_repo')}, "
                        f"current is {fp['repo']}."
                    )
                    mismatch_type = "repo_mismatch"
                elif state.get("reviewed_head") != fp["head"]:
                    parts.append("Reason: HEAD has changed since review.")
                    mismatch_type = "head_mismatch"
                elif state.get("reviewed_diff_hash") != fp["diff_hash"]:
                    parts.append("Reason: staged diff has changed since review.")
                    mismatch_type = "diff_hash_mismatch"
                else:
                    parts.append("Reason: review state mismatch.")
            parts.append(
                f"State: diff_reviewed={state.get('diff_reviewed')}, "
                f"dirty_since_review={state.get('dirty_since_review')}"
            )
            # Phase 3E.1: list pending MCP recommendations
            pending = []
            if state.get("needs_review"):
                pending.append("local_review_diff")
            if state.get("needs_debate"):
                pending.append("local_debate_review_diff")
            if state.get("needs_test_plan"):
                pending.append("local_generate_test_plan")
            if state.get("needs_summarize"):
                pending.append("local_summarize_file")
            if pending:
                parts.append(f"MCP pending recommendations: {', '.join(pending)}")

            # MCP-GATE-1B: write audit events for blocked commit
            audit_reason = "\n".join(parts)
            _try_audit_event({
                "event_type": "commit_gate_blocked",
                "task_type": "commit_gate",
                "tool_name": "commit_gate",
                "project_name": project_name,
                "project_path": repo_root,
                "command": cmd[:500],
                "result_status": "blocked",
                "blocking": True,
                "output_summary": audit_reason[:500],
                "commit_before": fp["head"] if fp else None,
                "staged_diff_hash": fp["diff_hash"] if fp else None,
                "reviewed_diff_hash": state.get("reviewed_diff_hash"),
                "hook_state_summary": json.dumps({
                    "reviewed_repo": state.get("reviewed_repo"),
                    "current_repo": fp["repo"] if fp else None,
                    "reviewed_head": state.get("reviewed_head"),
                    "current_head": fp["head"] if fp else None,
                    "dirty_since_review": state.get("dirty_since_review"),
                    "diff_reviewed": state.get("diff_reviewed"),
                }),
                "notes": f"Mismatch type: {mismatch_type}" if mismatch_type else "",
            })

            if mismatch_type in ("repo_mismatch", "head_mismatch"):
                _try_audit_failure({
                    "failure_type": "hook_state_mismatch",
                    "severity": "high",
                    "tool_name": "commit_gate",
                    "project_name": project_name,
                    "project_path": repo_root,
                    "command": cmd[:500],
                    "hook_state_summary": json.dumps({
                        "reviewed_repo": state.get("reviewed_repo"),
                        "current_repo": fp["repo"] if fp else None,
                        "reviewed_head": state.get("reviewed_head"),
                        "current_head": fp["head"] if fp else None,
                    }),
                    "resolved": False,
                })
            elif mismatch_type == "diff_hash_mismatch":
                _try_audit_failure({
                    "failure_type": "staged_diff_hash_mismatch",
                    "severity": "high",
                    "tool_name": "commit_gate",
                    "project_name": project_name,
                    "project_path": repo_root,
                    "staged_diff_hash": fp["diff_hash"] if fp else None,
                    "reviewed_diff_hash": state.get("reviewed_diff_hash"),
                    "resolved": False,
                })

            return {"allow": False, "reason": "\n".join(parts)}
    return {"allow": True, "reason": ""}


def handle_stop(config_dir: str, payload: dict) -> list:
    """Stop hook: return list of reminder strings. Never blocks.

    Returns empty list if nothing to report.
    """
    state = load_state(config_dir)
    cwd = payload.get("cwd", "")
    mcp_calls = state.get("mcp_calls", {})
    reminders = []

    # Phase 3E: session_needs_local_check
    if state.get("session_needs_local_check") and not mcp_calls.get("mcp__local-llm__local_check"):
        reminders.append("Task start: local_check recommended (not yet called this session).")

    # MCP tool usage
    if not mcp_calls.get("mcp__local-llm__local_check"):
        reminders.append("local_check was not called this session.")

    has_review = (
        mcp_calls.get("mcp__local-llm__local_review_diff")
        or mcp_calls.get("mcp__local-llm__local_debate_review_diff")
    )
    if not has_review:
        reminders.append("No local_review_diff or local_debate_review_diff called this session.")

    has_summarize = (
        mcp_calls.get("mcp__local-llm__local_summarize_file")
        or mcp_calls.get("mcp__local-llm__local_summarize_tree")
    )
    if not has_summarize:
        reminders.append("No local_summarize_file/tree called this session.")

    # Failed MCP
    if mcp_calls.get("_last_mcp_failed"):
        reminders.append("WARNING: at least one MCP call failed this session. "
                         "Do not commit without a successful review.")

    # Review failure
    if state.get("last_review_error") and not state.get("diff_reviewed"):
        reminders.append("Last MCP review FAILED (not marked as reviewed).")

    # Git tree state
    if cwd:
        dirty_output = run_git(["status", "--short"], cwd=cwd)
        if dirty_output:
            dirty_files = dirty_output.strip().split("\n")
            reminders.append(f"Working tree dirty ({len(dirty_files)} file(s)):")
            for f in dirty_files[:10]:
                reminders.append(f"  {f}")
            if len(dirty_files) > 10:
                reminders.append(f"  ... and {len(dirty_files) - 10} more")
            if not state.get("diff_reviewed"):
                reminders.append("REMINDER: dirty tree without successful "
                                 "local_review_diff. Run review before commit.")
            elif state.get("dirty_since_review"):
                reminders.append("REMINDER: files modified after last review. "
                                 "Re-run review before commit.")

        staged = run_git(["diff", "--cached", "--stat"], cwd=cwd)
        if staged:
            reminders.append("Staged changes exist — remember to re-review "
                             "staged diff before commit.")

        # Phase 3A/3B: risk-based MCP routing recommendations
        diff_text = run_git(["diff"], cwd=cwd) or ""
        touched = state.get("touched_files", [])
        if touched or diff_text:
            risk = classify_diff_risk(diff_text, touched)
            actions = recommend_mcp_action(risk, touched, diff_text)
            risk_label = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(risk, risk)
            reminders.append(
                f"Risk: {risk_label}. Recommended MCP: {', '.join(actions)}."
            )
            if "local_debate_review_diff" in actions and not mcp_calls.get("mcp__local-llm__local_debate_review_diff"):
                reminders.append("Debate review recommended but not yet called this session.")
            if "local_generate_test_plan" in actions and not mcp_calls.get("mcp__local-llm__local_generate_test_plan"):
                reminders.append("Test plan recommended but not yet called this session.")

        # Phase 3E: real-time participation flags
        if state.get("needs_review") and not state.get("diff_reviewed"):
            reminders.append("ACTIVE: needs_review — files were edited, run local_review_diff.")
        if state.get("needs_debate") and not mcp_calls.get("mcp__local-llm__local_debate_review_diff"):
            reminders.append("ACTIVE: needs_debate — high-risk files touched, run local_debate_review_diff.")
        if state.get("needs_test_plan") and not mcp_calls.get("mcp__local-llm__local_generate_test_plan"):
            reminders.append("ACTIVE: needs_test_plan — test files modified, run local_generate_test_plan.")
        if state.get("needs_summarize"):
            reminders.append(f"ACTIVE: needs_summarize — {len(state['needs_summarize'])} large file(s) read, run local_summarize_file.")
        if state.get("session_large_reads"):
            reminders.append(f"Large files read this session: {', '.join(state['session_large_reads'][:5])}")

    # Phase 3E: accumulated session recommendations
    recs = state.get("session_recommendations", [])
    if recs:
        reminders.append(f"Session recommendations: {', '.join(recs)}")

    return reminders


def handle_session_start(config_dir: str, payload: dict):
    """Start a fresh session, clearing per-session MCP tracking.

    v0.9.6: Runs a quick self-diagnostic (doctor lite) and reports
    issues to stderr. Non-blocking — never prevents session start.
    """
    _clear_session(config_dir)
    _run_doctor_lite(config_dir)


def _run_doctor_lite(config_dir: str):
    """Quick self-diagnostic at session start. Reports issues to stderr.

    Checks: state file health, hook log size, state file corruption.
    Never blocks — all failures are reported as warnings only.
    """
    issues = []

    # 1. Check state file is valid JSON
    state_path = Path(config_dir) / "state.json"
    if state_path.exists():
        try:
            state_size = state_path.stat().st_size
            data = json.loads(state_path.read_text(encoding="utf-8"))
            # Check for stale session data (>24h old)
            started = data.get("session_started_at", "")
            if started:
                try:
                    started_dt = datetime.fromisoformat(started)
                    age_h = (datetime.now(timezone.utc) - started_dt).total_seconds() / 3600
                    if age_h > 24:
                        issues.append(f"previous session was {age_h:.0f}h ago — state may be stale")
                except ValueError:
                    pass
            # Check for unusually large state (>1MB suggests unbounded growth)
            if state_size > 1_000_000:
                issues.append(f"state.json is {state_size / 1_000_000:.1f}MB — may need cleanup")
        except (json.JSONDecodeError, OSError) as e:
            issues.append(f"state.json is corrupted: {e} — run mcp_doctor.py --fix")
    else:
        issues.append("state.json not found — will be created on first write")

    # 2. Check hook log size
    for log_name in ["hook-events.jsonl", "hook-errors.log"]:
        log_path = Path(config_dir) / log_name
        if log_path.exists():
            try:
                log_size = log_path.stat().st_size
                if log_size > 10_000_000:
                    issues.append(f"{log_name} is {log_size / 1_000_000:.1f}MB — consider rotating")
            except OSError:
                pass

    # 3. Report issues to stderr
    if issues:
        sys.stderr.write("\n=== MCP Doctor Lite (SessionStart) ===\n")
        for i, issue in enumerate(issues, 1):
            sys.stderr.write(f"  [{i}] {issue}\n")
        sys.stderr.write("======================================\n\n")


# ---------------------------------------------------------------------------
# main entry point (for user-level wrapper)
# ---------------------------------------------------------------------------

def _redact(text: str) -> str:
    return _REDACT_RE.sub("***REDACTED***", text)


def _redact_recursive(obj):
    if isinstance(obj, dict):
        return {k: _redact_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_recursive(v) for v in obj]
    if isinstance(obj, str):
        return _redact(obj)
    return obj


def main(config_dir: str):
    """Main hook entry point. Reads payload from stdin, executes, writes result.

    config_dir: directory for state.json and hook-events.jsonl.
    """
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not raw.strip():
            sys.exit(0)
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    if not isinstance(payload, dict):
        sys.exit(0)

    payload["_audit_ts"] = datetime.now(timezone.utc).isoformat()
    log_event(config_dir, _redact_recursive(dict(payload)))

    event = payload.get("hook_event_name", "")

    if event == "SessionStart":
        handle_session_start(config_dir, payload)

    elif event == "PostToolUse":
        handle_post_tooluse(config_dir, payload)

    elif event == "PreToolUse":
        result = handle_pre_tooluse(config_dir, payload)
        if not result["allow"]:
            sys.stdout.write(json.dumps({
                "continue": False,
                "decision": "block",
                "reason": result["reason"],
            }))
            sys.stdout.flush()
            sys.exit(1)

    elif event == "Stop":
        reminders = handle_stop(config_dir, payload)
        if reminders:
            summary = "=== MCP Session Summary ===\n" + "\n".join(f"  {r}" for r in reminders)
            try:
                sys.stderr.write(summary + "\n")
                sys.stderr.flush()
            except Exception:
                pass

        # Build structured action_items for machine-readable MCP recommendations
        state = load_state(config_dir)
        mcp_calls = state.get("mcp_calls", {})
        cwd = payload.get("cwd", "")
        action_items = []

        if state.get("session_needs_local_check") and not mcp_calls.get("mcp__local-llm__local_check"):
            action_items.append({"tool": "local_check", "reason": "not yet called this session"})

        if state.get("needs_review") and not state.get("diff_reviewed"):
            action_items.append({"tool": "local_review_diff", "reason": "files edited, diff not reviewed"})

        if state.get("needs_debate") and not mcp_calls.get("mcp__local-llm__local_debate_review_diff"):
            action_items.append({"tool": "local_debate_review_diff", "reason": "high-risk files touched"})

        if state.get("needs_test_plan") and not mcp_calls.get("mcp__local-llm__local_generate_test_plan"):
            action_items.append({"tool": "local_generate_test_plan", "reason": "test files modified"})

        needs_summ = state.get("needs_summarize", [])
        if needs_summ and not mcp_calls.get("mcp__local-llm__local_summarize_file"):
            action_items.append({
                "tool": "local_summarize_file",
                "reason": f"{len(needs_summ)} large file(s) read without summarization",
                "files": needs_summ[:5],
            })

        if cwd:
            diff_text = run_git(["diff"], cwd=cwd) or ""
            touched = state.get("touched_files", [])
            if touched or diff_text:
                risk = classify_diff_risk(diff_text, touched)
                if risk == "high":
                    action_items.append({
                        "tool": "local_debate_review_diff",
                        "reason": f"diff classified as HIGH risk",
                        "risk": risk,
                    })

        if action_items:
            try:
                sys.stderr.write(
                    "\n" + json.dumps({"action_items": action_items}, ensure_ascii=False) + "\n"
                )
                sys.stderr.flush()
            except Exception:
                pass

    sys.stdout.write(json.dumps({"continue": True}))
    sys.stdout.flush()
    sys.exit(0)


# ---------------------------------------------------------------------------
# internal helpers (not exported)
# ---------------------------------------------------------------------------

def _split_command_chain(cmd: str):
    parts = []
    current = []
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == '"':
            current.append(ch)
            i += 1
            while i < n and cmd[i] != '"':
                current.append(cmd[i])
                i += 1
            if i < n:
                current.append(cmd[i])
            i += 1
        elif ch == "'":
            current.append(ch)
            i += 1
            while i < n and cmd[i] != "'":
                current.append(cmd[i])
                i += 1
            if i < n:
                current.append(cmd[i])
            i += 1
        elif cmd[i:i + 2] == "&&":
            parts.append("".join(current).strip())
            current = []
            i += 2
        elif cmd[i:i + 2] == "||":
            parts.append("".join(current).strip())
            current = []
            i += 2
        elif ch == ";":
            parts.append("".join(current).strip())
            current = []
            i += 1
        else:
            current.append(ch)
            i += 1
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _single_cmd_is_git_commit(cmd: str) -> bool:
    try:
        raw_tokens = shlex.split(cmd, posix=False)
    except ValueError:
        # Fallback for shlex-unparseable input (e.g. PowerShell here-strings)
        m = _GIT_SUBCMD_FALLBACK_RE.match(cmd.strip())
        return bool(m and m.group(1) == "commit" and "commit-tree" not in cmd)
    tokens = [t.strip('"').strip("'") for t in raw_tokens]
    if not tokens or tokens[0] != "git":
        return False
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in _GIT_ARG_OPTS:
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            break
    return i < len(tokens) and tokens[i] == "commit"


def _sub_cmd_is_benign_output(cmd: str) -> bool:
    """Return True if the command is an output-only command like echo."""
    try:
        tokens = shlex.split(cmd, posix=False)
    except ValueError:
        return False
    if not tokens:
        return False
    base = tokens[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base in _BENIGN_OUTPUT_COMMANDS


def _get_git_subcommand(cmd: str) -> str | None:
    """Extract the git subcommand name, skipping global options.

    Returns the subcommand (e.g. "tag", "push", "commit") or None if
    the command is not a git invocation or parsing fails.
    """
    try:
        raw_tokens = shlex.split(cmd, posix=False)
    except ValueError:
        # Fallback for shlex-unparseable input (e.g. PowerShell here-strings)
        m = _GIT_SUBCMD_FALLBACK_RE.match(cmd.strip())
        return m.group(1) if m else None
    tokens = [t.strip('"').strip("'") for t in raw_tokens]
    if not tokens or tokens[0] != "git":
        return None
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in _GIT_ARG_OPTS:
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            break
    return tokens[i] if i < len(tokens) else None


def _is_git_tag_creation(cmd: str) -> bool:
    """Return True if cmd creates a git tag (not listing).

    git tag / git tag -l / git tag --list => False (listing)
    git tag v0.1.0 / git tag -a v0.1.0 -m "msg" => True (creation)
    """
    if _get_git_subcommand(cmd) != "tag":
        return False
    try:
        raw_tokens = shlex.split(cmd, posix=False)
    except ValueError:
        return False
    tokens = [t.strip('"').strip("'") for t in raw_tokens]
    try:
        tag_idx = tokens.index("tag")
    except ValueError:
        return False
    remaining = tokens[tag_idx + 1:]
    if any(t in ("-l", "--list") for t in remaining):
        return False
    for t in remaining:
        if not t.startswith("-"):
            return True
    return False


def _is_git_push(cmd: str) -> bool:
    """Return True if cmd is a git push (any form).

    git push --force / git push -f are already caught by the dangerous
    command guard. This catches all other push variants.
    """
    return _get_git_subcommand(cmd) == "push"
