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
from urllib.request import Request, urlopen
from urllib.error import URLError

SCRIPT_DIR = Path(__file__).parent
PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"
TASKS_PATH = SCRIPT_DIR / "local_llm_tasks.json"
WORKER_PATH = SCRIPT_DIR / "local_llm_worker.py"

ALLOWED_ENV_VARS = {"LOCAL_LLM_BASE_URL"}

# Lazy import: health_store lives in the same directory but is loaded on
# demand so this module stays importable in environments where the
# runtime out dir does not exist yet.
sys.path.insert(0, str(SCRIPT_DIR))


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


def probe_llamacpp_endpoint(base_url: str, timeout: int = 5) -> bool:
    """Quick health check against a llama.cpp-compatible /models endpoint."""
    url = base_url.rstrip("/") + "/models"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_profile(task: str, profile_override: str | None, model_override: str | None,
                    profiles_data: dict | None = None, tasks_data: dict | None = None) -> tuple[str, str, str]:
    """Returns (profile_name, model_name, risk_level)."""
    if tasks_data is None:
        tasks_data = load_json(TASKS_PATH)
    if profiles_data is None:
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


def _resolve_health(profile_name: str, profile: dict,
                    health_data: dict | None) -> dict:
    """Pick the health record for `profile_name` from one of three
    sources, in priority order.

    1. Explicit `health_data` argument (used by tests / callers that
       already loaded the runtime doc once).
    2. Runtime health store (`.local_llm_out/local_llm_health.json`)
       via `tools.health_store.load_profile_health` — the production
       path after MCP Health Telemetry Isolation P1-H.2.
    3. Legacy `profile["_health"]` from `local_llm_profiles.json` —
       kept for `tests/test_layer4_quality.py` compatibility and for
       any environment where the helper module is unavailable.

    Returns `{}` when no source has data.
    """
    if health_data is not None:
        if isinstance(health_data, dict):
            profiles_key = health_data.get("profiles")
            if isinstance(profiles_key, dict) and profile_name in profiles_key:
                h = profiles_key.get(profile_name)
                if isinstance(h, dict):
                    return h
            if profile_name in health_data and isinstance(
                health_data[profile_name], dict
            ):
                return health_data[profile_name]
        return {}
    try:
        from health_store import load_profile_health
        runtime = load_profile_health(profile_name)
        if runtime:
            return runtime
    except Exception:
        pass
    legacy = profile.get("_health", {}) if isinstance(profile, dict) else {}
    return legacy if isinstance(legacy, dict) else {}


def is_profile_healthy(profile_name: str, profiles_data: dict,
                       health_data: dict | None = None) -> bool:
    """Check if a profile is healthy enough to use.

    Returns False if consecutive_failures >= 2 or success_rate < 0.5.
    This causes the router to skip unhealthy profiles and use candidates instead.

    `health_data` (optional, P1-H.2): pass a pre-loaded runtime health
    document to avoid repeated disk reads. Shape may be either the
    full runtime doc (`{"profiles": {name: {...}}}`) or a flat
    `{name: {...}}` map. When omitted, the runtime health store is
    consulted; if that has no data, legacy `profile["_health"]` is
    used (test compatibility).
    """
    profile = profiles_data.get("profiles", {}).get(profile_name, {})
    h = _resolve_health(profile_name, profile, health_data)
    if not h:
        return True  # No health data — assume healthy
    if h.get("consecutive_failures", 0) >= 2:
        return False
    if h.get("success_rate", 1.0) < 0.5:
        return False
    return True


