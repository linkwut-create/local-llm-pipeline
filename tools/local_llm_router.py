#!/usr/bin/env python3
"""
Local LLM Router — selects the right profile/model and delegates to the worker.

Usage:
    python tools/local_llm_router.py summarize-file README.md
    python tools/local_llm_router.py summarize-tree src --max-files 30
    python tools/local_llm_router.py generate-test-plan src/example.py
    git diff | python tools/local_llm_router.py review-diff --stdin
    python tools/local_llm_router.py risk-analysis docs/plan.md
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"
TASKS_PATH = SCRIPT_DIR / "local_llm_tasks.json"
WORKER_PATH = SCRIPT_DIR / "local_llm_worker.py"


def load_json(path: Path) -> dict:
    if not path.exists():
        print(f"WARNING: {path} not found", file=sys.stderr)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_ollama_models() -> list[str]:
    try:
        output = subprocess.check_output(
            ["ollama", "list"], text=True, stderr=subprocess.DEVNULL
        )
        lines = output.strip().splitlines()[1:]
        return [line.split()[0] for line in lines if line.strip()]
    except Exception:
        return []


def resolve_profile(task: str, profile_override: str | None, model_override: str | None) -> tuple[str, str, str]:
    """Returns (profile_name, model_name, risk_level)."""
    tasks_data = load_json(TASKS_PATH)
    profiles_data = load_json(PROFILES_PATH)

    task_conf = tasks_data.get("tasks", {}).get(task, {})
    profile_name = profile_override or task_conf.get("default_profile", "fast_summary")
    profile = profiles_data.get("profiles", {}).get(profile_name, {})

    model = model_override or profile.get("model", "")
    risk = task_conf.get("risk", profile.get("risk_level", "unknown"))

    return profile_name, model, risk


def check_model_available(model: str, available: list[str]) -> bool:
    if not model:
        return False
    for m in available:
        if m == model or m.startswith(model.split(":")[0]):
            return True
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/local_llm_router.py <task> [target] [options]", file=sys.stderr)
        print("\nAvailable tasks:", file=sys.stderr)
        tasks_data = load_json(TASKS_PATH)
        for task_name, conf in tasks_data.get("tasks", {}).items():
            risk = conf.get("risk", "?")
            profile = conf.get("default_profile", "?")
            print(f"  {task_name:30s} risk={risk:12s} profile={profile}", file=sys.stderr)
        sys.exit(1)

    task = sys.argv[1]

    passthrough_args = sys.argv[2:]

    profile_override = None
    model_override = None
    filtered_args = []
    i = 0
    while i < len(passthrough_args):
        arg = passthrough_args[i]
        if arg == "--profile" and i + 1 < len(passthrough_args):
            profile_override = passthrough_args[i + 1]
            i += 2
            continue
        elif arg == "--model" and i + 1 < len(passthrough_args):
            model_override = passthrough_args[i + 1]
            i += 2
            continue
        else:
            filtered_args.append(arg)
            i += 1

    profile_name, model, risk = resolve_profile(task, profile_override, model_override)

    available_models = get_ollama_models()

    if model and not check_model_available(model, available_models):
        print(f"WARNING: Model '{model}' not found in ollama list.", file=sys.stderr)
        print("Available models:", file=sys.stderr)
        for m in available_models[:20]:
            print(f"  - {m}", file=sys.stderr)
        if available_models:
            print(f"\nFalling back to first available: {available_models[0]}", file=sys.stderr)
            model = available_models[0]
        else:
            print("ERROR: No models available. Is Ollama running?", file=sys.stderr)
            sys.exit(1)

    print(f"Router: task={task} profile={profile_name} model={model} risk={risk}", file=sys.stderr)

    if risk in ("high",):
        print(f"NOTE: High-risk task. Controller MUST verify output.", file=sys.stderr)

    cmd = [
        sys.executable, str(WORKER_PATH),
        task,
        "--profile", profile_name,
        "--model", model,
    ] + filtered_args

    has_stdin = "--stdin" in filtered_args
    if has_stdin:
        stdin_data = sys.stdin.read() if not sys.stdin.isatty() else ""
        result = subprocess.run(cmd, input=stdin_data, text=True, capture_output=False)
    else:
        result = subprocess.run(cmd, text=True, capture_output=False)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
