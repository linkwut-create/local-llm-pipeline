#!/usr/bin/env python3
"""Task Bootstrap — thin orchestration layer for project context bootstrapping.

Combines repo_map + key file selection + optional summaries into a
single command.  Read-only.  Advisory-only.  Writes only to .local_llm_out/.

Usage:
    py -3 tools/task_bootstrap.py --project PATH [options]

Options:
    --project PATH       Target project root (required).
    --task TEXT          Optional task description for context-aware selection.
    --max-summaries N    Max files to LLM-summarize (default: 3).
    --budget N           Approximate token budget (default: 6000).
    --no-summaries       Skip LLM summaries; repo_map + file list only.
    --json               Print machine-readable JSON to stdout.
    --out-dir PATH       Output directory (default: .local_llm_out/).
    --dry-run            No LLM calls; repo_map + selected files only.

Exit codes:
    0 = bootstrap completed (partial summary failure ok).
    1 = repo_map failed.
    2 = project path invalid.
    3 = all summaries failed (when summaries were requested).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from local_llm_repo_map import build_repo_map

SCHEMA_VERSION = 1
GENERATOR_ID = "task_bootstrap v0.1.0"

ESTIMATED_CHARS_PER_TOKEN = 4
REPO_MAP_TOKEN_OVERHEAD = 2500
SUMMARY_TOKEN_ESTIMATE = 1200

INSTRUCTION_FILE_NAMES = {
    "claude.md", "agents.md", "readme.md", "readme.txt", "readme.rst",
    "readme", "codex.md",
}

_VENDOR_PATH_PREFIXES = (
    "tools/local_llm_", "tools/claude_", ".venv/", "node_modules/",
    "models/", "vendor/", "third_party/", "external/", "runtime/",
    "cache/", "data/",
)

_TASK_SYNONYMS: dict[str, list[str]] = {
    "translation": ["tm", "translate", "translator"],
    "memory": ["tm", "cache", "storage"],
    "subtitle": ["srt", "subtitle", "caption", "transcription"],
    "realtime": ["live", "stream", "streaming"],
    "ocr": ["ocr", "paddleocr", "paddle", "image"],
    "glossary": ["terminology", "terms", "glossary"],
    "terminology": ["terms", "glossary", "glossary"],
    "tm": ["translation", "memory"],
    "embed": ["embedding", "semantic", "vector"],
    "voice": ["audio", "speech", "whisper"],
    "screenshot": ["screen", "capture", "overlay"],
}

ROUTER_PATH = SCRIPT_DIR / "local_llm_router.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_git_info(project_root: Path) -> dict:
    """Best-effort git metadata. Never raises."""
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(project_root), text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        head = ""
    try:
        describe = subprocess.check_output(
            ["git", "describe", "--tags", "--dirty"],
            cwd=str(project_root), text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        describe = ""
    try:
        dirty = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=str(project_root), text=True, stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(dirty)
    except Exception:
        dirty = None
    return {"head": head, "describe": describe, "dirty": dirty}


def _estimate_tokens(chars: int) -> int:
    return max(1, chars // ESTIMATED_CHARS_PER_TOKEN)


def _looks_like_test(path: str) -> bool:
    p = path.lower().replace("\\", "/")
    return p.startswith("tests/") or p.startswith("test/") or "test_" in p


def _task_mentions_tests(task_text: str) -> bool:
    if not task_text:
        return False
    t = task_text.lower()
    return any(kw in t for kw in ("test", "tests", "pytest", "testing"))


def _task_keywords(task_text: str) -> set[str]:
    if not task_text:
        return set()
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", task_text.lower())
    stop = {"the", "and", "for", "with", "that", "this", "from", "have",
            "has", "are", "not", "but", "its", "it's", "can", "all", "will",
            "should", "would", "could", "does", "when", "where", "which"}
    base = {w for w in words if w not in stop}
    # Expand synonyms
    expanded = set(base)
    for kw in base:
        for syn in _TASK_SYNONYMS.get(kw, []):
            expanded.add(syn)
    return expanded


def _looks_like_vendor_embedded(path: str) -> bool:
    p = path.lower().replace("\\", "/")
    return any(p.startswith(prefix) for prefix in _VENDOR_PATH_PREFIXES)


def _is_root_level(path: str) -> bool:
    """True if the path has at most one directory component (root level)."""
    p = path.replace("\\", "/")
    return "/" not in p


# ---------------------------------------------------------------------------
# File selection
# ---------------------------------------------------------------------------

def _select_instruction_files(files: list[dict]) -> list[dict]:
    """Return root-level CLAUDE.md / AGENTS.md / README.* entries."""
    result = []
    seen = set()
    for f in files:
        path = f["path"].replace("\\", "/")
        name = Path(path).name.lower()
        if name not in INSTRUCTION_FILE_NAMES:
            continue
        # Only root-level or docs/ level
        if "/" in path and not path.startswith("docs/"):
            continue
        if _looks_like_vendor_embedded(path):
            continue
        if path not in seen:
            seen.add(path)
            result.append(f)
    result.sort(key=lambda f: (
        0 if Path(f["path"]).name.lower() in ("claude.md", "agents.md")
        else 1,
        f["path"],
    ))
    return result


def _select_summary_candidates(
    files: list[dict],
    task_text: str,
    max_summaries: int,
) -> list[dict]:
    """Select files for LLM summarization. Returns files with a selection_reason."""
    if max_summaries <= 0:
        return []

    task_kw = _task_keywords(task_text)
    task_mentions_test = _task_mentions_tests(task_text)

    def _ok(f: dict) -> bool:
        if _looks_like_test(f["path"]) and not task_mentions_test:
            return False
        return True

    def _task_match_score(f: dict) -> int:
        """Score a file against task keywords. Higher = more relevant."""
        if not task_kw:
            return 0
        parts = f["path"].lower().replace("\\", "/").split("/")
        filename = parts[-1]
        score = 0
        for kw in task_kw:
            if kw in filename:
                score += 3
            elif any(kw in part for part in parts[:-1]):
                score += 1
        return score

    # Collect candidates with scores
    candidates: list[dict] = []
    seen: set[str] = set()

    # Priority 1: entrypoints (non-vendor, non-test)
    entrypoints = [f for f in files if f.get("entrypoint")
                   and not _looks_like_vendor_embedded(f["path"])]
    entrypoints.sort(key=lambda f: f.get("size", 0), reverse=True)
    for f in entrypoints:
        if _ok(f):
            seen.add(f["path"])
            candidates.append({**f, "selection_reason": "entrypoint"})

    # Priority 1.5: task keyword matched sources (boosted above generic size)
    if task_kw:
        scored_source = [
            (f, _task_match_score(f))
            for f in files
            if f.get("role") == "source"
            and f["path"] not in seen
            and not _looks_like_vendor_embedded(f["path"])
            and _ok(f)
        ]
        scored_source.sort(key=lambda x: x[1], reverse=True)
        for f, score in scored_source:
            if score > 0:
                seen.add(f["path"])
                candidates.append({**f, "selection_reason": "task_keyword_match"})

    # Priority 2: largest project source files not already selected
    sources = [f for f in files if f.get("role") == "source"
               and not _looks_like_vendor_embedded(f["path"])]
    sources.sort(key=lambda f: f.get("size", 0), reverse=True)
    for f in sources:
        if f["path"] in seen:
            continue
        if not _ok(f):
            continue
        seen.add(f["path"])
        candidates.append({**f, "selection_reason": "largest_source"})

    # Priority 3: remaining entrypoints (including vendor) as fallback
    remaining_eps = [f for f in files if f.get("entrypoint")
                     and f["path"] not in seen]
    remaining_eps.sort(key=lambda f: f.get("size", 0), reverse=True)
    for f in remaining_eps:
        if not _ok(f):
            continue
        seen.add(f["path"])
        candidates.append({**f, "selection_reason": "entrypoint"})

    # Slice to max_summaries
    selected = candidates[:max_summaries]
    return selected


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------

def _build_what_not_to_read(
    repo_map: dict,
    instruction_files: list[dict],
    selected: list[dict],
) -> list[str]:
    """Generate list of file categories the user can safely skip first."""
    items = []
    summary = repo_map.get("summary", {})
    selected_paths = {s["path"] for s in selected}
    inst_paths = {i["path"] for i in instruction_files}

    test_count = summary.get("test_files", 0)
    if test_count > 10 and not any(_looks_like_test(p) for p in selected_paths):
        items.append(
            f"tests/ ({test_count} files) — deferred until test plan is needed"
        )

    config_count = summary.get("config_files", 0)
    if config_count > 50:
        items.append(
            f"config/data files ({config_count} files) — runtime data, not architecture"
        )

    # Release notes / changelog files not selected
    release_files = [
        f for f in repo_map.get("files", [])
        if any(kw in f["path"].lower()
               for kw in ("release_note", "changelog", "snapshot"))
        and f["path"] not in selected_paths
        and f["path"] not in inst_paths
    ]
    if len(release_files) > 2:
        items.append(
            f"release notes / changelogs ({len(release_files)} files) "
            f"— historical, not current architecture"
        )

    # Large docs that aren't instructions
    large_docs = [
        f for f in repo_map.get("files", [])
        if f.get("role") in ("docs", "unknown")
        and f.get("size", 0) > 10000
        and f["path"] not in selected_paths
        and f["path"] not in inst_paths
    ]
    if large_docs:
        names = ", ".join(f["path"] for f in large_docs[:3])
        suffix = "..." if len(large_docs) > 3 else ""
        items.append(
            f"large doc files not selected for summary: {names}{suffix}"
        )

    return items


def _build_risk_hints(repo_map: dict) -> list[str]:
    hints = []
    files = repo_map.get("files", [])
    risk_counts: dict[str, int] = {}
    for f in files:
        for tag in f.get("risk_tags", []):
            risk_counts[tag] = risk_counts.get(tag, 0) + 1

    security_count = risk_counts.get("security", 0)
    if security_count:
        hints.append(
            f"security: {security_count} files tagged — review sensitive paths"
        )

    # Check for very large entrypoints
    for f in files:
        if f.get("entrypoint") and f.get("size", 0) > 50000:
            hints.append(
                f"large entrypoint: {f['path']} is "
                f"{f['size'] // 1000}KB — deep understanding requires focused review"
            )

    # Check for MCP tools present
    mcp_count = risk_counts.get("mcp", 0)
    if mcp_count:
        hints.append(
            f"mcp: {mcp_count} MCP-related files — may use local LLM pipeline"
        )

    return hints


def _build_suggested_calls(
    selected: list[dict],
    project_path: str,
) -> list[str]:
    calls = []
    for s in selected:
        calls.append(
            f"py -3 tools/local_llm_router.py summarize-file "
            f'"{project_path}/{s["path"]}" --max-chars 12000'
        )
    # Add test plan suggestion for largest selected source
    sources = [s for s in selected if s.get("role") == "source"]
    if sources:
        largest = max(sources, key=lambda s: s.get("size", 0))
        calls.append(
            f"py -3 tools/local_llm_router.py generate-test-plan "
            f'"{project_path}/{largest["path"]}"'
        )
    # Add repo review suggestion
    calls.append(
        "git diff | py -3 tools/local_llm_router.py review-diff --stdin"
    )
    return calls


def _build_context_budget(
    repo_map: dict,
    summaries: list[dict],
    budget_limit: int,
) -> dict:
    repo_map_tokens = _estimate_tokens(
        sum(f.get("size", 0) for f in repo_map.get("files", [])[:50])
    )
    # Better: use fixed overhead estimate
    repo_map_overhead = REPO_MAP_TOKEN_OVERHEAD
    summaries_tokens = sum(
        s.get("summary_chars", SUMMARY_TOKEN_ESTIMATE * ESTIMATED_CHARS_PER_TOKEN)
        for s in summaries
    ) // ESTIMATED_CHARS_PER_TOKEN
    return {
        "budget_limit": budget_limit,
        "estimated_tokens": repo_map_overhead + summaries_tokens,
        "repo_map_tokens": repo_map_overhead,
        "summaries_tokens": summaries_tokens,
    }


def _run_summary(file_path: str, max_chars: int = 12000) -> dict:
    """Run summarize-file via router. Returns {ok, summary, output_path, error}.

    Reads the actual markdown summary file produced by the worker.
    Never returns router stderr/status lines as summary content.
    """
    try:
        result = subprocess.run(
            [
                sys.executable, str(ROUTER_PATH),
                "summarize-file", file_path,
                "--max-chars", str(max_chars),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return {
                "ok": False,
                "summary": "",
                "error": f"router exit {result.returncode}: "
                         f"{result.stderr[:200] if result.stderr else 'no stderr'}",
            }
        # Find output file path from router stderr
        output_path = ""
        for line in result.stderr.splitlines():
            stripped = line.strip()
            if stripped.startswith("MD:") or stripped.startswith("Markdown:"):
                output_path = line.split(":", 1)[1].strip()
                break
        # Read summary from the worker's output file
        summary = ""
        if output_path:
            candidates = [
                Path(output_path),
                Path.cwd() / output_path,
                SCRIPT_DIR.parent / output_path,
            ]
            for sp in candidates:
                try:
                    if sp.exists() and sp.is_file():
                        summary = sp.read_text(encoding="utf-8", errors="replace")
                        break
                except Exception:
                    continue
        if not summary:
            return {
                "ok": False,
                "summary": "",
                "error": f"summary file not readable: {output_path or 'no path found'}",
                "output_path": output_path,
            }
        return {
            "ok": True,
            "summary": summary[:6000],
            "output_path": output_path,
            "summary_chars": len(summary),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "summary": "", "error": "timeout after 120s"}
    except Exception as e:
        return {"ok": False, "summary": "", "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def _build_markdown(
    project_path: str,
    task_text: str,
    git_info: dict,
    repo_map: dict,
    instruction_files: list[dict],
    selected: list[dict],
    risk_hints: list[str],
    suggested_calls: list[str],
    context_budget: dict,
    what_not_to_read: list[str],
    summaries: list[dict],
    dry_run: bool,
) -> str:
    summary = repo_map.get("summary", {})
    lines = [
        f"# Task Bootstrap: {Path(project_path).name}",
        "",
        f"**Generated**: {_now_iso()}",
        f"**Project**: `{project_path}`",
        f"**Git**: `{git_info.get('describe', git_info.get('head', '?'))}`",
    ]
    if task_text:
        lines.append(f"**Task**: {task_text}")
    if dry_run:
        lines.append("**Mode**: dry-run (no LLM calls)")
    lines += [
        "",
        "## Repo Map Summary",
        "",
        f"| Category | Count |",
        f"|----------|-------|",
        f"| Total files | {summary.get('total_files', 0)} |",
        f"| Source files | {summary.get('source_files', 0)} |",
        f"| Test files | {summary.get('test_files', 0)} |",
        f"| Doc files | {summary.get('docs_files', 0)} |",
        f"| Config files | {summary.get('config_files', 0)} |",
    ]

    subsystems = repo_map.get("subsystems", {})
    if subsystems:
        lines.append("")
        lines.append("### Subsystems")
        lines.append("")
        for sub, info in sorted(subsystems.items()):
            key_files = info.get("key_files", [])
            kf_str = ", ".join(key_files[:5])
            if len(key_files) > 5:
                kf_str += f", ... (+{len(key_files) - 5})"
            lines.append(
                f"- **{sub}** ({info.get('file_count', 0)} files)"
            )
            if kf_str:
                lines.append(f"  - Key: {kf_str}")

    entrypoints = [f for f in repo_map.get("files", []) if f.get("entrypoint")]
    if entrypoints:
        lines.append("")
        lines.append("### Entrypoints")
        lines.append("")
        for ep in entrypoints[:15]:
            lines.append(f"- `{ep['path']}` ({ep.get('size', 0) // 1000}KB)")

    lines += [
        "",
        "## Read First — Project Instructions",
        "",
    ]
    if instruction_files:
        for inf in instruction_files:
            size_kb = inf.get("size", 0) // 1000
            role = inf.get("role", "unknown")
            lines.append(f"- **`{inf['path']}`** ({size_kb}KB, {role})")
    else:
        lines.append("(no instruction files found)")

    lines += [
        "",
        "## Selected Files for Summary",
        "",
    ]
    if selected:
        for i, s in enumerate(selected, 1):
            reason = s.get("selection_reason", "unknown")
            size_kb = s.get("size", 0) // 1000
            lines.append(f"### {i}. `{s['path']}` ({size_kb}KB, {reason})")
            if i <= len(summaries) and summaries[i - 1].get("ok"):
                lines.append("")
                lines.append(summaries[i - 1].get("summary", "(empty summary)"))
            elif dry_run:
                lines.append("")
                lines.append("*(dry-run — no summary generated)*")
            else:
                err = summaries[i - 1].get("error", "unknown") if i <= len(summaries) else "not run"
                lines.append("")
                lines.append(f"*(summary failed: {err})*")
            lines.append("")
    else:
        lines.append("(no files selected for summary)")
        lines.append("")

    lines += [
        "## Risk Hints",
        "",
    ]
    if risk_hints:
        for h in risk_hints:
            lines.append(f"- {h}")
    else:
        lines.append("(no specific risks detected)")
    lines.append("")

    lines += [
        "## Context Budget",
        "",
        f"| Item | Est. Tokens |",
        f"|------|-------------|",
        f"| Repo map | ~{context_budget['repo_map_tokens']:,} |",
        f"| Summaries | ~{context_budget['summaries_tokens']:,} |",
        f"| **Total** | **~{context_budget['estimated_tokens']:,}** |",
        f"| Budget limit | {context_budget['budget_limit']:,} |",
        "",
    ]

    lines += [
        "## Suggested Next Calls",
        "",
    ]
    for c in suggested_calls:
        lines.append(f"- `{c}`")
    lines.append("")

    lines += [
        "## What NOT to Read First",
        "",
    ]
    if what_not_to_read:
        for w in what_not_to_read:
            lines.append(f"- {w}")
    else:
        lines.append("(nothing excluded — project is small/focused)")
    lines.append("")

    lines += [
        "---",
        "",
        "**Advisory only.** No files were modified. No hooks or gates triggered.",
        f"Generated by `{GENERATOR_ID}`.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Task Bootstrap — generate project context package",
    )
    parser.add_argument("--project", required=True, help="Target project root")
    parser.add_argument("--task", default="", help="Optional task description")
    parser.add_argument("--max-summaries", type=int, default=3,
                        help="Max files to LLM-summarize (default: 3)")
    parser.add_argument("--budget", type=int, default=6000,
                        help="Approximate token budget (default: 6000)")
    parser.add_argument("--no-summaries", action="store_true",
                        help="Skip LLM summaries")
    parser.add_argument("--json", action="store_true",
                        help="Print JSON to stdout")
    parser.add_argument("--out-dir", default="",
                        help="Output directory (default: .local_llm_out/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="No LLM calls; repo_map + file list only")
    args = parser.parse_args()

    project = Path(args.project)
    if not project.exists() or not project.is_dir():
        print(f"ERROR: Project path does not exist or is not a directory: "
              f"{args.project}", file=sys.stderr)
        return 2

    # Determine output directory
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = Path(".local_llm_out")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: repo_map
    print("task_bootstrap: generating repo map...", file=sys.stderr)
    try:
        repo_map = build_repo_map(project.resolve(), max_files=None)
    except Exception as e:
        print(f"ERROR: repo_map failed: {e}", file=sys.stderr)
        return 1

    if not repo_map.get("ok"):
        err = repo_map.get("error", "unknown repo_map error")
        print(f"ERROR: repo_map returned fail: {err}", file=sys.stderr)
        return 1

    files = repo_map.get("files", [])
    git_info = _get_git_info(project.resolve())

    # Phase 2: select files
    instruction_files = _select_instruction_files(files)
    max_summaries = args.max_summaries
    do_summaries = not args.no_summaries and not args.dry_run

    selected = _select_summary_candidates(files, args.task, max_summaries)

    # Phase 3: run summaries (if enabled)
    summaries: list[dict] = []
    summary_requested = do_summaries and len(selected) > 0
    if do_summaries:
        for s in selected:
            file_abs = str(project.resolve() / s["path"])
            print(f"task_bootstrap: summarizing {s['path']}...", file=sys.stderr)
            result = _run_summary(file_abs)
            summaries.append(result)
            if not result["ok"]:
                print(f"  WARNING: summary failed for {s['path']}: "
                      f"{result.get('error', '?')}", file=sys.stderr)
            else:
                print(f"  OK: {len(result.get('summary', ''))} chars", file=sys.stderr)
    else:
        summaries = [{"ok": False, "summary": "", "error": "skipped"} for _ in selected]

    # Phase 4: build output
    risk_hints = _build_risk_hints(repo_map)
    suggested_calls = _build_suggested_calls(selected, str(project.resolve()))
    context_budget = _build_context_budget(repo_map, summaries, args.budget)
    what_not_to_read = _build_what_not_to_read(
        repo_map, instruction_files, selected,
    )

    # Entrypoints list
    entrypoint_list = [
        f["path"] for f in files if f.get("entrypoint")
    ][:20]
    subsystem_list = sorted(repo_map.get("subsystems", {}).keys())

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"{ts}_bootstrap.md"
    json_path = out_dir / f"{ts}_bootstrap.json"

    # Build markdown
    md_content = _build_markdown(
        str(project.resolve()), args.task, git_info, repo_map,
        instruction_files, selected, risk_hints, suggested_calls,
        context_budget, what_not_to_read, summaries, args.dry_run,
    )
    md_path.write_text(md_content, encoding="utf-8")
    print(f"task_bootstrap: markdown → {md_path}", file=sys.stderr)

    # Build JSON
    json_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATOR_ID,
        "project_root": str(project.resolve()),
        "task_description": args.task or None,
        "git": git_info,
        "repo_map_summary": {
            "total_files": repo_map["summary"].get("total_files", 0),
            "source_files": repo_map["summary"].get("source_files", 0),
            "test_files": repo_map["summary"].get("test_files", 0),
            "doc_files": repo_map["summary"].get("docs_files", 0),
            "config_files": repo_map["summary"].get("config_files", 0),
            "subsystems": subsystem_list,
            "entrypoints": entrypoint_list,
        },
        "instruction_files": [
            {
                "path": f["path"],
                "role": f.get("role", "unknown"),
                "size_chars": f.get("size", 0),
            }
            for f in instruction_files
        ],
        "selected_files": [
            {
                "path": s["path"],
                "selection_reason": s.get("selection_reason", "unknown"),
                "size_chars": s.get("size", 0),
                "summary_status": (
                    "ok" if i < len(summaries) and summaries[i].get("ok")
                    else "failed" if i < len(summaries) and not summaries[i].get("ok")
                    else "skipped"
                ),
                "summary": (
                    summaries[i].get("summary", "")[:3000]
                    if i < len(summaries) else ""
                ),
            }
            for i, s in enumerate(selected)
        ],
        "risk_hints": risk_hints,
        "suggested_next_calls": suggested_calls,
        "context_budget": context_budget,
        "what_not_to_read_first": what_not_to_read,
        "output_files": {
            "markdown": str(md_path),
            "json": str(json_path),
        },
        "advisory_only": True,
    }
    json_path.write_text(
        json.dumps(json_doc, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"task_bootstrap: json → {json_path}", file=sys.stderr)

    if args.json:
        print(json.dumps(json_doc, indent=2, ensure_ascii=False))

    # Determine exit code
    if summary_requested:
        ok_count = sum(1 for s in summaries if s.get("ok"))
        if ok_count == 0:
            print("ERROR: all summaries failed", file=sys.stderr)
            return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
