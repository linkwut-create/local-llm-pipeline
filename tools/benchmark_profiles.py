#!/usr/bin/env python3
"""
Benchmark local LLM profiles on a small test file.

Measures response time and output quality for each profile.

Usage:
    python tools/benchmark_profiles.py
    python tools/benchmark_profiles.py --file README.md
    python tools/benchmark_profiles.py --profiles fast_summary,code_worker
    python tools/benchmark_profiles.py --task summarize-file
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROUTER_PATH = SCRIPT_DIR / "local_llm_router.py"
PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"
OUTPUT_DIR = ".local_llm_out"


def get_profiles() -> dict:
    if not PROFILES_PATH.exists():
        return {}
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    return data.get("profiles", {})


def find_test_file() -> Path | None:
    candidates = ["README.md", "AGENTS.md", "CLAUDE.md", "package.json", "pyproject.toml"]
    for name in candidates:
        p = Path(name)
        if p.exists() and p.stat().st_size > 100:
            return p
    # find any .py or .md file
    for ext in ["*.md", "*.py", "*.ts", "*.js"]:
        found = list(Path(".").glob(ext))
        if found:
            return found[0]
    return None


def run_benchmark(profile: str, model: str, task: str, test_file: Path) -> dict:
    cmd = [
        sys.executable, str(ROUTER_PATH),
        task, str(test_file),
        "--profile", profile,
        "--json-only",
        "--no-markdown",
    ]

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            return {
                "profile": profile,
                "model": model,
                "task": task,
                "ok": False,
                "time_seconds": round(elapsed, 1),
                "error": result.stderr.strip()[-200:] if result.stderr else "unknown error",
                "output_chars": 0,
            }

        # try to parse JSON from stdout
        output_chars = 0
        try:
            lines = result.stdout.strip().split("\n")
            json_start = None
            for i, line in enumerate(lines):
                if line.strip().startswith("{"):
                    json_start = i
                    break
            if json_start is not None:
                json_text = "\n".join(lines[json_start:])
                data = json.loads(json_text)
                output_chars = len(data.get("result", ""))
        except (json.JSONDecodeError, ValueError):
            output_chars = len(result.stdout)

        return {
            "profile": profile,
            "model": model,
            "task": task,
            "ok": True,
            "time_seconds": round(elapsed, 1),
            "error": None,
            "output_chars": output_chars,
        }

    except subprocess.TimeoutExpired:
        return {
            "profile": profile,
            "model": model,
            "task": task,
            "ok": False,
            "time_seconds": 600,
            "error": "TIMEOUT (600s)",
            "output_chars": 0,
        }


def main():
    parser = argparse.ArgumentParser(description="Benchmark local LLM profiles")
    parser.add_argument("--file", default=None, help="Test file to use")
    parser.add_argument("--profiles", default=None,
                        help="Comma-separated profile names (default: all)")
    parser.add_argument("--task", default="summarize-file",
                        help="Task to benchmark (default: summarize-file)")

    args = parser.parse_args()

    profiles = get_profiles()
    if not profiles:
        print("ERROR: No profiles found. Run update_profiles_from_ollama.py first.")
        sys.exit(1)

    if args.profiles:
        selected = args.profiles.split(",")
        profiles = {k: v for k, v in profiles.items() if k in selected}

    test_file = Path(args.file) if args.file else find_test_file()
    if not test_file or not test_file.exists():
        print("ERROR: No test file found. Specify one with --file.")
        sys.exit(1)

    file_size = test_file.stat().st_size
    print(f"Benchmark: task={args.task} file={test_file} ({file_size} bytes)")
    print(f"Profiles to test: {', '.join(profiles.keys())}")
    print(f"{'='*70}\n")

    results = []
    for profile_name, profile_conf in profiles.items():
        model = profile_conf.get("model", "unknown")
        print(f"Testing {profile_name} ({model})...", end=" ", flush=True)

        r = run_benchmark(profile_name, model, args.task, test_file)
        results.append(r)

        if r["ok"]:
            print(f"{r['time_seconds']}s, {r['output_chars']} chars")
        else:
            print(f"FAILED: {r['error'][:80]}")

    print(f"\n{'='*70}")
    print(f"\n{'Profile':<22} {'Model':<35} {'Time':>7} {'Chars':>7} {'Status':<8}")
    print(f"{'-'*22} {'-'*35} {'-'*7} {'-'*7} {'-'*8}")

    for r in sorted(results, key=lambda x: x["time_seconds"]):
        status = "OK" if r["ok"] else "FAIL"
        model_short = r["model"][:33] + ".." if len(r["model"]) > 35 else r["model"]
        print(f"{r['profile']:<22} {model_short:<35} {r['time_seconds']:>6.1f}s {r['output_chars']:>6} {status:<8}")

    ok_results = [r for r in results if r["ok"]]
    if ok_results:
        fastest = min(ok_results, key=lambda x: x["time_seconds"])
        most_output = max(ok_results, key=lambda x: x["output_chars"])
        print(f"\nFastest: {fastest['profile']} ({fastest['time_seconds']}s)")
        print(f"Most output: {most_output['profile']} ({most_output['output_chars']} chars)")

    # Save results
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ts}_benchmark.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
