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


def run_model_benchmark(model: str, task: str, test_file: Path,
                       timeout_secs: int) -> dict:
    """Benchmark a model directly (bypassing profiles) via the worker."""
    cmd = [
        sys.executable, str(SCRIPT_DIR / "local_llm_worker.py"),
        task, str(test_file),
        "--model", model,
    ]

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_secs,
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            return {
                "model": model,
                "task": task,
                "ok": False,
                "timed_out": False,
                "duration_sec": round(elapsed, 2),
                "output_chars": 0,
                "error": result.stderr.strip()[-300:] if result.stderr else "unknown error",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        return {
            "model": model,
            "task": task,
            "ok": True,
            "timed_out": False,
            "duration_sec": round(elapsed, 2),
            "output_chars": len(result.stdout),
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    except subprocess.TimeoutExpired:
        return {
            "model": model,
            "task": task,
            "ok": False,
            "timed_out": True,
            "duration_sec": timeout_secs,
            "output_chars": 0,
            "error": f"TIMEOUT ({timeout_secs}s)",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def main():
    parser = argparse.ArgumentParser(description="Benchmark local LLM profiles and models")
    parser.add_argument("--input", default=None, help="Test file to use")
    parser.add_argument("--file", default=None, help="Alias for --input")
    parser.add_argument("--profile", default=None,
                        help="Single profile to benchmark")
    parser.add_argument("--profiles", default=None,
                        help="Comma-separated profile names")
    parser.add_argument("--models", default=None,
                        help="Comma-separated model names (bypass profiles)")
    parser.add_argument("--all", action="store_true",
                        help="Benchmark all profiles")
    parser.add_argument("--task", default="summarize-file",
                        help="Single task (default: summarize-file)")
    parser.add_argument("--tasks", default=None,
                        help="Comma-separated task names")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Repeat each benchmark N times (default: 1)")
    parser.add_argument("--timeout", type=int, default=1000,
                        help="Timeout per run in seconds (default: 600)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be tested without running")
    parser.add_argument("--json", action="store_true",
                        help="Print JSON results to stdout")
    parser.add_argument("--output-json", default=None,
                        help="Write JSON report to file")
    parser.add_argument("--output-md", default=None,
                        help="Write Markdown report to file")

    args = parser.parse_args()

    all_profiles = get_profiles()

    # Resolve models to test
    model_task_pairs = []

    tasks = [args.task]
    if args.tasks:
        tasks = [t.strip() for t in args.tasks.split(",")]

    if args.models:
        models = [m.strip() for m in args.models.split(",")]
        for model in models:
            for task in tasks:
                for _ in range(args.repeat):
                    model_task_pairs.append((model, task, None))
    else:
        # Profile-based selection
        if args.profile:
            if args.profile not in all_profiles:
                print(f"ERROR: Profile '{args.profile}' not found.", file=sys.stderr)
                sys.exit(1)
            selected = {args.profile: all_profiles[args.profile]}
        elif args.profiles:
            names = [n.strip() for n in args.profiles.split(",")]
            selected = {k: v for k, v in all_profiles.items() if k in names}
        elif args.all:
            selected = all_profiles
        else:
            default = get_default_profile()
            selected = {default: all_profiles[default]} if default in all_profiles else {}

        for profile_name, profile_conf in selected.items():
            model = profile_conf.get("model", "unknown")
            for task in tasks:
                for _ in range(args.repeat):
                    model_task_pairs.append((model, task, profile_name))

    test_file = Path(args.input or args.file or "") if (args.input or args.file) else find_test_file()
    if not test_file or not test_file.exists():
        print("ERROR: No test file found. Specify with --input.", file=sys.stderr)
        sys.exit(1)

    file_size = test_file.stat().st_size

    if args.dry_run:
        print(f"DRY RUN — would test {len(model_task_pairs)} runs:\n")
        for model, task, profile in model_task_pairs:
            label = f"[{profile}]" if profile else "[direct]"
            print(f"  {label} {model} -> {task} (timeout={args.timeout}s, input={test_file})")
        print(f"\nTotal: {len(model_task_pairs)} runs across {len(set(m for m,_,_ in model_task_pairs))} models")
        return 0

    if not args.json:
        print(f"Benchmark: file={test_file} ({file_size} bytes)")
        print(f"Models to test: {len(set(m for m,_,_ in model_task_pairs))}")
        print(f"Total runs: {len(model_task_pairs)} (repeat={args.repeat})")
        print(f"{'=' * 70}\n")

    results = []
    for model, task, profile in model_task_pairs:
        label = f"[{profile}] {model}" if profile else f"[direct] {model}"
        if not args.json:
            print(f"Testing {label} -> {task}...", end=" ", flush=True)

        if profile:
            r = run_benchmark(profile, model, task, test_file, args.timeout)
            r["model"] = model
            r["task"] = task
        else:
            r = run_model_benchmark(model, task, test_file, args.timeout)

        results.append(r)

        if not args.json:
            if r["ok"]:
                print(f"{r.get('duration_sec', r.get('elapsed_seconds', '?'))}s, {r['output_chars']} chars")
            elif r.get("timed_out"):
                print(f"TIMEOUT ({args.timeout}s)")
            else:
                err = (r.get("error") or "")[:80]
                print(f"FAILED: {err}")

    if not args.json:
        print(f"\n{'=' * 70}")
        print(f"\n{'Model':<40} {'Task':<22} {'Time':>7} {'Chars':>7} {'Status':<8}")
        print(f"{'-' * 40} {'-' * 22} {'-' * 7} {'-' * 7} {'-' * 8}")
        for r in sorted(results, key=lambda x: x.get("duration_sec", x.get("elapsed_seconds", 999))):
            status = "OK" if r["ok"] else ("TIMEOUT" if r.get("timed_out") else "FAIL")
            model_short = r["model"][:38] + ".." if len(r["model"]) > 40 else r["model"]
            dur = r.get("duration_sec", r.get("elapsed_seconds", 0))
            print(f"{model_short:<40} {r['task']:<22} {dur:>6.1f}s {r['output_chars']:>6} {status:<8}")

        ok_results = [r for r in results if r["ok"]]
        if ok_results:
            fastest = min(ok_results, key=lambda x: x.get("duration_sec", x.get("elapsed_seconds", 999)))
            most_output = max(ok_results, key=lambda x: x["output_chars"])
            print(f"\nFastest: {fastest['model']} ({fastest.get('duration_sec', fastest.get('elapsed_seconds', 0))}s)")
            print(f"Most output: {most_output['model']} ({most_output['output_chars']} chars)")

    # Save output
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    benchmark_output = {
        "task": args.task,
        "tasks": tasks,
        "input_file": str(test_file),
        "input_bytes": file_size,
        "repeat": args.repeat,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }

    json_path = args.output_json or str(out_dir / f"benchmark_{ts}.json")
    Path(json_path).write_text(json.dumps(benchmark_output, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.output_md:
        lines = [
            f"# Benchmark: {', '.join(tasks)}",
            f"\nInput: {test_file} ({file_size} bytes)",
            f"\nRuns: {len(results)} | Repeat: {args.repeat}",
            f"\nCreated: {benchmark_output['created_at']}",
            "\n| Model | Task | Duration | OK | Output |",
            "|---|---|---|---|---|",
        ]
        for r in sorted(results, key=lambda x: x.get("duration_sec", x.get("elapsed_seconds", 999))):
            dur = r.get("duration_sec", r.get("elapsed_seconds", 0))
            status = "OK" if r["ok"] else ("TIMEOUT" if r.get("timed_out") else "FAIL")
            lines.append(f"| {r['model']} | {r['task']} | {dur:.1f}s | {status} | {r['output_chars']} |")
        Path(args.output_md).write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(benchmark_output, indent=2, ensure_ascii=False))
    else:
        print(f"\nResults saved: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
