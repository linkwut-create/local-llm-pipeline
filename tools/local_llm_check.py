#!/usr/bin/env python3
"""
Local LLM environment health check.

Checks Python, requests, git root, Ollama, OpenAI-compatible server,
scans real available models, and recommends profile assignments.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    requests = None

OLLAMA_BASE_DEFAULT = "http://localhost:11434"
OPENAI_COMPAT_BASE = "http://localhost:8080"

# llama.cpp MTP endpoints to check (remote GPU server + local)
_MTP_ENDPOINTS = [
    ("http://193.168.2.2:8080/v1", "zero12 Gemma4-26B-MTP"),
    ("http://193.168.2.2:8082/v1", "zero12 Qwen3.6-27B-MTP"),
    ("http://193.168.2.2:8083/v1", "zero12 Qwen3.6-35B-MoE-MTP"),
]


def resolve_ollama_base_url() -> tuple[str, str]:
    """Resolve Ollama base URL from env vars. Returns (base_url, source_description)."""
    env_base = os.environ.get("LOCAL_LLM_BASE_URL", "")
    if env_base:
        return env_base, "LOCAL_LLM_BASE_URL"
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    if ollama_host:
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"
        return ollama_host, "OLLAMA_HOST"
    return OLLAMA_BASE_DEFAULT, "default"
PROFILES_PATH = Path(__file__).parent / "local_llm_profiles.json"
OUTPUT_DIR_NAME = ".local_llm_out"

MODEL_HINTS = {
    "fast_summary": {
        "keywords": ["gemma-4-e4b", "gemma4:e4b", "qwen3.5-9b", "gpt-oss-20b", "minicpm", "deepseek-ocr", "glm-ocr"],
        "prefer_small": True,
        "description": "lightweight model for fast summarization",
    },
    "code_worker": {
        "keywords": ["coder", "qwen3-coder", "qwen3.5-9b", "qwen3.6:27b", "qwen3.6-27b-mtp", "gpt-oss-20b"],
        "prefer_small": False,
        "description": "coder model for test plans, TODO extraction",
    },
    "diff_reviewer": {
        "keywords": ["coder", "qwen3-coder", "qwen3.5-27b", "qwen3.6:27b", "qwen3.6-27b-mtp", "qwen3.5-35b"],
        "prefer_small": False,
        "description": "stronger coder model for diff review",
    },
    "deep_reviewer": {
        "keywords": ["mistral-medium", "mistral-small-4", "qwen3.5-35b", "qwen3-coder-next", "llama4", "nemotron-3-super", "qwen3.5-122b", "qwen3.6-35b-moe"],
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
    base_url, source = resolve_ollama_base_url()
    if requests is None:
        return CheckResult("ollama", False, f"requests not installed, cannot check {base_url}")
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        detail = f"{len(models)} models at {base_url}"
        if source == "OLLAMA_HOST":
            detail += f" (via OLLAMA_HOST)"
        return CheckResult("ollama", True, detail, data=models)
    except Exception as e:
        return CheckResult("ollama", False, f"Ollama at {base_url} not reachable: {e}")


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


def check_mtp_endpoints() -> list[CheckResult]:
    """Check each llama.cpp MTP endpoint for model availability."""
    results: list[CheckResult] = []
    import requests as _requests
    for url, label in _MTP_ENDPOINTS:
        try:
            resp = _requests.get(f"{url}/models" if not url.endswith("/models") else url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", m.get("name", "?")) for m in data.get("data", [])]
            results.append(CheckResult(f"mtp_{label.replace(' ', '_').lower()}", True,
                                      f"{label}: {len(models)} models", data=models))
        except Exception as e:
            results.append(CheckResult(f"mtp_{label.replace(' ', '_').lower()}", False,
                                      f"{label}: not reachable ({e})"))
    return results


PROBE_REPORT_SCHEMA_VERSION = 1
_PROBE_TIMEOUT_DEFAULT = 5.0


def _probe_endpoint(endpoint_url: str, timeout: float) -> tuple[bool, str]:
    """Reachability probe for a single endpoint URL.

    Returns `(ok, error_message)`. Never raises. `requests` missing is
    treated as a probe failure with an explanatory error.
    """
    if requests is None:
        return False, "requests library not installed"
    try:
        resp = requests.get(endpoint_url, timeout=timeout)
        resp.raise_for_status()
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def build_probe_report(probe_timeout: float = _PROBE_TIMEOUT_DEFAULT) -> dict:
    """Build a worker-pool dry-run probe report.

    Diagnostic only. Does not change routing, dispatch tasks, persist
    state, or stamp the call ledger. Reaches into the same endpoint
    config sources `local_check` already inspects:

      * resolved Ollama base URL
      * the OpenAI-compatible server (`OPENAI_COMPAT_BASE`)
      * `_MTP_ENDPOINTS` (zero12 llama.cpp MTP hosts)

    Returns a dict with the P4-B contract shape. `routing_changed` and
    `ledger_stamped` are always the literal boolean `False` — they are
    in the schema so future readers see a machine-checkable "no" to
    "did this probe change routing or write to the ledger?".
    """
    configured: list[dict] = []
    reachable: list[dict] = []
    unreachable: list[dict] = []
    errors: list[dict] = []

    ollama_url, _ = resolve_ollama_base_url()
    configured.append({
        "id": "ollama_default",
        "host": ollama_url,
        "endpoint": f"{ollama_url.rstrip('/')}/api/tags",
        "endpoint_type": "ollama",
    })

    configured.append({
        "id": "openai_compat_default",
        "host": OPENAI_COMPAT_BASE,
        "endpoint": f"{OPENAI_COMPAT_BASE.rstrip('/')}/v1/models",
        "endpoint_type": "openai_compat",
    })

    for url, label in _MTP_ENDPOINTS:
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "mtp"
        endpoint = url if url.endswith("/models") else f"{url.rstrip('/')}/models"
        configured.append({
            "id": f"mtp_{slug}",
            "host": url,
            "endpoint": endpoint,
            "endpoint_type": "llama_cpp_mtp",
        })

    for cfg in configured:
        ok, err = _probe_endpoint(cfg["endpoint"], probe_timeout)
        if ok:
            reachable.append({**cfg, "reachable": True})
        else:
            unreachable.append({**cfg, "reachable": False, "error": err})
            errors.append({"id": cfg["id"], "error": err})

    return {
        "schema_version": PROBE_REPORT_SCHEMA_VERSION,
        "worker_pool_dry_run_enabled": True,
        "configured_workers": configured,
        "reachable_workers": reachable,
        "unreachable_workers": unreachable,
        "probe_errors": errors,
        "routing_changed": False,
        "ledger_stamped": False,
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }


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

    # Load authoritative model assignments from profiles.json
    profiles_json_models = {}
    profiles_path = Path(__file__).parent / "local_llm_profiles.json"
    try:
        with open(profiles_path, encoding="utf-8") as f:
            profiles_data = json.loads(f.read())
        for name, cfg in profiles_data.get("profiles", {}).items():
            model = cfg.get("model", "")
            candidates = cfg.get("candidates", [])
            if model:
                profiles_json_models[name] = {
                    "model": model,
                    "candidates": candidates,
                }
    except Exception:
        pass

    for profile_name, hints in MODEL_HINTS.items():
        # Prefer the model from profiles.json if available
        pj = profiles_json_models.get(profile_name, {})
        pj_model = pj.get("model", "")
        pj_candidates = pj.get("candidates", [])

        # Build candidate list: profiles.json model first if available,
        # then profiles.json candidates, then keyword-matched models
        candidates = []
        seen = set()

        if pj_model and pj_model in base_models:
            candidates.append(pj_model)
            seen.add(pj_model)

        for c in pj_candidates:
            if c in base_models and c not in seen:
                candidates.append(c)
                seen.add(c)

        for model in base_models:
            if model in seen:
                continue
            model_lower = model.lower()
            for kw in hints["keywords"]:
                if kw.lower() in model_lower:
                    candidates.append(model)
                    seen.add(model)
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


def _parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local LLM environment health check.",
        add_help=True,
    )
    parser.add_argument(
        "--probe-workers",
        action="store_true",
        help="Also run a diagnostic worker-pool dry-run probe. "
             "Does not change routing, dispatch tasks, or write to the "
             "call ledger.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="With --probe-workers, emit the probe report as a single "
             "JSON object on stdout instead of the human-readable health "
             "check. Without --probe-workers, this flag is a no-op for "
             "P4-B.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = _parse_cli_args(argv)

    if args.probe_workers and args.json:
        report = build_probe_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

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

    print_section("llama.cpp MTP Endpoints (zero12)")
    mtp_results = check_mtp_endpoints()
    for r in mtp_results:
        print(f"  [{('OK' if r.ok else 'FAIL'):4s}] {r.detail}")

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

    if args.probe_workers:
        report = build_probe_report()
        print_section("Worker Pool Dry-Run Probe (diagnostic only)")
        print(f"  schema_version:    {report['schema_version']}")
        print(f"  configured:        {len(report['configured_workers'])}")
        print(f"  reachable:         {len(report['reachable_workers'])}")
        print(f"  unreachable:       {len(report['unreachable_workers'])}")
        for w in report["unreachable_workers"]:
            print(f"    - {w['id']} ({w['endpoint']}): {w['error']}")
        print(f"  routing_changed:   {report['routing_changed']}")
        print(f"  ledger_stamped:    {report['ledger_stamped']}")
        print("  Note: probe is advisory; routing and ledger are unchanged.")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
