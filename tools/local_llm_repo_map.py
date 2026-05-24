#!/usr/bin/env python3
"""
Repo/Codebase Map Generator — heuristic-only, read-only (C1).

Produces a structured JSON map of the repository: file classification,
risk tags, entrypoint detection, test mapping, and subsystem grouping.

No model calls. No MCP integration. No ledger writes. Advisory-only.
Output writes only to .local_llm_out/ when explicitly requested via CLI.
"""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
GENERATOR_VERSION = "local_llm_repo_map v0.1.0"

# ---------------------------------------------------------------------------
# Ignore paths — directories and file patterns to skip entirely
# ---------------------------------------------------------------------------
IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "node_modules", ".local_llm_out", ".mcp_audit", ".ruff_cache",
    "build", "dist",
}

IGNORE_EXTS = {".pyc", ".pyo", ".sqlite", ".db", ".pem", ".key", ".p12", ".pfx", ".jks"}

IGNORE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
}

IGNORE_NAME_PREFIXES = (".env.", "secrets", "credentials", "ssl/")

BINARY_SIGNATURES = (b"\x00", b"\xff\xd8\xff", b"\x89PNG", b"PK\x03\x04", b"GIF8")
BINARY_READ_LIMIT = 512


def _is_ignored(fpath: Path, dir_root: Path) -> bool:
    """Check if a path should be excluded from the repo map."""
    parts = fpath.relative_to(dir_root).parts
    for part in parts:
        if part in IGNORE_DIRS:
            return True
    name = fpath.name
    if name in IGNORE_NAMES:
        return True
    name_lower = name.lower()
    if name_lower.startswith(IGNORE_NAME_PREFIXES):
        return True
    if fpath.suffix.lower() in IGNORE_EXTS:
        return True
    return False


def _is_binary(fpath: Path) -> bool:
    """Heuristic binary detection: read first 512 bytes, look for null bytes
    or known binary signatures."""
    try:
        with open(fpath, "rb") as fh:
            head = fh.read(BINARY_READ_LIMIT)
        if not head:
            return False
        if b"\x00" in head:
            return True
        for sig in BINARY_SIGNATURES:
            if head.startswith(sig):
                return True
        return False
    except OSError:
        return True


# ---------------------------------------------------------------------------
# Role classification
# ---------------------------------------------------------------------------

def classify_file_role(path_str: str) -> str:
    """Classify a file into a semantic role based on path and name heuristics."""
    norm = path_str.replace("\\", "/").lower()
    name = Path(path_str).name

    if norm.endswith(".md"):
        if name.lower() in ("readme.md",):
            return "readme"
        if name.lower() in ("changelog.md",):
            return "changelog"
        if name.lower() in ("project_status.md",):
            return "project_status"
        if name.lower() in ("release_notes.md",):
            return "release_notes"
        if name.lower() in ("claude.md", "agents.md"):
            return "claude_instructions"
    if norm.startswith("docs/"):
        return "docs"

    if norm.endswith(".rst") or norm.endswith(".txt"):
        return "docs"

    if norm.startswith("tests/") and (norm.endswith(".py") or norm.endswith(".sh")):
        return "test"

    if norm.startswith("tools/claude_hooks/"):
        return "hook"

    if norm == "tools/local_llm_mcp_server.py":
        return "mcp_server"
    if norm == "tools/local_llm_worker.py":
        return "worker"
    if norm == "tools/local_llm_router.py":
        return "router"
    if norm == "tools/local_llm_debate.py":
        return "debate"
    if norm in ("tools/call_ledger.py", "tools/call_ledger_cli.py"):
        return "ledger"
    if norm == "tools/local_llm_cache.py":
        return "cache"
    if norm == "tools/local_llm_preclassifier.py":
        return "preclassifier"
    if norm == "tools/local_llm_check.py":
        return "health_check"
    if norm == "tools/local_llm_prompt_registry.py":
        return "prompt_registry"

    if norm in ("pyproject.toml", "version", "setup.cfg", "setup.py"):
        return "config"
    if norm in (".mcp.json",):
        return "mcp_config"
    if norm.endswith(".json") or norm.endswith(".yaml") or norm.endswith(".yml"):
        return "config"

    if norm.endswith(".py"):
        return "source"

    return "unknown"