def _try_audit_start(task: str, profile: str, model: str,
                     args: list[str], has_stdin: bool):
    """Record invocation start to MCP audit logger. Never raises."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
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
        sys.path.insert(0, str(SCRIPT_DIR))
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


def cmd_health_report():
    """Print model health report.

    After MCP Health Telemetry Isolation P1-H.3 the report reads runtime
    health from `.local_llm_out/local_llm_health.json` instead of each
    profile's `_health` block (which no longer exists in profiles.json
    as of P1-H.2). Static profile metadata (name, model) still comes
    from profiles.json.

    Falls back to the legacy `cfg["_health"]` block when runtime data
    is unavailable for a profile — keeps the report working in
    synthetic test setups and any future profile that re-introduces
    the legacy field locally.
    """
    profiles_data = load_json(PROFILES_PATH)
    profiles = profiles_data.get("profiles", {})

    runtime_profiles: dict = {}
    try:
        from health_store import load_health
        runtime_profiles = load_health().get("profiles", {}) or {}
    except Exception:
        runtime_profiles = {}

    print(f"{'Profile':30s} {'Model':40s} {'Success':>8s} {'Avg Lat':>8s} {'Timeouts':>8s} {'ConsecFail':>10s}")
    print("-" * 110)
    healthy = 0
    unhealthy = 0
    no_data = 0
    for name, cfg in sorted(profiles.items()):
        # Runtime wins by presence, not truthiness — an explicit empty
        # runtime record means "no data" rather than "fall back to
        # legacy stale data".
        if name in runtime_profiles:
            h = runtime_profiles[name] if isinstance(runtime_profiles[name], dict) else {}
        else:
            h = cfg.get("_health", {})
        if not h:
            no_data += 1
            continue
        rate = h.get("success_rate", 0)
        avg = h.get("avg_latency_s", 0)
        timeouts = h.get("last_timeout") or "-"
        cf = h.get("consecutive_failures", 0)
        model = cfg.get("model", "?")[:38]
        status = "OK" if rate >= 0.9 and cf == 0 else "WARN" if rate >= 0.7 else "DEGRADED"
        print(f"{name:30s} {model:40s} {rate:7.1%}  {avg:5.0f}s    {str(timeouts):>8s} {cf:>10}  {status}")
        if rate >= 0.9 and cf == 0:
            healthy += 1
        else:
            unhealthy += 1
    print(f"\nHealthy: {healthy}  Unhealthy: {unhealthy}  No health data: {no_data}")
    return 0


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

    if task == "health-report":
        sys.exit(cmd_health_report())

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
        elif arg == "--confirm-high-risk":
            i += 1
            continue
        else:
            filtered_args.append(arg)
            i += 1

    tasks_data = load_json(TASKS_PATH)
    profiles_data = load_json(PROFILES_PATH)

    profile_name, model, risk = resolve_profile(
        task, profile_override, model_override,
        profiles_data=profiles_data, tasks_data=tasks_data)
    profile_cfg = profiles_data.get("profiles", {}).get(profile_name, {})

    # Resolve model availability (with cross-backend fallback)
    if not profile_cfg.get("_env"):
        available_models = get_ollama_models()

        # Phase 3B: health-aware routing — check primary profile health
        if not is_profile_healthy(profile_name, profiles_data):
            print(f"WARNING: Profile '{profile_name}' is unhealthy — skipping.", file=sys.stderr)

        if model and not check_model_available(model, available_models):
            print(f"WARNING: Model '{model}' not found in ollama list.", file=sys.stderr)
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
                # Phase 2.1: cross-backend fallback via _llamacpp_profile
                task_conf = tasks_data.get("tasks", {}).get(task, {})
                llmacpp_name = task_conf.get("_llamacpp_profile", "")
                llmacpp_cfg = profiles_data.get("profiles", {}).get(llmacpp_name, {}) if llmacpp_name else {}
                if llmacpp_name and llmacpp_cfg:
                    if not is_profile_healthy(llmacpp_name, profiles_data):
                        print(
                            f"WARNING: Cross-backend profile '{llmacpp_name}' is unhealthy — skipped.",
                            file=sys.stderr,
                        )
                    else:
                        llmacpp_env = llmacpp_cfg.get("_env", "")
                        if llmacpp_env:
                            base_url = ""
                            for part in llmacpp_env.split(" "):
                                if part.startswith("LOCAL_LLM_BASE_URL="):
                                    base_url = part.split("=", 1)[1]
                            if base_url and probe_llamacpp_endpoint(base_url):
                                print(
                                    f"Cross-backend fallback: {profile_name} → {llmacpp_name} "
                                    f"({base_url})",
                                    file=sys.stderr,
                                )
                                profile_name = llmacpp_name
                                profile_cfg = llmacpp_cfg
                                model = llmacpp_cfg.get("model", "")
                                risk = task_conf.get("risk", llmacpp_cfg.get("risk_level", risk))
                            else:
                                print(
                                    f"WARNING: llama.cpp backend {base_url or '(unknown)'} not reachable. "
                                    f"Cannot use fallback profile '{llmacpp_name}'.",
                                    file=sys.stderr,
                                )
                if not profile_cfg.get("_env"):
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
    else:
        # Phase 2.2: pre-flight health check for _env (llama.cpp) profiles
        env_override = profile_cfg.get("_env", "")
        base_url = ""
        for part in env_override.split(" "):
            if part.startswith("LOCAL_LLM_BASE_URL="):
                base_url = part.split("=", 1)[1]
        if base_url:
            if probe_llamacpp_endpoint(base_url):
                print(f"Router: llama.cpp endpoint {base_url} health check OK", file=sys.stderr)
            else:
                print(f"WARNING: llama.cpp endpoint {base_url} not reachable.", file=sys.stderr)
                candidates = profile_cfg.get("candidates", [])
                fallback = None
                for c in candidates:
                    c_profile = profiles_data.get("profiles", {}).get(c, {})
                    if not c_profile.get("_env") and check_model_available(
                        c_profile.get("model", ""), get_ollama_models()
                    ):
                        fallback = c
                        break
                if fallback:
                    fb_cfg = profiles_data.get("profiles", {}).get(fallback, {})
                    print(f"Falling back to Ollama profile: {fallback} ({fb_cfg.get('model', '')})", file=sys.stderr)
                    profile_name = fallback
                    profile_cfg = fb_cfg
                    model = fb_cfg.get("model", model)
                    risk = fb_cfg.get("risk_level", risk)
                else:
                    print(
                        f"ERROR: llama.cpp endpoint {base_url} unreachable and no "
                        f"Ollama profile candidates available.",
                        file=sys.stderr,
                    )
                    sys.exit(1)

    print(f"Router: task={task} profile={profile_name} model={model} risk={risk}", file=sys.stderr)

    if risk in ("high",):
        if "--confirm-high-risk" not in sys.argv:
            print(
                f"ERROR: task={task} is risk=high. Pass --confirm-high-risk to proceed. "
                f"Controller MUST verify output.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"NOTE: High-risk task confirmed. Controller MUST verify output.", file=sys.stderr)

    # Apply profile-specific env overrides (e.g. llama.cpp endpoint for MTP profiles)
    subprocess_env = os.environ.copy()
    env_override = profile_cfg.get("_env", "")
    if env_override:
        for part in env_override.split(" "):
            if "=" in part:
                k, v = part.split("=", 1)
                if k in ALLOWED_ENV_VARS:
                    subprocess_env[k] = v
                    print(f"Router: {profile_name} → env {k}={v}", file=sys.stderr)
                else:
                    print(
                        f"WARNING: {profile_name} _env key '{k}' not in ALLOWED_ENV_VARS — skipped",
                        file=sys.stderr,
                    )

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
