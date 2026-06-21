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


def _resolve_ollama_base_url() -> str:
    base_url = os.environ.get("LOCAL_LLM_BASE_URL") or os.environ.get("OLLAMA_HOST")
    if not base_url:
        return "http://localhost:11434"
    if not base_url.startswith(("http://", "https://")):
        base_url = "http://" + base_url
    return base_url.rstrip("/")


def _get_ollama_models_from_api() -> list[str]:
    url = _resolve_ollama_base_url() + "/api/tags"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    models = payload.get("models", [])
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def get_ollama_models() -> list[str]:
    try:
        output = subprocess.check_output(
            ["ollama", "list"], text=True, stderr=subprocess.DEVNULL
        )
        lines = output.strip().splitlines()[1:]
        return [line.split()[0] for line in lines if line.strip()]
    except Exception:
        return _get_ollama_models_from_api()


def _get_openai_models_from_api(base_url: str) -> list[str]:
    """Query an OpenAI-compatible /v1/models endpoint (e.g. llama.cpp, LiteLLM)."""
    url = base_url.rstrip("/") + "/models"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("id") or entry.get("model") or ""
        if isinstance(mid, str) and mid:
            names.append(mid)
    return names


def get_available_models() -> list[str]:
    """Get available models from the configured backend.

    When LOCAL_LLM_BASE_URL points to a non-Ollama endpoint (e.g. LiteLLM,
    llama.cpp), model discovery goes through the OpenAI-compatible /v1/models
    endpoint first.  Falls back to Ollama when the OpenAI-compatible endpoint
    is unreachable or when the base URL still points at an Ollama port.
    """
    base_url = os.environ.get("LOCAL_LLM_BASE_URL", "")
    if base_url and ":11434" not in base_url and ":11436" not in base_url:
        models = _get_openai_models_from_api(base_url)
        if models:
            return models
    return get_ollama_models()


def probe_llamacpp_endpoint(base_url: str, timeout: int = 5) -> bool:
    """Quick health check against a llama.cpp-compatible /models endpoint."""
    url = base_url.rstrip("/") + "/models"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _get_service_for_profile(profile_name: str, profile_config: dict) -> str:
    """Get the systemd service name for a llama.cpp profile."""
    return profile_config.get("_service", "")


def _ensure_model_running(profile_name: str, profile_config: dict,
                          timeout: int = 60) -> bool:
    """Auto-start a llama.cpp systemd service if the model is not reachable.

    Returns True if the model is reachable (was already or started successfully).
    Only acts on profiles with _backend_class == "openai-compatible" and a _service field.
    """
    bc = profile_config.get("_backend_class", "")
    if bc != "openai-compatible":
        return True  # Not a llama.cpp profile, nothing to do

    service = _get_service_for_profile(profile_name, profile_config)
    if not service:
        return True  # No service configured, assume already running

    # Check direct llama.cpp port health (not LiteLLM proxy)
    port = profile_config.get("_port", 0)
    if not port:
        return True  # No port configured
    direct_url = f"http://127.0.0.1:{port}/v1"

    # Quick health check via SSH to zero12
    import subprocess
    result = subprocess.run(
        ["ssh", "zero12", f"curl -s --max-time 3 http://127.0.0.1:{port}/health"],
        timeout=10, capture_output=True, text=True,
    )
    if result.returncode == 0 and '"status":"ok"' in result.stdout:
        return True

    # Model not reachable — auto-start via SSH
    import subprocess
    print(
        f"Router: model {profile_name} not reachable, auto-starting {service}...",
        file=sys.stderr,
    )
    try:
        subprocess.run(
            ["ssh", "zero12", f"systemctl --user start {service}"],
            timeout=15, capture_output=True, text=True,
        )
    except Exception as e:
        print(f"WARNING: SSH start failed: {e}", file=sys.stderr)
        return False

    # Wait for health
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        if probe_llamacpp_endpoint(base_url, timeout=3):
            elapsed = timeout - (deadline - time.time())
            print(
                f"Router: {service} ready after {elapsed:.0f}s",
                file=sys.stderr,
            )
            return True
        print(".", end="", file=sys.stderr, flush=True)

    print(f" WARNING: {service} did not become ready within {timeout}s", file=sys.stderr)
    return False


# --- backend class eligibility (J-C5) ---