def _file_subsystem(role: str) -> str:
    """Map role to subsystem."""
    mapping = {
        "mcp_server": "mcp",
        "mcp_config": "mcp",
        "worker": "worker",
        "router": "routing",
        "debate": "debate",
        "ledger": "ledger",
        "cache": "cache",
        "preclassifier": "preclassifier",
        "health_check": "diagnostic",
        "hook": "hooks",
        "readme": "docs",
        "changelog": "docs",
        "project_status": "docs",
        "release_notes": "docs",
        "claude_instructions": "docs",
        "docs": "docs",
        "test": "tests",
        "config": "config",
        "prompt_registry": "config",
        "source": "source",
    }
    return mapping.get(role, "other")


# ---------------------------------------------------------------------------
# Risk tags
# ---------------------------------------------------------------------------

def detect_risk_tags(path_str: str) -> list[str]:
    """Detect risk tags for a file based on heuristics."""
    norm = path_str.replace("\\", "/").lower()
    tags: list[str] = []

    if "local_llm_mcp_server.py" in norm or norm.endswith(".mcp.json"):
        tags.append("mcp")
    if "local_llm_worker.py" in norm:
        tags.append("worker")
    if "local_llm_router.py" in norm or "local_llm_profiles.json" in norm or "local_llm_tasks.json" in norm:
        tags.append("routing")
    if "local_llm_debate.py" in norm:
        tags.append("debate")
    if "call_ledger" in norm:
        tags.append("ledger")
    if "local_llm_cache.py" in norm:
        tags.append("cache")
    if "local_llm_preclassifier.py" in norm:
        tags.append("preclassifier")
    if "claude_hooks" in norm:
        tags.append("hooks")
    if "mcp_gate.py" in norm:
        tags.append("safety")
    if any(k in norm for k in ("dangerous", "release_guard")):
        tags.append("safety")
    if norm.endswith(".json") or norm.endswith(".yaml") or norm.endswith(".yml"):
        tags.append("config")
    if "pyproject.toml" in norm or norm == "version" or "setup.cfg" in norm:
        tags.append("config")
    if any(n in norm for n in ("docs/", ".md", ".rst", ".txt", "readme", "changelog", "project_status")):
        tags.append("docs")
    if "tests/" in norm and not norm.startswith("tests/test_"):
        pass
    elif norm.startswith("tests/") or "_test.py" in norm or norm.startswith("test_"):
        tags.append("tests")
    if "mcp_auto_worker" in norm:
        tags.append("auto_invocation")
    if "mcp_doctor" in norm:
        tags.append("diagnostic")
    if "health_store" in norm:
        tags.append("health")
    if any(k in norm for k in ("auth", "token", "credential", "api_key", "permission")):
        tags.append("security")

    return sorted(set(tags))


# ---------------------------------------------------------------------------
# Entrypoint detection
# ---------------------------------------------------------------------------

_ENTRYPOINT_NAMES = {
    "local_llm_mcp_server.py", "local_llm_worker.py", "local_llm_debate.py",
    "local_llm_router.py", "local_llm_check.py",
    "call_ledger_cli.py", "mcp_gate.py", "mcp_doctor.py",
    "run_checks.py",
}

_ENTRYPOINT_PATTERNS = [
    'if __name__ == "__main__"',
    "if __name__ == '__main__'",
    "argparse.ArgumentParser",
    "FastMCP",
    "def main(",
]


