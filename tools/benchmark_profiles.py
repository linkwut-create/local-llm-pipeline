#!/usr/bin/env python3
"""
Benchmark local LLM profiles on a test file.

Measures response time and output size for each profile.
Default: only runs fast_summary. Use --all to run every profile.

Usage:
    python tools/benchmark_profiles.py
    python tools/benchmark_profiles.py --profile fast_summary --task summarize-file --input AGENTS.md --json
    python tools/benchmark_profiles.py --all
    python tools/benchmark_profiles.py --profiles fast_summary,code_worker
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
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


def get_default_profile() -> str:
    if not PROFILES_PATH.exists():
        return "fast_summary"
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    return data.get("default_profile", "fast_summary")


def find_test_file() -> Path | None:
    candidates = ["README.md", "AGENTS.md", "CLAUDE.md", "package.json", "pyproject.toml"]
    for name in candidates:
        p = Path(name)
        if p.exists() and p.stat().st_size > 100:
            return p
    for ext in ["*.md", "*.py", "*.ts", "*.js"]:
        found = list(Path(".").glob(ext))
        if found:
            return found[0]
    return None


def run_benchmark(profile: str, model: str, task: str, test_file: Path,
                  timeout_secs: int) -> dict:
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
            cmd, capture_output=True, text=True, timeout=timeout_secs,
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            return {
                "profile": profile,
                "model": model,
                "task": task,
                "ok": False,
                "elapsed_seconds": round(elapsed, 2),
                "error": result.stderr.strip()[-200:] if result.stderr else "unknown error",
                "output_chars": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

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
            "elapsed_seconds": round(elapsed, 2),
            "error": None,
            "output_chars": output_chars,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    except subprocess.TimeoutExpired:
        return {
            "profile": profile,
            "model": model,
            "task": task,
            "ok": False,
            "elapsed_seconds": timeout_secs,
            "error": f"TIMEOUT ({timeout_secs}s)",
            "output_chars": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def main():
    parser = argparse.ArgumentParser(description="Benchmark local LLM profiles")
    parser.add_argument("--input", default=None, help="Test file to use")
    parser.add_argument("--file", default=None, help="Alias for --input")
    parser.add_argument("--profile", default=None,
                        help="Single profile to benchmark")
    parser.add_argument("--profiles", default=None,
                        help="Comma-separated profile names")
    parser.add_argument("--all", action="store_true",
                        help="Benchmark all profiles (default: only fast_summary)")
    parser.add_argument("--task", default="summarize-file",
                        help="Task to benchmark (default: summarize-file)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout per profile in seconds (default: 600)")
    parser.add_argument("--json", action="store_true",
                        help="Print JSON results to stdout")

    args = parser.parse_args()

    all_profiles = get_profiles()
    if not all_profiles:
        print("ERROR: No profiles found in local_llm_profiles.json.", file=sys.stderr)
        sys.exit(1)

    if args.profile:
        selected = {args.profile: all_profiles[args.profile]} if args.profile in all_profiles else {}
        if not selected:
            print(f"ERROR: Profile '{args.profile}' not found.", file=sys.stderr)
            sys.exit(1)
    elif args.profiles:
        names = args.profiles.split(",")
        selected = {k: v for k, v in all_profiles.items() if k in names}
    elif args.all:
        selected = all_profiles
    else:
        default = get_default_profile()
        selected = {default: all_profiles[default]} if default in all_profiles else {}

    test_file = Path(args.input or args.file or "") if (args.input or args.file) else find_test_file()
    if not test_file or not test_file.exists():
        print("ERROR: No test file found. Specify with --input.", file=sys.stderr)
        sys.exit(1)

    file_size = test_file.stat().st_size

    if not args.json:
        print(f"Benchmark: task={args.task} file={test_file} ({file_size} bytes)")
        print(f"Profiles: {', '.join(selected.keys())}")
        print(f"{'=' * 70}\n")

    results = []
    for profile_name, profile_conf in selected.items():
        model = profile_conf.get("model", "unknown")
        if not args.json:
            print(f"Testing {profile_name} ({model})...", end=" ", flush=True)

        r = run_benchmark(profile_name, model, args.task, test_file, args.timeout)
        results.append(r)

        if not args.json:
            if r["ok"]:
                print(f"{r['elapsed_seconds']}s, {r['output_chars']} chars")
            else:
                print(f"FAILED: {r['error'][:80]}")

    if not args.json:
        print(f"\n{'=' * 70}")
        print(f"\n{'Profile':<22} {'Model':<35} {'Time':>7} {'Chars':>7} {'Status':<8}")
        print(f"{'-' * 22} {'-' * 35} {'-' * 7} {'-' * 7} {'-' * 8}")

        for r in sorted(results, key=lambda x: x["elapsed_seconds"]):
            status = "OK" if r["ok"] else "FAIL"
            model_short = r["model"][:33] + ".." if len(r["model"]) > 35 else r["model"]
            print(f"{r['profile']:<22} {model_short:<35} {r['elapsed_seconds']:>6.1f}s {r['output_chars']:>6} {status:<8}")

        ok_results = [r for r in results if r["ok"]]
        if ok_results:
            fastest = min(ok_results, key=lambda x: x["elapsed_seconds"])
            most_output = max(ok_results, key=lambda x: x["output_chars"])
            print(f"\nFastest: {fastest['profile']} ({fastest['elapsed_seconds']}s)")
            print(f"Most output: {most_output['profile']} ({most_output['output_chars']} chars)")

    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"benchmark_{ts}.json"

    benchmark_output = {
        "task": args.task,
        "input_file": str(test_file),
        "input_bytes": file_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    out_path.write_text(json.dumps(benchmark_output, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(benchmark_output, indent=2, ensure_ascii=False))
    else:
        print(f"\nResults saved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
