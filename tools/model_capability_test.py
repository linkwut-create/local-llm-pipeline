#!/usr/bin/env python3
"""
Model Capability Assessment — each model takes a battery of standardized tests.
Results determine which role/profile each model is best suited for.

Usage:
    py -3 tools/model_capability_test.py
    py -3 tools/model_capability_test.py --model qwen3-coder:30b
    py -3 tools/model_capability_test.py --quick  # test fewer models faster
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "193.168.2.2:11434")
OLLAMA_API = f"http://{OLLAMA_HOST}/api/generate"

# ── Test Battery ──────────────────────────────────────────────
# Each test is a (capability, prompt, eval_criteria)
# eval: "contains:<word>" | "length:>N" | "speed:<Ns"
BATTERY = [
    {
        "id": "speed",
        "capability": "basic-response",
        "prompt": "Say hello.",
        "eval": "length:>2",
        "timeout": 30,
    },
    {
        "id": "summary",
        "capability": "summarization",
        "prompt": "Summarize this in exactly one short sentence: Artificial intelligence has transformed many industries including healthcare, finance, and transportation. Machine learning models can now diagnose diseases, predict market trends, and drive cars autonomously.",
        "eval": "length:>20",
        "timeout": 60,
    },
    {
        "id": "code",
        "capability": "code-understanding",
        "prompt": "In one sentence, what does this function return? `def f(n): return len([x for x in range(2, n) if all(x % d != 0 for d in range(2, int(x**0.5)+1))])`",
        "eval": "contains:prime",
        "timeout": 60,
    },
    {
        "id": "logic",
        "capability": "reasoning",
        "prompt": "All cats are mammals. Some mammals are aquatic. Can we conclude that some cats are aquatic? Answer ONLY: Yes or No.",
        "eval": "contains:No",
        "timeout": 60,
    },
    {
        "id": "chinese",
        "capability": "multilingual",
        "prompt": "用一句话翻译成英文：人工智能正在改变世界。",
        "eval": "contains:intelligence",
        "timeout": 60,
    },
    {
        "id": "structure",
        "capability": "structured-output",
        "prompt": "Output exactly this JSON and nothing else: {\"name\":\"test\",\"value\":42}",
        "eval": "contains:\"name\"",
        "timeout": 60,
    },
]

# ── Role assignment ──────────────────────────────────────────
# Based on which capabilities a model passes, assign it to roles
ROLE_RULES = [
    {
        "role": "fast_summary",
        "requires": ["basic-response", "summarization"],
        "prefers": ["speed < 5s"],
        "model_field": "fast lightweight summarizer",
    },
    {
        "role": "code_worker",
        "requires": ["basic-response", "code-understanding"],
        "prefers": ["structured-output"],
        "model_field": "coder / code-adjacent tasks",
    },
    {
        "role": "commit_reviewer",
        "requires": ["basic-response", "code-understanding"],
        "prefers": ["speed < 30s", "structured-output"],
        "model_field": "fast commit-gate reviewer",
    },
    {
        "role": "diff_reviewer",
        "requires": ["basic-response", "code-understanding", "reasoning"],
        "model_field": "thorough diff reviewer",
    },
    {
        "role": "deep_reviewer",
        "requires": ["basic-response", "code-understanding", "reasoning"],
        "prefers": ["structured-output"],
        "model_field": "deep architecture reviewer",
    },
    {
        "role": "reasoning_checker",
        "requires": ["basic-response", "reasoning"],
        "model_field": "risk analysis / logic check",
    },
    {
        "role": "deep_reasoning",
        "requires": ["basic-response", "reasoning", "structured-output"],
        "model_field": "deep reasoning for critical tasks",
    },
    {
        "role": "translation",
        "requires": ["basic-response", "multilingual"],
        "prefers": ["summarization"],
        "model_field": "translation tasks",
    },
    {
        "role": "smart_summary",
        "requires": ["basic-response", "summarization"],
        "prefers": ["structured-output", "speed < 10s"],
        "model_field": "high-quality summarizer",
    },
    {
        "role": "heavy_reviewer",
        "requires": ["basic-response", "code-understanding", "reasoning"],
        "prefers": ["summarization"],
        "model_field": "large backup reviewer",
    },
]


def call_ollama(model: str, prompt: str, timeout: int = 60) -> dict:
    """Call Ollama generate API. Returns {ok, response, elapsed_seconds, error}."""
    start = time.time()
    try:
        data = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 200, "temperature": 0.1},
        }).encode()
        req = urllib.request.Request(
            OLLAMA_API,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
            elapsed = time.time() - start
            response_text = result.get("response", "")
            return {
                "ok": True,
                "response": response_text,
                "elapsed_seconds": round(elapsed, 1),
                "error": None,
                "eval_duration_ns": result.get("eval_duration", 0),
            }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "ok": False,
            "response": "",
            "elapsed_seconds": round(elapsed, 1),
            "error": str(e)[:150],
            "eval_duration_ns": 0,
        }


def evaluate_test(test_def: dict, result: dict) -> tuple[bool, str]:
    """Evaluate if a test passed based on its criteria."""
    if not result["ok"]:
        return False, f"API error: {result['error']}"

    response = result["response"].strip()
    if not response:
        return False, "empty response"

    eval_str = test_def["eval"]

    if eval_str.startswith("length:>"):
        min_len = int(eval_str.split(">")[1])
        if len(response) < min_len:
            return False, f"too short ({len(response)} < {min_len})"
        return True, "ok"

    if eval_str.startswith("contains:"):
        keyword = eval_str.split(":", 1)[1].lower()
        if keyword not in response.lower():
            return False, f"missing '{keyword}'"
        return True, "ok"

    return True, "ok"


def unload_model(model: str):
    """Unload model from Ollama VRAM."""
    try:
        data = json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode()
        req = urllib.request.Request(OLLAMA_API, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def get_ollama_models() -> list[str]:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
        return [line.split()[0] for line in r.stdout.strip().split("\n")[1:] if line.strip()]
    except Exception:
        return []


def classify_model(results: list[dict]) -> dict:
    """Classify a model based on its test results."""
    passed = {r["test_id"]: r["passed"] for r in results}
    capabilities = []
    for r in results:
        if r["passed"]:
            capabilities.append(r["capability"])

    speed_result = next((r for r in results if r["test_id"] == "speed"), None)
    speed = speed_result["elapsed_seconds"] if speed_result else 999

    assigned_roles = []
    for rule in ROLE_RULES:
        required = all(c in capabilities for c in rule["requires"])
        if not required:
            continue
        # Check preferences
        pref_ok = True
        for pref in rule.get("prefers", []):
            if pref.startswith("speed <"):
                max_speed = float(pref.split("<")[1].replace("s", ""))
                if speed > max_speed:
                    pref_ok = False
        if pref_ok:
            assigned_roles.append(rule["role"])

    return {
        "capabilities": capabilities,
        "speed_seconds": speed,
        "assigned_roles": assigned_roles,
        "tests_passed": sum(1 for r in results if r["passed"]),
        "tests_total": len(results),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="Test a single model")
    parser.add_argument("--quick", action="store_true", help="Test fewer models")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.model:
        models = [args.model]
    else:
        models = get_ollama_models()
        if args.quick:
            # Only test models that are in profiles
            profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
            if profiles_path.exists():
                profile_models = set()
                profiles_data = json.loads(profiles_path.read_text(encoding="utf-8"))
                for p in profiles_data.get("profiles", {}).values():
                    profile_models.add(p.get("model", ""))
                models = [m for m in models if m in profile_models]
                # Also add new gemma and Q4 models
                extras = [m for m in models if "12b" in m.lower() or "q4" in m.lower()]
                models = list(set(models) | set(extras))

    if not models:
        print("No models found")
        sys.exit(1)

    if not args.json_only:
        print(f"Testing {len(models)} models with {len(BATTERY)} capability tests each")
        print(f"Model,Role Fit,Tests,Speed,Capabilities")
        print("-" * 90)

    all_results = []

    for model in sorted(models):
        model_results = []
        if not args.json_only:
            print(f"\n{model}", end="", flush=True)

        for test in BATTERY:
            result = call_ollama(model, test["prompt"], timeout=test["timeout"])
            passed, reason = evaluate_test(test, result)
            model_results.append({
                "test_id": test["id"],
                "capability": test["capability"],
                "passed": passed,
                "elapsed_seconds": result["elapsed_seconds"],
                "reason": reason,
                "response_preview": result["response"][:100] if result["ok"] else "",
            })
            if not args.json_only:
                marker = "." if passed else "x"
                print(marker, end="", flush=True)

        classification = classify_model(model_results)
        roles_str = ",".join(classification["assigned_roles"][:3]) or "unclassified"
        caps_str = ",".join(classification["capabilities"])

        if not args.json_only:
            print(f"\n  → {classification['tests_passed']}/{classification['tests_total']} passed, "
                  f"{classification['speed_seconds']:.1f}s, roles=[{roles_str}]")

        all_results.append({
            "model": model,
            "classification": classification,
            "test_details": model_results,
        })

        unload_model(model)

    # Write report
    report_path = SCRIPT_DIR.parent / ".local_llm_out" / "model_capability_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "test_date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "models_tested": len(models),
        "tests_per_model": len(BATTERY),
        "results": all_results,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if not args.json_only:
        print(f"\nReport: {report_path}")

        # Summary by role
        print(f"\n{'='*60}")
        print("ROLE ASSIGNMENTS")
        print(f"{'='*60}")
        role_models = {}
        for r in all_results:
            for role in r["classification"]["assigned_roles"]:
                role_models.setdefault(role, []).append(r["model"])
        for role in sorted(role_models):
            print(f"  {role}:")
            for m in role_models[role]:
                print(f"    - {m}")



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