def detect_entrypoint(fpath: Path, *, content_sample: str | None = None) -> bool:
    """Detect if a file is a CLI/server entrypoint."""
    name = fpath.name.lower()
    if name in _ENTRYPOINT_NAMES:
        return True
    if name.endswith("_cli.py"):
        return True
    if fpath.suffix != ".py":
        return False

    sample = content_sample
    if sample is None:
        try:
            sample = fpath.read_text(encoding="utf-8", errors="replace")[:8192]
        except OSError:
            return False

    for pat in _ENTRYPOINT_PATTERNS:
        if pat in sample:
            return True
    return False


# ---------------------------------------------------------------------------
# Test mapping
# ---------------------------------------------------------------------------

def infer_test_mapping(files: list[dict]) -> dict[str, list[str]]:
    """Infer which test files cover which source files via naming heuristics.

    A test file ``tests/test_foo.py`` maps to any source file whose name
    contains ``foo`` (case-insensitive, normalised underscore/dash).
    """
    mapping: dict[str, list[str]] = {}
    source_paths: list[str] = []
    test_paths: list[tuple[str, str]] = []  # (path, stem)

    for f in files:
        p = f["path"]
        role = f.get("role", "")
        if role == "test":
            stem = Path(p).stem
            if stem.startswith("test_"):
                stem = stem[5:]
            if stem.endswith("_test"):
                stem = stem[:-5]
            test_paths.append((p, stem.lower().replace("_", "").replace("-", "")))
        elif role not in ("docs", "readme", "changelog", "project_status",
                          "release_notes", "claude_instructions", "unknown"):
            source_paths.append(p)

    for src in source_paths:
        src_stem = Path(src).stem.lower().replace("_", "").replace("-", "")
        covers: list[str] = []
        for tp, tstem in test_paths:
            if tstem and tstem in src_stem:
                covers.append(tp)
        if covers:
            mapping[src] = sorted(covers)

    return mapping


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def generate_cache_key(repo_map: dict) -> str:
    """Stable hash: schema_version + git_head + file_count + sorted path list."""
    files = repo_map.get("files", [])
    parts = [
        f"v{repo_map.get('schema_version', SCHEMA_VERSION)}",
        repo_map.get("git_head", ""),
        str(len(files)),
    ]
    for f in sorted(files, key=lambda x: x.get("path", "")):
        parts.append(f"{f.get('path','')}:{f.get('size',0)}:{f.get('mtime_ns',0)}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def _get_git_head(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(root), timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _safe_stat(fpath: Path) -> tuple[int, int]:
    try:
        st = fpath.stat()
        return st.st_size, st.st_mtime_ns
    except OSError:
        return 0, 0


def scan_repo(
    root: Path,
    *,
    include_tests: bool = True,
    include_docs: bool = True,
    max_files: int | None = None,
) -> dict:
    """Walk the repo and build a structured file listing.

    Returns a dict with keys: ``ok``, ``files``, ``skipped_files``,
    ``summary``, ``warnings``.  Does NOT write to disk.
    """
    root = root.resolve()
    files: list[dict] = []
    skipped_files: list[dict] = []
    warnings: list[str] = []

    if not root.exists():
        return {"ok": False, "files": [], "skipped_files": [], "summary": {},
                "warnings": [f"root directory not found: {root}"]}
    if not root.is_dir():
        return {"ok": False, "files": [], "skipped_files": [], "summary": {},
                "warnings": [f"root is not a directory: {root}"]}

    for dirpath_str, dirnames, filenames in os.walk(str(root)):
        dirpath = Path(dirpath_str)
        # Filter out ignored directories in-place
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for fname in sorted(filenames):
            fpath = dirpath / fname
            if _is_ignored(fpath, root):
                continue
            if not fpath.is_file():
                continue

            try:
                rel = str(fpath.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(fpath)

            role = classify_file_role(rel)

            # Filter by include flags
            if not include_tests and role == "test":
                skipped_files.append({"path": rel, "reason": "tests excluded via include_tests=false"})
                continue
            if not include_docs and role in ("docs", "readme", "changelog",
                                               "project_status", "release_notes",
                                               "claude_instructions"):
                skipped_files.append({"path": rel, "reason": "docs excluded via include_docs=false"})
                continue

            size, mtime_ns = _safe_stat(fpath)

            # Binary detection — skip binary, record as skipped
            if _is_binary(fpath):
                skipped_files.append({"path": rel, "reason": "binary file"})
                continue

            risk_tags = detect_risk_tags(rel)

            # Entrypoint: sample first 8 KB for content-based detection
            content_sample = None
            try:
                content_sample = fpath.read_text(encoding="utf-8", errors="replace")[:8192]
            except OSError:
                pass
            entrypoint = detect_entrypoint(fpath, content_sample=content_sample)

            subsystem = _file_subsystem(role)

            files.append({
                "path": rel,
                "role": role,
                "subsystem": subsystem,
                "risk_tags": risk_tags,
                "entrypoint": entrypoint,
                "size": size,
                "mtime_ns": mtime_ns,
            })

    # Apply max_files limit deterministically (after sort)
    files.sort(key=lambda f: f["path"])
    if max_files is not None and len(files) > max_files:
        overflow = files[max_files:]
        files = files[:max_files]
        for of in overflow:
            skipped_files.append({"path": of["path"], "reason": "max_files limit reached"})
        warnings.append(f"max_files={max_files} reached: {len(overflow)} files excluded")

    # Summary counts
    summary = {
        "total_files": len(files),
        "source_files": sum(1 for f in files if f["role"] == "source"),
        "docs_files": sum(1 for f in files if f["role"] in (
            "docs", "readme", "changelog", "project_status", "release_notes",
            "claude_instructions")),
        "test_files": sum(1 for f in files if f["role"] == "test"),
        "config_files": sum(1 for f in files if f["role"] in ("config", "mcp_config")),
        "hook_files": sum(1 for f in files if f["role"] == "hook"),
        "mcp_files": sum(1 for f in files if f["role"] == "mcp_server"),
        "skipped_files": len(skipped_files),
    }

    return {
        "ok": True,
        "files": files,
        "skipped_files": skipped_files,
        "summary": summary,
        "warnings": warnings,
    }


def build_repo_map(
    root: Path,
    *,
    include_tests: bool = True,
    include_docs: bool = True,
    max_files: int | None = None,
) -> dict:
    """Build the full repo map document (schema v1).

    Returns a dict ready for JSON serialisation.
    """
    scan = scan_repo(root, include_tests=include_tests, include_docs=include_docs,
                     max_files=max_files)

    if not scan["ok"]:
        return {
            "schema_version": SCHEMA_VERSION,
            "repo_root": str(root),
            "git_head": "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": GENERATOR_VERSION,
            "cache_key": "",
            "ok": False,
            "error": scan["warnings"][0] if scan["warnings"] else "scan failed",
            "summary": scan["summary"],
            "files": [],
            "skipped_files": scan["skipped_files"],
            "subsystems": {},
            "test_mapping": {},
            "risk_tags_legend": RISK_TAGS_LEGEND,
        }

    git_head = _get_git_head(root)

    files = scan["files"]
    skipped = scan["skipped_files"]

    # Build subsystems index
    subsystems: dict[str, dict] = {}
    for f in files:
        sub = f["subsystem"]
        if sub not in subsystems:
            subsystems[sub] = {"key_files": [], "file_count": 0}
        subsystems[sub]["file_count"] += 1
        if f.get("entrypoint") or f["role"] in (
            "mcp_server", "worker", "router", "debate", "ledger", "hook",
        ):
            subsystems[sub]["key_files"].append(f["path"])

    # Sort key_files within each subsystem
    for sub in subsystems:
        subsystems[sub]["key_files"].sort()

    # Build test mapping
    test_mapping = infer_test_mapping(files)

    repo_map = {
        "schema_version": SCHEMA_VERSION,
        "repo_root": str(root),
        "git_head": git_head,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": GENERATOR_VERSION,
        "ok": True,
        "summary": scan["summary"],
        "files": files,
        "skipped_files": skipped,
        "subsystems": dict(sorted(subsystems.items())),
        "test_mapping": test_mapping,
        "risk_tags_legend": RISK_TAGS_LEGEND,
    }
    repo_map["cache_key"] = generate_cache_key(repo_map)
    return repo_map


# ---------------------------------------------------------------------------
# Risk tags legend
# ---------------------------------------------------------------------------

RISK_TAGS_LEGEND = {
    "mcp": "MCP protocol surface — changes affect all MCP tool contracts",
    "worker": "Worker runtime — changes affect all local model calls",
    "routing": "Model/profile routing — changes affect which model serves which task",
    "debate": "Multi-model debate — changes affect cross-review behavior",
    "ledger": "Call ledger — changes affect cost/usage tracking",
    "cache": "Result cache — changes affect cache-hit behavior",
    "preclassifier": "Diff risk preclassifier — changes affect skip decisions",
    "hooks": "Claude Code hook logic — changes affect guard enforcement",
    "safety": "Safety/security boundary — changes affect guard enforcement",
    "config": "Configuration — changes affect system behavior without code change",
    "docs": "Documentation — advisory only, no runtime impact",
    "tests": "Test files — does not affect production behavior",
    "auto_invocation": "Auto-invocation — changes affect background worker spawning",
    "diagnostic": "Diagnostic/doctor — changes affect health checks",
    "health": "Health telemetry — changes affect profile health tracking",
    "security": "Security-related — changes affect auth/token/credential handling",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repo Map Generator — heuristic-only, read-only (C1)",
    )
    parser.add_argument("--root", default=".", help="Repo root directory (default: .)")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--write", default=None, help="Write JSON to file path")
    parser.add_argument("--include-tests", action="store_true", default=True,
                        help="Include test files (default: true)")
    parser.add_argument("--no-tests", action="store_true",
                        help="Exclude test files")
    parser.add_argument("--include-docs", action="store_true", default=True,
                        help="Include documentation files (default: true)")
    parser.add_argument("--no-docs", action="store_true",
                        help="Exclude documentation files")
    parser.add_argument("--max-files", type=int, default=None,
                        help="Maximum files to include")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    include_tests = not args.no_tests
    include_docs = not args.no_docs

    repo_map = build_repo_map(
        root,
        include_tests=include_tests,
        include_docs=include_docs,
        max_files=args.max_files,
    )

    json_str = json.dumps(repo_map, indent=2, ensure_ascii=False)

    if args.write:
        out_path = Path(args.write)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        print(f"Repo map written to {out_path} ({len(repo_map.get('files', []))} files)")
        return 0

    if args.json:
        print(json_str)
        return 0

    # Default: human-readable summary
    if not repo_map.get("ok"):
        print(f"ERROR: {repo_map.get('error', 'scan failed')}")
        return 1

    s = repo_map["summary"]
    print(f"Repo Map v{SCHEMA_VERSION}  —  {repo_map['repo_root']}")
    print(f"  git: {repo_map['git_head']}")
    print(f"  generated: {repo_map['generated_at']}")
    print(f"  cache_key: {repo_map['cache_key']}")
    print(f"  files: {s['total_files']} total")
    print(f"    source: {s['source_files']}")
    print(f"    docs:   {s['docs_files']}")
    print(f"    tests:  {s['test_files']}")
    print(f"    config: {s['config_files']}")
    print(f"    hooks:  {s['hook_files']}")
    print(f"    mcp:    {s['mcp_files']}")
    print(f"    skipped:{s['skipped_files']}")
    print(f"  subsystems: {len(repo_map['subsystems'])}")
    for name, info in sorted(repo_map["subsystems"].items()):
        print(f"    {name}: {info['file_count']} files")
    print(f"  test_mapping: {len(repo_map['test_mapping'])} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
