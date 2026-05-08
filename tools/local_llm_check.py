#!/usr/bin/env python3
"""
Local LLM environment health check.

Checks Python, requests, git root, Ollama, OpenAI-compatible server,
scans real available models, and recommends profile assignments.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OLLAMA_BASE = "http://localhost:11434"
OPENAI_COMPAT_BASE = "http://localhost:8080"
PROFILES_PATH = Path(__file__).parent / "local_llm_profiles.json"
OUTPUT_DIR_NAME = ".local_llm_out"

MODEL_HINTS = {
    "fast_summary": {
        "keywords": ["gemma-4-e4b", "gemma4:e4b", "qwen3.5-9b", "gpt-oss-20b", "minicpm", "deepseek-ocr", "glm-ocr"],
        "prefer_small": True,
        "description": "lightweight model for fast summarization",
    },
    "code_worker": {
        "keywords": ["coder", "qwen3-coder", "qwen3.5-9b", "qwen3.6:27b", "gpt-oss-20b"],
        "prefer_small": False,
        "description": "coder model for test plans, TODO extraction",
    },
    "diff_reviewer": {
        "keywords": ["coder", "qwen3-coder", "qwen3.5-27b", "qwen3.6:27b", "qwen3.5-35b"],
        "prefer_small": False,
        "description": "stronger coder model for diff review",
    },
    "deep_reviewer": {
        "keywords": ["mistral-medium", "mistral-small-4", "qwen3.5-35b", "qwen3-coder-next", "llama4", "nemotron-3-super", "qwen3.5-122b"],
        "prefer_small": False,
        "description": "large model for deep code review",
    },
    "reasoning_checker": {
        "keywords": ["reasoning", "deepseek-r1", "qwen3.5-27b-reasoning"],
        "prefer_small": False,
        "description": "reasoning model for risk analysis and logic checks",
    },
    "translation": {
        "keywords": ["translategemma", "qwen3.5-9b", "qwen3.6:27b", "gemma4:26b", "glm-4"],
        "prefer_small": False,
        "description": "model with good multilingual / Chinese capability",
    },
}

SKIP_SUFFIXES = ["-original", "-agentprefill", "-toolfix", "-agent"]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    data: Any = None


def check_python() -> CheckResult:
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return CheckResult("python", True, f"Python {v}")


def check_requests() -> CheckResult:
    try:
        import requests  # noqa: F401
        return CheckResult("requests", True, f"requests {requests.__version__}")
    except ImportError:
        return CheckResult("requests", False, "missing — run: pip install requests")


def check_git_root() -> CheckResult:
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        return CheckResult("git_root", True, root)
    except Exception:
        return CheckResult("git_root", False, "not inside a git repository")


def check_output_dir() -> CheckResult:
    git_result = check_git_root()
    if git_result.ok:
        out_dir = Path(git_result.detail) / OUTPUT_DIR_NAME
    else:
        out_dir = Path.cwd() / OUTPUT_DIR_NAME
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        test_file = out_dir / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
        return CheckResult("output_dir", True, str(out_dir))
    except Exception as e:
        return CheckResult("output_dir", False, f"cannot write to {out_dir}: {e}")


def check_ollama() -> CheckResult:
    try:
        import requests
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        return CheckResult("ollama", True, f"{len(models)} models available", data=models)
    except Exception as e:
        return CheckResult("ollama", False, f"Ollama not reachable: {e}")


def check_openai_compat() -> CheckResult:
    try:
        import requests
        resp = requests.get(f"{OPENAI_COMPAT_BASE}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [m.get("id", m.get("name", "?")) for m in data.get("data", [])]
        return CheckResult("openai_compat", True, f"{len(models)} models", data=models)
    except Exception as e:
        return CheckResult("openai_compat", False, f"not reachable: {e}")


def run_ollama_list() -> CheckResult:
    try:
        output = subprocess.check_output(["ollama", "list"], text=True, stderr=subprocess.DEVNULL)
        lines = [l.strip() for l in output.strip().splitlines()[1:] if l.strip()]
        names = []
        for line in lines:
            parts = line.split()
            if parts:
                names.append(parts[0])
        return CheckResult("ollama_list", True, f"{len(names)} models via CLI", data=names)
    except Exception as e:
        return CheckResult("ollama_list", False, f"ollama list failed: {e}")


def is_variant(name: str) -> bool:
    for suffix in SKIP_SUFFIXES:
        if name.endswith(suffix) or name.endswith(f"{suffix}:latest"):
            return True
    return False


def deduplicate_models(models: list[str]) -> list[str]:
    seen_digests: dict[str, str] = {}
    result = []
    for name in models:
        base = name
        for suffix in SKIP_SUFFIXES:
            if base.endswith(suffix) or base.endswith(f"{suffix}:latest"):
                continue
        if not is_variant(name):
            result.append(name)
    return result


def estimate_size_gb(name: str) -> float:
    patterns = [
        (r"(\d+)[bB]", lambda m: float(m.group(1))),
        (r"(\d+\.\d+)[bB]", lambda m: float(m.group(1))),
    ]
    for pat, extractor in patterns:
        match = re.search(pat, name)
        if match:
            return extractor(match)
    return 30.0


def recommend_profiles(models: list[str]) -> dict[str, dict]:
    base_models = deduplicate_models(models)
    recommendations = {}

    for profile_name, hints in MODEL_HINTS.items():
        candidates = []
        for model in base_models:
            model_lower = model.lower()
            for kw in hints["keywords"]:
                if kw.lower() in model_lower:
                    candidates.append(model)
                    break

        if not candidates:
            candidates = base_models[:3] if base_models else []

        if hints.get("prefer_small"):
            candidates.sort(key=lambda n: estimate_size_gb(n))
        else:
            candidates.sort(key=lambda n: estimate_size_gb(n), reverse=True)

        chosen = candidates[0] if candidates else None
        recommendations[profile_name] = {
            "model": chosen,
            "candidates": candidates[:5],
            "description": hints["description"],
        }

    return recommendations


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    print_section("Local LLM Environment Health Check")
    print(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"  CWD:  {os.getcwd()}")

    checks = [
        check_python(),
        check_requests(),
        check_git_root(),
        check_output_dir(),
    ]

    print_section("Basic Environment")
    for c in checks:
        status = "OK" if c.ok else "FAIL"
        print(f"  [{status:4s}] {c.name}: {c.detail}")

    print_section("Ollama CLI")
    cli_result = run_ollama_list()
    print(f"  [{('OK' if cli_result.ok else 'FAIL'):4s}] {cli_result.detail}")

    print_section("Ollama API")
    api_result = check_ollama()
    print(f"  [{('OK' if api_result.ok else 'FAIL'):4s}] {api_result.detail}")

    print_section("OpenAI-Compatible Server")
    oai_result = check_openai_compat()
    print(f"  [{('OK' if oai_result.ok else 'FAIL'):4s}] {oai_result.detail}")

    all_models = []
    if cli_result.ok and cli_result.data:
        all_models = cli_result.data
    elif api_result.ok and api_result.data:
        all_models = api_result.data

    if all_models:
        base_models = deduplicate_models(all_models)
        print_section(f"Available Base Models ({len(base_models)})")
        for m in base_models:
            print(f"  - {m}")

        print_section("Recommended Profiles")
        recs = recommend_profiles(all_models)
        for profile, info in recs.items():
            model_str = info["model"] or "(none found)"
            print(f"\n  {profile}:")
            print(f"    Model:       {model_str}")
            print(f"    Description: {info['description']}")
            if info["candidates"]:
                print(f"    Candidates:  {', '.join(info['candidates'][:3])}")

        if PROFILES_PATH.exists():
            print(f"\n  Existing profiles config: {PROFILES_PATH}")
        else:
            print(f"\n  No profiles config yet at: {PROFILES_PATH}")
            print("  Run the router to auto-generate, or create manually.")
    else:
        print_section("No Models Found")
        print("  Cannot recommend profiles without available models.")
        print("  Ensure Ollama is running: ollama serve")

    print_section("Example Commands")
    examples = [
        "python tools/local_llm_check.py",
        "python tools/local_llm_router.py summarize-file README.md",
        "python tools/local_llm_router.py summarize-tree src --max-files 30",
        "python tools/local_llm_router.py extract-todos src",
        "python tools/local_llm_router.py generate-test-plan src/example.py",
        'git diff | python tools/local_llm_router.py review-diff --stdin',
        "python tools/local_llm_router.py risk-analysis docs/plan.md",
    ]
    for ex in examples:
        print(f"  {ex}")

    all_ok = all(c.ok for c in checks) and (cli_result.ok or api_result.ok)
    print_section("Summary")
    if all_ok:
        print("  Environment is ready.")
    else:
        print("  Some checks failed. Review above for details.")
        if not cli_result.ok and not api_result.ok:
            print("  CRITICAL: No LLM backend reachable.")
            print("  Start Ollama: ollama serve")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
