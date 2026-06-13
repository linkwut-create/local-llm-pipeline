#!/usr/bin/env python3
"""
Model Audition Runner — each model takes the full 12-case battery.
Results determine role suitability. Model-first, not task-first.

Usage:
    py -3 tools/model_audition.py --model qwen3-coder:30b
    py -3 tools/model_audition.py --from-ollama
    py -3 tools/model_audition.py --model qwen3-coder:30b --case 003
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
EVALS_DIR = SCRIPT_DIR.parent / "evals" / "model_audition"
CASES_DIR = EVALS_DIR / "cases"
RESULTS_DIR = EVALS_DIR / "results"
REPORTS_DIR = EVALS_DIR / "reports"
RUBRIC_PATH = EVALS_DIR / "rubric.yaml"

_raw_host = os.environ.get("OLLAMA_HOST", "193.168.2.2:11434")
# Strip protocol prefix if present (env var may include http:// or https://)
OLLAMA_HOST = _raw_host.replace("https://", "").replace("http://", "")
OLLAMA_API = f"http://{OLLAMA_HOST}/api/generate"


def load_case(case_id: str) -> dict | None:
    """Load a case file by ID (e.g., '003' or '003_profile_tag_drift')."""
    for f in sorted(CASES_DIR.glob("*.md")):
        name = f.stem
        if case_id in name or name.startswith(case_id):
            content = f.read_text(encoding="utf-8")
            # Extract prompt section
            prompt_match = re.search(r"```\n(.*?)```", content, re.DOTALL)
            if not prompt_match:
                prompt_match = re.search(r"## Prompt\n\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
            prompt = prompt_match.group(1).strip() if prompt_match else content
            return {
                "case_id": name[:3],
                "case_name": name,
                "title": content.split("\n")[0].replace("# ", ""),
                "prompt": prompt,
            }
    return None


def list_cases() -> list[str]:
    return sorted([f.stem for f in CASES_DIR.glob("*.md")])


# Pre-flight token limits to try, from small to large.
# Start at 200 — "Say OK." always succeeds at 50 but actual cases need headroom.
PREFLIGHT_TOKEN_LIMITS = [200, 400, 800]


def warmup_model(model: str, warmup_timeout: int = 1800) -> bool:
    """Load the model into GPU with a tiny prompt. Not timed — loading only.
    Returns True if model loaded and responded."""
    print(f"    warmup: loading {model} (timeout={warmup_timeout}s)...", end=" ", flush=True)
    r = call_ollama(model, "Say OK.", timeout=warmup_timeout, num_predict=5)
    if r["ok"] and r["response"].strip():
        print(f"OK ({r['elapsed_seconds']:.0f}s)", flush=True)
        return True
    print(f"FAIL ({r.get('error', 'unknown')})", flush=True)
    return False


def preflight_check(model: str, timeout: int = 180) -> int:
    """Run a quick test to find the optimal num_predict for this model.
    Uses a short but real prompt (not just "Say OK.") to ensure the model
    can produce multi-sentence output. Returns the recommended num_predict."""
    test_prompt = "Explain what a JSON schema validator does in 2-3 sentences."
    for np in PREFLIGHT_TOKEN_LIMITS:
        r = call_ollama(model, test_prompt, timeout=timeout, num_predict=np)
        if r["ok"] and len(r["response"].strip()) > 50:
            return np
    return PREFLIGHT_TOKEN_LIMITS[0]


def call_ollama(model: str, prompt: str, timeout: int = 180,
                num_predict: int = 400) -> dict:
    """Call Ollama with a prompt. Returns {ok, response, elapsed_seconds, error}."""
    start = time.time()
    try:
        data = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": num_predict, "temperature": 0.1},
        }).encode()
        req = urllib.request.Request(
            OLLAMA_API, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
            elapsed = time.time() - start
            return {
                "ok": True,
                "response": result.get("response", ""),
                "elapsed_seconds": round(elapsed, 1),
                "error": None,
                "eval_count": result.get("eval_count", 0),
            }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "ok": False,
            "response": "",
            "elapsed_seconds": round(elapsed, 1),
            "error": str(e)[:200],
            "eval_count": 0,
        }


def unload_model(model: str):
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


def run_audition(model: str, cases: list[str], timeout: int = 180,
                 num_predict: int = 400) -> list[dict]:
    """Run all cases for one model. Returns list of result dicts."""
    results = []
    run_id = time.strftime("%Y%m%d-%H%M%S")

    for case_name in cases:
        case = load_case(case_name)
        if not case:
            print(f"  WARNING: case '{case_name}' not found, skipping")
            continue

        print(f"  {case['case_id']} {case['title'][:60]}...", end=" ", flush=True)

        result = call_ollama(model, case["prompt"], timeout=timeout, num_predict=num_predict)
        status = "OK" if result["ok"] and result["response"].strip() else "FAIL"
        print(f"{status} ({result['elapsed_seconds']:.1f}s)")

        results.append({
            "run_id": run_id,
            "model": model,
            "case_id": case["case_id"],
            "case_name": case["case_name"],
            "case_title": case["title"],
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_sec": result["elapsed_seconds"],
            "success": result["ok"] and bool(result["response"].strip()),
            "raw_output": result["response"],
            "error": result.get("error"),
        })

    return results


def save_results(results: list[dict], model: str) -> Path:
    """Save results as JSONL. Returns path."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{timestamp}_{model.replace(':', '-')}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description="Model Audition — capability assessment")
    parser.add_argument("--model", action="append", default=[], help="Model to test (repeatable)")
    parser.add_argument("--from-ollama", action="store_true", help="Test all Ollama models")
    parser.add_argument("--case", default=None, help="Run only specific case (e.g., 003)")
    parser.add_argument("--timeout", type=int, default=180, help="Per-case timeout in seconds")
    parser.add_argument("--runs", type=int, default=1, help="Number of audition runs per model (default: 1)")
    parser.add_argument("--json-only", action="store_true", help="JSON output only")
    args = parser.parse_args()

    cases = [args.case] if args.case else list_cases()
    if not cases:
        print("ERROR: no cases found")
        sys.exit(1)

    models = args.model
    if args.from_ollama:
        models = get_ollama_models()
        # Skip non-text models
        skip = {"diffusiongemma", "nomic-embed", "bge-m3"}
        models = [m for m in models if not any(s in m.lower() for s in skip)]

    if not models:
        print("ERROR: no models specified. Use --model or --from-ollama")
        sys.exit(1)

    if not args.json_only:
        runs_str = f" × {args.runs} runs" if args.runs > 1 else ""
        print(f"Model Audition: {len(models)} models × {len(cases)} cases{runs_str}")
        print(f"Results: {RESULTS_DIR}")
        print(f"Reports: {REPORTS_DIR}")
        print()

    all_saved = []
    for model in models:
        # Phase 0: load model (long timeout — loading time not counted)
        if not warmup_model(model, warmup_timeout=1800):
            if not args.json_only:
                print(f"[{model}] SKIP: failed to load")
            continue

        # Phase 1: find optimal num_predict (model already loaded, short timeout)
        np = preflight_check(model, timeout=args.timeout)
        if not args.json_only:
            print(f"[{model}] preflight: num_predict={np}")

        for run_num in range(1, args.runs + 1):
            label = f"[{model}]" if args.runs == 1 else f"[{model}] run {run_num}/{args.runs}"
            if not args.json_only:
                print(label)
            results = run_audition(model, cases, timeout=args.timeout, num_predict=np)
            # Add run number and params to results
            for r in results:
                r["run_num"] = run_num
                r["num_predict"] = np
                r["timeout"] = args.timeout
            path = save_results(results, f"{model}_run{run_num}" if args.runs > 1 else model)
            all_saved.append(path)
        unload_model(model)

    if not args.json_only:
        print(f"\nDone. {len(all_saved)} result files saved.")
        for p in all_saved:
            print(f"  {p}")
        if all_saved:
            print(f"\nScore with: py -3 tools/score_model_audition.py {all_saved[-1]}")


if __name__ == "__main__":
    main()
