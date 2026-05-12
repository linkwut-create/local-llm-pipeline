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


def _try_audit_start(task: str, profile: str, model: str,
                     args: list[str], has_stdin: bool):
    """Record invocation start to MCP audit logger. Never raises."""
    try:
        from mcp_audit_logger import write_audit_event
        input_summary = "stdin" if has_stdin else (
            args[0] if args else "no args"
        )
        write_audit_event(None, {
            "event_type": "mcp_invocation_started",
            "task_type": task,
            "tool_name": f"local_llm_router:{task}",
            "profile_name": profile,
            "model_name": model,
            "command": f"python tools/local_llm_router.py {task}",
            "input_summary": input_summary,
            "result_status": "started",
        })
    except Exception:
        pass


def _try_audit_result(task: str, profile: str, model: str,
                      returncode: int, elapsed_ms: int):
    """Record invocation result to MCP audit logger. Never raises."""
    try:
        from mcp_audit_logger import write_audit_event, write_failure_event
        if returncode == 0:
            write_audit_event(None, {
                "event_type": "mcp_invocation_finished",
                "task_type": task,
                "tool_name": f"local_llm_router:{task}",
                "profile_name": profile,
                "model_name": model,
                "result_status": "passed",
                "output_summary": f"Completed in {elapsed_ms}ms",
            })
        else:
            write_audit_event(None, {
                "event_type": "mcp_invocation_failed",
                "task_type": task,
                "tool_name": f"local_llm_router:{task}",
                "profile_name": profile,
                "model_name": model,
                "result_status": "failed",
                "output_summary": f"Exit code {returncode} in {elapsed_ms}ms",
            })
            # Map return code to failure type
            failure_map = {
                1: "tool_failed",
                49: "model_unavailable",
            }
            write_failure_event(None, {
                "failure_type": failure_map.get(returncode, "tool_failed"),
                "severity": "high" if returncode != 0 else "low",
                "tool_name": f"local_llm_router:{task}",
                "command": f"python tools/local_llm_router.py {task}",
                "exit_code": returncode,
                "resolved": 0,
            })
    except Exception:
        pass


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
    profiles_data = load_json(PROFILES_PATH)

    if model and not check_model_available(model, available_models):
        print(f"WARNING: Model '{model}' not found in ollama list.", file=sys.stderr)
        # Try profile candidates in order (v0.9.5: candidates-based fallback only)
        profile_cfg = profiles_data.get("profiles", {}).get(profile_name, {})
        candidates = profile_cfg.get("candidates", [])
        fallback = None
        for c in candidates:
            if check_model_available(c, available_models):
                fallback = c
                break
        if fallback:
            print(f"Falling back to profile candidate: {fallback}", file=sys.stderr)
            model = fallback
        else:
            print(
                f"ERROR: Requested model '{model}' not available and no profile "
                f"candidates are reachable.\n"
                f"  Profile: {profile_name}\n"
                f"  Candidates: {candidates or '(none)'}\n"
                f"  Available models ({len(available_models)}): "
                f"{', '.join(available_models[:10])}",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"Router: task={task} profile={profile_name} model={model} risk={risk}", file=sys.stderr)

    if risk in ("high",):
        print(f"NOTE: High-risk task. Controller MUST verify output.", file=sys.stderr)

    # Apply profile-specific env overrides (e.g. llama.cpp endpoint for MTP profiles)
    subprocess_env = os.environ.copy()
    profile_cfg = profiles_data.get("profiles", {}).get(profile_name, {})
    env_override = profile_cfg.get("_env", "")
    if env_override:
        for part in env_override.split(" "):
            if "=" in part:
                k, v = part.split("=", 1)
                subprocess_env[k] = v
                print(f"Router: {profile_name} → env {k}={v}", file=sys.stderr)

    cmd = [
        sys.executable, str(WORKER_PATH),
        task,
        "--profile", profile_name,
        "--model", model,
    ] + filtered_args

    import time
    started = time.time()
    has_stdin = "--stdin" in filtered_args

    # MCP-AUDIT-5: record invocation start
    _try_audit_start(task, profile_name, model, filtered_args, has_stdin)
    if has_stdin:
        stdin_data = sys.stdin.buffer.read().decode("utf-8", errors="replace") if not sys.stdin.isatty() else ""
        result = subprocess.run(cmd, input=stdin_data, text=True,
                                encoding="utf-8", errors="replace",
                                capture_output=False, env=subprocess_env)
    else:
        result = subprocess.run(cmd, text=True,
                                encoding="utf-8", errors="replace",
                                capture_output=False, env=subprocess_env)
    elapsed_ms = int((time.time() - started) * 1000)

    # MCP-AUDIT-5: record invocation result
    _try_audit_result(task, profile_name, model, result.returncode, elapsed_ms)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