BACKEND_CLASS_AUTO_ALLOWED = {"ollama", "ollama_mtp_pending", "openai-compatible"}

BACKEND_CLASS_HEAVY = {"ollama_heavy_manual"}

BACKEND_CLASS_NOT_ELIGIBLE = {
    "llamacpp_unconfigured", "unavailable", "placeholder",
}


def get_backend_class(profile_config: dict) -> str:
    """Extract _backend_class from a profile config dict, defaulting to unknown."""
    bc = profile_config.get("_backend_class", "")
    if not bc:
        return "unknown"
    return bc


def is_profile_auto_eligible(profile_name: str, profile_config: dict,
                             explicit: bool = False,
                             task_risk: str | None = None) -> tuple[bool, str]:
    """Check whether a profile is eligible for selection.

    Returns (eligible, reason).
    - ollama / ollama_mtp_pending: always eligible
    - ollama_heavy_manual: only if explicit or task risk >= medium-high
    - llamacpp_unconfigured / unavailable / placeholder: only if explicit
    - unknown (missing _backend_class): allowed with warning for backward compat
    """
    bc = get_backend_class(profile_config)

    if bc in BACKEND_CLASS_AUTO_ALLOWED:
        return True, ""

    if bc in BACKEND_CLASS_HEAVY:
        if explicit:
            return True, ""
        # Allow heavy manual profiles for high-risk / deep review tasks
        if task_risk and task_risk in ("high", "medium-high"):
            return True, ""
        return False, (
            f"profile '{profile_name}' is {bc} — requires explicit --profile "
            f"or a high-risk task (current risk: {task_risk or 'unknown'})"
        )

    if bc in BACKEND_CLASS_NOT_ELIGIBLE:
        if explicit:
            return True, ""
        return False, (
            f"profile '{profile_name}' is {bc} — not auto-eligible. "
            f"Use --profile {profile_name} to override."
        )

    # unknown: allow with warning
    return True, ""


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

    # J-C5: check backend class eligibility (warning only — main() enforces)
    eligible, reason = is_profile_auto_eligible(
        profile_name, profile, explicit=bool(profile_override),
        task_risk=task_conf.get("risk"))
    if not eligible:
        print(f"WARNING: {reason}", file=sys.stderr)

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
    local_only = False
    cloud_ok = False
    privacy_strict = True  # default: strict privacy, no auto-upload
    positional_target = None
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
        elif arg == "--local-only":
            local_only = True
            i += 1
            continue
        elif arg == "--cloud-ok":
            cloud_ok = True
            privacy_strict = False  # explicit opt-in overrides strict privacy
            i += 1
            continue
        elif arg == "--no-cloud":
            local_only = True
            i += 1
            continue
        elif arg == "--privacy" and i + 1 < len(passthrough_args):
            if passthrough_args[i + 1] == "strict":
                privacy_strict = True
            elif passthrough_args[i + 1] == "relaxed":
                privacy_strict = False
            i += 2
            continue
        elif not arg.startswith("-") and positional_target is None:
            # The first bare positional argument is the target path and must be
            # placed before option flags when invoking local_llm_worker.py.
            positional_target = arg
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

    # J-C5: enforce backend class eligibility
    task_conf = tasks_data.get("tasks", {}).get(task, {})
    eligible, reason = is_profile_auto_eligible(
        profile_name, profile_cfg, explicit=bool(profile_override),
        task_risk=task_conf.get("risk"))
    if not eligible:
        print(f"ERROR: {reason}", file=sys.stderr)
        sys.exit(1)

    # Resolve model availability (with cross-backend fallback)
    if not profile_cfg.get("_env"):
        available_models = get_available_models()

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
                # Try auto-starting the model before falling back
                service = profile_cfg.get("_service", "")
                port = profile_cfg.get("_port", 0)
                if service and port:
                    print(f"Router: attempting auto-start {service}...", file=sys.stderr)
                    import subprocess as _subprocess, time as _time
                    try:
                        _subprocess.run(
                            ["ssh", "zero12", f"systemctl --user start {service}"],
                            timeout=15, capture_output=True, text=True)
                        deadline = _time.time() + 30
                        while _time.time() < deadline:
                            _time.sleep(2)
                            r = _subprocess.run(
                                ["ssh", "zero12", f"curl -s --max-time 2 http://127.0.0.1:{port}/health"],
                                timeout=10, capture_output=True, text=True)
                            if r.returncode == 0 and '"status":"ok"' in r.stdout:
                                print(f" {service} ready", file=sys.stderr)
                                break
                            print(".", end="", file=sys.stderr, flush=True)
                    except Exception as _e:
                        print(f" (unavailable: {_e})", file=sys.stderr)
                
                if not probe_llamacpp_endpoint(base_url):
                    print(f"WARNING: llama.cpp endpoint {base_url} not reachable.", file=sys.stderr)
                candidates = profile_cfg.get("candidates", [])
                fallback = None
                for c in candidates:
                    c_profile = profiles_data.get("profiles", {}).get(c, {})
                    # Check if candidate is an _env profile (llama.cpp/LiteLLM)
                    if c_profile.get("_env"):
                        c_env = c_profile.get("_env", "")
                        c_base = ""
                        for part in c_env.split(" "):
                            if part.startswith("LOCAL_LLM_BASE_URL="):
                                c_base = part.split("=", 1)[1]
                        if c_base and probe_llamacpp_endpoint(c_base):
                            fallback = c
                            break
                    elif check_model_available(c_profile.get("model", ""), get_ollama_models()):
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

    # Auto-start llama.cpp service if model not reachable
    _ensure_model_running(profile_name, profile_cfg)

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
    ]
    if positional_target is not None:
        cmd.append(positional_target)
    cmd.extend([
        "--profile", profile_name,
        "--model", model,
    ])
    cmd.extend(filtered_args)

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

    # ---- cloud escalation ----
    if result.returncode != 0 and not local_only:
        profile_is_cloud = profile_cfg.get("cloud", False)
        if profile_is_cloud:
            # Already tried cloud — don't escalate further
            print("Cloud model failed — no further escalation.", file=sys.stderr)
            sys.exit(result.returncode)

        # Check privacy before any cloud call
        input_data = ""
        if has_stdin:
            input_data = stdin_data
        else:
            # For non-stdin tasks, the target file content is in filtered_args
            input_data = " ".join(filtered_args)

        privacy_ok = True
        if privacy_strict and input_data:
            try:
                from deepseek_client import _check_privacy
                privacy_ok, privacy_reason = _check_privacy(input_data)
                if not privacy_ok:
                    print(f"Cloud escalation blocked by privacy gate: {privacy_reason}", file=sys.stderr)
            except ImportError:
                print("WARNING: deepseek_client not available for privacy check.", file=sys.stderr)

        # Only escalate if explicitly allowed (--cloud-ok) or profile has cloud trigger
        if cloud_ok or profile_cfg.get("_escalation_trigger"):
            try:
                from deepseek_client import should_escalate_to_cloud, resolve_escalation_profile, call_deepseek
                do_escalate, esc_level, esc_reason = should_escalate_to_cloud(
                    task, risk, local_failures=1,
                    privacy_ok=privacy_ok, cloud_ok=cloud_ok,
                )
                if do_escalate:
                    esc_profile = resolve_escalation_profile(profile_name, profiles_data, escalation_level=esc_level)
                    if esc_profile:
                        esc_model = esc_profile.get("model", "deepseek-v4-flash")
                        esc_thinking = esc_profile.get("thinking", False)
                        esc_effort = esc_profile.get("reasoning_effort", "low")
                        print(f"Escalating to cloud: {esc_model} (level={esc_level}, reason={esc_reason})", file=sys.stderr)

                        cloud_result = call_deepseek(
                            prompt=input_data[:200000],  # cap at 200K chars
                            model=esc_model,
                            thinking=esc_thinking,
                            reasoning_effort=esc_effort,
                        )
                        if cloud_result["ok"]:
                            print(cloud_result["content"])
                            print(f"\nCloud: {esc_model} ({cloud_result['elapsed_seconds']:.1f}s)", file=sys.stderr)
                            sys.exit(0)
                        else:
                            print(f"Cloud escalation failed: {cloud_result['error']}", file=sys.stderr)
                    else:
                        print(f"No escalation profile found for level {esc_level}", file=sys.stderr)
                else:
                    if result.returncode != 0:
                        print(f"Cloud escalation not triggered: {esc_reason}", file=sys.stderr)
            except ImportError:
                if cloud_ok:
                    print("WARNING: deepseek_client module not found. Cloud escalation unavailable.", file=sys.stderr)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
