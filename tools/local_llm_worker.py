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
}


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


@dataclass
class WorkerOutput:
    task: str = ""
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
    created_at: str = ""
    truncated_files: list = field(default_factory=list)
    truncation_report: list = field(default_factory=list)
    total_input_chars: int = 0
    included_input_chars: int = 0


def is_blocked_path(path: Path) -> bool:
    parts = path.parts
    for part in parts:
        if part in BLOCKED_PATHS:
            return True
    if path.suffix in BLOCKED_EXTENSIONS:
        return True
    if path.name in BLOCKED_FILENAMES:
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


def build_prompt(task: str, content: str, config: WorkerConfig) -> tuple[str, str]:
    task_prompt = TASK_PROMPTS.get(task, f"Analyze the following content for task: {task}")
    if "{target_language}" in task_prompt:
        task_prompt = task_prompt.replace("{target_language}", config.target_language)
    if "{style}" in task_prompt:
        task_prompt = task_prompt.replace("{style}", config.style)

    system = SYSTEM_PROMPT_BASE + f"\nTask: {task}\n"
    user = f"{task_prompt}\n\n---\n\n{content}"
    return system, user


def call_ollama(system: str, user: str, config: WorkerConfig) -> str:
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
    return data.get("message", {}).get("content", "")


def call_openai_compat(system: str, user: str, config: WorkerConfig) -> str:
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
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


def call_model(system: str, user: str, config: WorkerConfig) -> str:
    if config.provider == "ollama":
        return call_ollama(system, user, config)
    elif config.provider == "openai-compatible":
        return call_openai_compat(system, user, config)
    else:
        raise ValueError(f"Unknown provider: {config.provider}")


def parse_structured(raw: str, task: str) -> dict:
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
        if any(kw in lower for kw in ["must read", "must inspect", "controller must"]):
            parsed["must_read"].append(line.strip())
        if any(kw in lower for kw in ["risk", "danger", "warning", "concern"]):
            parsed["risks"].append(line.strip())
        if any(kw in lower for kw in ["test gap", "missing test", "untested", "no test"]):
            parsed["test_gaps"].append(line.strip())
        if any(kw in lower for kw in ["uncertain", "unclear", "insufficient", "unknown", "unsure"]):
            parsed["uncertain_points"].append(line.strip())

    file_pattern = re.compile(r'[\w./\\-]+\.\w{1,10}')
    for match in file_pattern.finditer(raw):
        candidate = match.group()
        if candidate not in parsed["key_files"] and "/" in candidate or "\\" in candidate:
            parsed["key_files"].append(candidate)

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
    config.provider = (
        args.provider
        or os.environ.get("LOCAL_LLM_PROVIDER")
        or "ollama"
    )
    config.model = (
        args.model
        or os.environ.get("LOCAL_LLM_MODEL")
        or profile.get("model", "")
    )
    config.profile = profile_name

    env_base = os.environ.get("LOCAL_LLM_BASE_URL", "")
    if config.provider == "ollama":
        config.base_url = args.base_url or env_base or "http://localhost:11434"
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
    return config


def gather_input(args: argparse.Namespace, config: WorkerConfig) -> tuple[str, dict, list[str], list[dict]]:
    """Returns (content, input_meta, warnings, truncation_report)."""
    warnings = []
    truncation_report = []
    input_meta = {"path": None, "stdin": False, "max_files": None, "max_chars": config.max_chars}

    if args.stdin:
        content = sys.stdin.read()
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
        return content, input_meta, warnings, truncation_report

    return "", input_meta, [f"Target not found: {target}"], truncation_report


def run(args: argparse.Namespace) -> int:
    config = resolve_config(args)

    output = WorkerOutput(
        task=args.task,
        profile=config.profile,
        model=config.model,
        provider=config.provider,
        base_url=config.base_url,
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
        output.warnings.append("No model available")
        json_path, md_path = save_output(output, config)
        print(f"ERROR: {output.error}", file=sys.stderr)
        print(f"JSON: {json_path}")
        return 1

    content, input_meta, gather_warnings, trunc_report = gather_input(args, config)
    output.input = input_meta
    output.warnings.extend(gather_warnings)
    output.truncation_report = trunc_report
    output.truncated_files = [r["path"] for r in trunc_report]
    output.total_input_chars = len(content) + sum(r.get("original_chars", 0) - r.get("included_chars", 0) for r in trunc_report)
    output.included_input_chars = len(content)

    if not content:
        output.error = "No input content to analyze"
        output.warnings.append("Empty input")
        json_path, md_path = save_output(output, config)
        print(f"ERROR: {output.error}", file=sys.stderr)
        print(f"JSON: {json_path}")
        return 1

    system, user = build_prompt(args.task, content, config)

    try:
        print(f"Calling {config.provider} model {config.model}...", file=sys.stderr)
        raw_result = call_model(system, user, config)
    except requests.exceptions.Timeout:
        output.error = f"Model call timed out after {config.timeout}s"
        json_path, md_path = save_output(output, config)
        print(f"ERROR: {output.error}", file=sys.stderr)
        print(f"JSON: {json_path}")
        return 1
    except requests.exceptions.ConnectionError:
        output.error = f"Cannot connect to {config.provider} at {config.base_url}"
        json_path, md_path = save_output(output, config)
        print(f"ERROR: {output.error}", file=sys.stderr)
        print(f"JSON: {json_path}")
        return 1
    except Exception as e:
        output.error = f"Model call failed: {e}"
        json_path, md_path = save_output(output, config)
        print(f"ERROR: {output.error}", file=sys.stderr)
        print(f"JSON: {json_path}")
        return 1

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

    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
