#!/usr/bin/env python3
"""
Comprehensive model task test — tests ALL Ollama models with real tasks.
Output: JSON report to .local_llm_out/model_test_report.json.

Usage:
    py -3 tools/test_all_models.py
    py -3 tools/test_all_models.py --task summarize-file   # single task
    py -3 tools/test_all_models.py --profile fast_summary  # single profile
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

__test__ = False  # This is a standalone script, not a pytest test module.

SCRIPT_DIR = Path(__file__).parent
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "193.168.2.2:11434")
OLLAMA_URL = f"http://{OLLAMA_HOST}"

# Tasks to test
DEFAULT_TASKS = ["summarize-file"]
TEST_INPUT = "README.md"  # small file for quick testing


def get_ollama_models() -> list[str]:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
        lines = r.stdout.strip().split("\n")[1:]
        return [line.split()[0] for line in lines if line.strip()]
    except Exception as e:
        print(f"ERROR: cannot get ollama list: {e}")
        return []


def unload_model(model: str):
    """Tell Ollama to unload a model from memory."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def test_model_with_task(model: str, task: str, profile: str | None = None,
                         timeout: int = 1000) -> dict:
    """Test a single model with a single task. Returns result dict."""
    start = time.time()

    if profile:
        cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"),
               task, TEST_INPUT, "--profile", profile]
    else:
        cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_worker.py"),
               task, "--model", model, TEST_INPUT]

    try:
        # Merge stderr into stdout — router writes "OK:" to stderr
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "OLLAMA_HOST": OLLAMA_HOST},
        )
        elapsed = time.time() - start
        combined = r.stdout + r.stderr

        ok = "OK:" in combined or "OK (cache hit)" in combined
        error = None
        if not ok:
            for line in combined.split("\n"):
                if "ERROR:" in line or "error:" in line.lower():
                    error = line.strip()[:200]
                    break
            if not error:
                error = "no OK/ERROR marker found"

        return {
            "model": model,
            "task": task,
            "profile": profile,
            "ok": ok,
            "elapsed_seconds": round(elapsed, 1),
            "error": error,
            "cache_hit": "cache hit" in combined,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return {
            "model": model, "task": task, "profile": profile,
            "ok": False, "elapsed_seconds": round(elapsed, 1),
            "error": "timeout",
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "model": model, "task": task, "profile": profile,
            "ok": False, "elapsed_seconds": round(elapsed, 1),
            "error": str(e)[:200],
        }


def get_profile_for_model(model: str, profiles_data: dict) -> str | None:
    """Find which profile uses this model as primary."""
    for pname, p in profiles_data.get("profiles", {}).items():
        if p.get("model") == model:
            return pname
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test all Ollama models with tasks")
    parser.add_argument("--task", default=None, help="Single task to test")
    parser.add_argument("--profile", default=None, help="Single profile to test")
    parser.add_argument("--timeout", type=int, default=1000, help="Per-model timeout")
    parser.add_argument("--json-only", action="store_true", help="JSON output only")
    args = parser.parse_args()

    tasks = [args.task] if args.task else DEFAULT_TASKS

    # Load profiles
    profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
    profiles_data = {}
    if profiles_path.exists():
        profiles_data = json.loads(profiles_path.read_text(encoding="utf-8"))

    # Get models to test
    if args.profile:
        profile_cfg = profiles_data.get("profiles", {}).get(args.profile, {})
        models_to_test = [profile_cfg.get("model", "")]
        if not models_to_test[0]:
            print(f"ERROR: profile '{args.profile}' not found")
            sys.exit(1)
    else:
        models_to_test = get_ollama_models()
        if not models_to_test:
            print("ERROR: no models found")
            sys.exit(1)

    if not args.json_only:
        print(f"Testing {len(models_to_test)} models with {len(tasks)} task(s)...")
        print(f"{'Model':40s} {'Task':20s} {'Result':8s} {'Time':>6s}")
        print("-" * 80)

    results = []
    n_ok = 0
    n_fail = 0

    for model in models_to_test:
        if not model.strip():
            continue

        for task in tasks:
            profile = get_profile_for_model(model, profiles_data)

            # Skip if no profile and no explicit model
            if not profile:
                # Test directly via worker without profile
                result = test_model_with_task(model, task, timeout=args.timeout)
            else:
                result = test_model_with_task(model, task, profile=profile, timeout=args.timeout)

            results.append(result)

            if result["ok"]:
                n_ok += 1
                status = "OK"
            else:
                n_fail += 1
                status = "FAIL"

            if not args.json_only:
                err = f" ({result['error'][:60]})" if result.get("error") else ""
                print(f"{model:40s} {task:20s} {status:8s} {result['elapsed_seconds']:5.1f}s{err}",
                      flush=True)

            # Unload model from memory
            unload_model(model)

    # Write report
    out_dir = SCRIPT_DIR.parent / ".local_llm_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "model_test_report.json"

    report = {
        "test_date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ollama_host": OLLAMA_HOST,
        "total_models": len(models_to_test),
        "total_tests": len(results),
        "passed": n_ok,
        "failed": n_fail,
        "results": results,
    }

    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if not args.json_only:
        print(f"\n{n_ok}/{len(results)} passed, {n_fail} failed")
        print(f"Report: {report_path}")

    sys.exit(0 if n_fail == 0 else 1)



def _get_openai_models_from_api(base_url: str) -> list[str]:
    """Fallback: query OpenAI-compatible /v1/models endpoint."""
    try:
        from urllib.request import Request, urlopen
        import json
        url = base_url.rstrip("/") + "/models"
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return [m.get("id", "") for m in payload.get("data", []) if isinstance(m, dict) and m.get("id")]
    except Exception:
        return []


def get_available_models() -> list[str]:
    """Get models: Ollama first, fall back to OpenAI-compat endpoints."""
    import os
    models = get_ollama_models()
    if models:
        return models
    base_url = os.environ.get("LOCAL_LLM_BASE_URL", "")
    if base_url and ":11434" not in base_url and ":11436" not in base_url:
        models = _get_openai_models_from_api(base_url)
        if models:
            return models
    return get_ollama_models()  # retry

if __name__ == "__main__":
    main()
