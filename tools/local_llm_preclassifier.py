#!/usr/bin/env python3
"""
Diff Risk Preclassifier — heuristic-only safety core (B1-A).

Classifies git diffs into risk levels based on file paths, content patterns,
and size — without any local model calls. All outputs default to
``escalate_to_debate=true`` and ``skip_debate_allowed=false``. No debate
is ever skipped by this module; the allow gate belongs to a later phase.

Read-only. No source mutation. No MCP integration yet.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Change thresholds
# ---------------------------------------------------------------------------
LARGE_DIFF_CHARS = 50_000


# ---------------------------------------------------------------------------
# Known sensitive path patterns (hard-coded safety blocklist)
# ---------------------------------------------------------------------------
_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    # MCP server / tool schema
    ("tools/local_llm_mcp_server.py", "MCP server source"),
    ("tools/local_llm_worker.py", "worker runtime"),
    ("tools/local_llm_debate.py", "debate runtime"),
    ("tools/local_llm_router.py", "model router"),
    ("tools/local_llm_prompt_registry.py", "prompt registry"),
    ("tools/local_llm_tasks.json", "task definitions"),
    ("tools/local_llm_check.py", "health check logic"),
    ("tools/local_llm_cache.py", "cache logic"),
    # Hook / gate / guard
    ("claude_hooks", "hook/guard logic"),
    ("mcp_gate", "MCP gate logic"),
    ("mcp_doctor", "MCP doctor logic"),
    ("mcp_auto_worker", "auto worker logic"),
    # Ledger / audit / cost
    ("call_ledger", "call ledger"),
    ("mcp_audit", "audit system"),
    ("audit", "audit directory"),
    ("cost_discipline", "cost discipline"),
    ("billing", "billing"),
    # Auth / security / credential
    ("auth", "authentication"),
    ("token", "token handling"),
    ("credential", "credential handling"),
    ("webauthn", "WebAuthn"),
    ("security", "security boundary"),
    ("permission", "permission system"),
    ("oauth", "OAuth"),
    ("api_key", "API key handling"),
    # Endpoint / provider / network
    ("endpoint", "endpoint routing"),
    ("provider", "model provider"),
    ("base_url", "base URL routing"),
    ("network", "network routing"),
    ("proxy", "proxy configuration"),
    # Release / version
    ("VERSION", "version bump"),
    ("version", "version metadata"),
    ("release", "release process"),
    ("pyproject.toml", "package metadata"),
    ("setup.cfg", "package metadata"),
    # Destructive / archive
    ("delete", "deletion logic"),
    ("archive", "archival logic"),
    ("push", "git push"),
    ("publish", "publish process"),
    # Test fixtures with security implications
    (".env", "environment secrets"),
    ("secrets", "secrets directory"),
    ("credentials", "credentials file"),
    ("ssl", "SSL/TLS"),
    ("tls", "SSL/TLS"),
    ("certificate", "certificate handling"),
]


def detect_changed_files(diff_text: str) -> list[str]:
    """Extract changed file paths from a unified git diff.

    Handles:
    - ``diff --git a/path b/path``
    - ``rename from / rename to``
    - ``deleted file``
    - ``new file``
    - Windows-style paths (both / and \\\\ separators)
    """
    if not diff_text or not diff_text.strip():
        return []

    files: set[str] = set()

    # Standard diff --git lines
    for m in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", diff_text, re.MULTILINE):
        a = m.group(1).strip()
        b = m.group(2).strip()
        # Normalize path separators
        normalized = a.replace("\\", "/")
        files.add(normalized)
        if b and b != a:
            files.add(b.replace("\\", "/"))

    # Rename detection
    for m in re.finditer(r"^rename from (.+)$", diff_text, re.MULTILINE):
        files.add(m.group(1).strip().replace("\\", "/"))
    for m in re.finditer(r"^rename to (.+)$", diff_text, re.MULTILINE):
        files.add(m.group(1).strip().replace("\\", "/"))

    # New file
    for m in re.finditer(r"^new file mode \d+$", diff_text, re.MULTILINE):
        pass  # usually paired with diff --git, already captured

    # Deleted file
    for m in re.finditer(r"^deleted file mode \d+$", diff_text, re.MULTILINE):
        pass  # usually paired with diff --git

    return sorted(files)


def detect_sensitive_paths(changed_files: list[str]) -> list[dict[str, str]]:
    """Return list of {path, reason} for any file matching the sensitive blocklist.

    Case-insensitive matching on the normalized path.

    ``.md`` documentation files are excluded from the "release", "version",
    "publish", and "push" keyword patterns — ``RELEASE_NOTES.md`` is a doc,
    not a release script.
    """
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for f in changed_files:
        norm = f.replace("\\", "/").lower()
        is_md = norm.endswith(".md")
        for pattern, reason in _SENSITIVE_PATTERNS:
            if pattern.lower() not in norm:
                continue
            # .md docs are not release/version/publish scripts
            if is_md and pattern.lower() in ("release", "version", "publish", "push"):
                continue
            if f not in seen:
                matches.append({"path": f, "reason": reason})
                seen.add(f)
            break  # first match is enough per file
    return matches


def is_docs_only(changed_files: list[str]) -> bool:
    """Return True when every changed file is a documentation-only file.

    Allowed: ``*.md``, ``docs/**``, ``CHANGELOG.md``, ``PROJECT_STATUS.md``,
    ``RELEASE_NOTES.md``.

    Explicitly NOT allowed: ``VERSION``, ``pyproject.toml``, ``setup.cfg``,
    and any file not ending in ``.md`` outside ``docs/``.
    """
    if not changed_files:
        return False
    for f in changed_files:
        norm = f.replace("\\", "/")
        if norm.endswith(".md") or norm.startswith("docs/"):
            continue
        return False
    return True


def is_tests_only(changed_files: list[str]) -> bool:
    """Return True when every changed file is a test file and there are no
    non-test files mixed in.

    Allowed: ``tests/**``, ``*_test.py``, ``test_*.py``.

    Explicitly NOT allowed: runtime files, config files, VERSION.
    """
    if not changed_files:
        return False
    for f in changed_files:
        norm = f.replace("\\", "/")
        if norm.startswith("tests/") or norm.endswith("_test.py") or norm.startswith("test_"):
            continue
        return False
    return True


def _has_runtime_code_changes(diff_text: str, changed_files: list[str]) -> bool:
    """Check if any changed file is a runtime source file (not docs, not tests)."""
    for f in changed_files:
        norm = f.replace("\\", "/")
        if norm.endswith(".md") or norm.startswith("docs/"):
            continue
        if norm.startswith("tests/") or norm.endswith("_test.py") or norm.startswith("test_"):
            continue
        if norm == "CHANGELOG.md" or norm == "PROJECT_STATUS.md" or norm == "RELEASE_NOTES.md":
            continue
        return True
    return False


def _has_version_or_release_files(parsed_files: list[str]) -> bool:
    """Check if VERSION or release/publish metadata files are touched.

    ``RELEASE_NOTES.md`` is a documentation file and does NOT trigger
    a version/release flag on its own.
    """
    for f in parsed_files:
        norm = f.replace("\\", "/")
        if norm == "VERSION" or norm.endswith("/VERSION"):
            return True
        if "release" in norm.lower() and not norm.endswith(".md"):
            return True
        if "publish" in norm.lower() and not norm.endswith(".md"):
            return True
        if norm == "pyproject.toml" or norm == "setup.cfg":
            return True
    return False


def _detect_security_patterns_in_body(diff_text: str) -> bool:
    """Check if the diff body contains security-sensitive code patterns."""
    if not diff_text:
        return False
    security_patterns = [
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"\bcompile\s*\(",
        r"\b__import__\s*\(",
        r"\bsubprocess\b",
        r"\bos\.system\b",
        r"\bos\.popen\b",
        r"\bpickle\.loads?\b",
        r"\bpickle\.dumps?\b",
        r"\bmarshal\.loads?\b",
        r"\bshell\s*=\s*True\b",
        r"\brm\s+-rf?\s",
        r"\bdel\s+/[sfq]\s",
        r"\bRemove-Item\s+-Recurse\s+-Force\b",
    ]
    for pat in security_patterns:
        if re.search(pat, diff_text, re.IGNORECASE):
            return True
    return False


def classify_diff_risk_heuristic(
    diff_text: str,
    changed_files: list[str] | None = None,
    context: dict | None = None,
) -> dict:
    """Classify a git diff into a risk level using heuristic-only analysis.

    No local model calls. No debate skipping. Conservative default:
    ``escalate_to_debate=true`` for every non-trivial case.

    Args:
        diff_text: Raw unified diff content.
        changed_files: Optional pre-parsed file list (overrides extraction from diff).
        context: Optional context dict with keys like ``commit_gate``, ``release``.

    Returns:
        A dict conforming to the B0 preclassifier JSON contract.
    """
    now = datetime.now(timezone.utc).isoformat()
    ctx = context or {}

    # 1. Parse changed files
    parsed_files = list(changed_files) if changed_files is not None else detect_changed_files(diff_text)

    # 2. Detect sensitivity
    sensitive = detect_sensitive_paths(parsed_files)

    # 3. Determine content categories
    docs_only = is_docs_only(parsed_files) if parsed_files else False
    tests_only = is_tests_only(parsed_files) if parsed_files else False
    has_runtime = _has_runtime_code_changes(diff_text, parsed_files) if parsed_files else False
    has_version_release = _has_version_or_release_files(parsed_files)
    has_security_body = _detect_security_patterns_in_body(diff_text)
    diff_size = len(diff_text) if diff_text else 0

    # 4. Safety blockers accumulation
    safety_blockers: list[str] = []
    risk_reasons: list[str] = []
    risk_level = "low"
    confidence = "high"

    # --- Empty / unknown diff ---
    if not parsed_files:
        return {
            "ok": True,
            "risk_level": "unknown",
            "confidence": "low",
            "skip_debate_recommended": False,
            "skip_debate_allowed": False,
            "escalate_to_debate": True,
            "sensitive_paths": [],
            "changed_files": [],
            "risk_reasons": ["no changed files detected — cannot classify"],
            "safety_blockers": ["empty or unparseable diff"],
            "classification_method": "heuristic",
            "created_at": now,
        }

    # --- Malformed / empty diff text ---
    if not diff_text or not diff_text.strip():
        return {
            "ok": True,
            "risk_level": "unknown",
            "confidence": "low",
            "skip_debate_recommended": False,
            "skip_debate_allowed": False,
            "escalate_to_debate": True,
            "sensitive_paths": [],
            "changed_files": parsed_files,
            "risk_reasons": ["empty diff text — cannot classify content"],
            "safety_blockers": ["empty diff text"],
            "classification_method": "heuristic",
            "created_at": now,
        }

    # --- Large diff ---
    if diff_size > LARGE_DIFF_CHARS:
        risk_level = "high"
        risk_reasons.append(f"diff too large ({diff_size} chars)")
        safety_blockers.append(f"diff exceeds {LARGE_DIFF_CHARS} chars")

    # --- Sensitive paths ---
    if sensitive:
        risk_level = "high"
        for s in sensitive:
            safety_blockers.append(f"{s['path']}: {s['reason']}")
        risk_reasons.append(f"{len(sensitive)} sensitive path(s) detected")

    # --- Security patterns in body ---
    if has_security_body:
        risk_level = "high"
        risk_reasons.append("security-sensitive code patterns detected in diff body")
        safety_blockers.append("security patterns in diff body")

    # --- Version / release files ---
    if has_version_release:
        if risk_level != "high":
            risk_level = "high"
        risk_reasons.append("version or release metadata touched")
        safety_blockers.append("version/release files require debate review")

    # --- Commit gate context (always escalate) ---
    if ctx.get("commit_gate") is True:
        risk_reasons.append("commit gate context — debate escalation mandatory")
        safety_blockers.append("commit gate requires debate review")

    # --- Release context (always escalate) ---
    if ctx.get("release") is True:
        risk_reasons.append("release context — debate escalation mandatory")
        safety_blockers.append("release requires full debate review")

    # --- Docs-only ---
    if docs_only and risk_level == "low":
        risk_reasons.append("docs-only changes")
        # Docs-only is the only case where we recommend skipping
        # (but still don't allow it in B1-A)
        skip_recommended = True
    else:
        skip_recommended = False

    # --- Tests-only ---
    if tests_only and risk_level == "low":
        if has_runtime:
            risk_level = "medium"
            risk_reasons.append("tests-only changes but runtime code also touched")
        else:
            risk_reasons.append("tests-only changes")
            skip_recommended = True

    # --- Runtime code changes ---
    if has_runtime and not docs_only and not tests_only:
        if risk_level == "low":
            risk_level = "medium"
        risk_reasons.append("runtime code changes detected")
        skip_recommended = False

    # --- If no blockers but has runtime, still escalate in B1-A ---
    if safety_blockers:
        confidence_for_risk = "high" if risk_level == "high" else "medium"
    elif has_runtime:
        confidence_for_risk = "medium"
    else:
        confidence_for_risk = confidence

    # B1-A iron rule: escalate_to_debate is always true
    # (skip_debate_allowed stays false until B1-C/B1-D)
    escalate = True
    skip_allowed = False

    # In B1-A, skip_debate_recommended can be true for docs-only/tests-only
    # but skip_debate_allowed stays false
    if skip_recommended and not safety_blockers:
        risk_reasons.append("B1-A: skip recommended but NOT allowed (debate gate not yet integrated)")

    sensitive_paths_out = [s["path"] for s in sensitive]

    return {
        "ok": True,
        "risk_level": risk_level,
        "confidence": confidence_for_risk,
        "skip_debate_recommended": skip_recommended and not safety_blockers,
        "skip_debate_allowed": skip_allowed,
        "escalate_to_debate": escalate,
        "sensitive_paths": sensitive_paths_out,
        "changed_files": parsed_files,
        "risk_reasons": risk_reasons,
        "safety_blockers": safety_blockers,
        "classification_method": "heuristic",
        "created_at": now,
    }
