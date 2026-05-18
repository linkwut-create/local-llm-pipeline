#!/usr/bin/env python3
"""Run every active profile against a test file. Small models in parallel,
large models serial. Records pass/fail, elapsed time, and key findings count."""

import subprocess, sys, json, time, os
from pathlib import Path
from collections import defaultdict

TOOLS = Path(__file__).parent.parent / "tools"
PROFILES = json.loads((TOOLS / "local_llm_profiles.json").read_text(encoding="utf-8"))
TASKS = json.loads((TOOLS / "local_llm_tasks.json").read_text(encoding="utf-8"))

TEST_FILE = str(Path(__file__).parent / "test_fixture_bugs.py")

# Model size thresholds (GB, approximate)
SMALL_THRESHOLD_GB = 25  # models under this can run in parallel
LARGE_THRESHOLD_GB = 50  # models over this need serial + cooldown

# Maps profile to estimated VRAM footprint (from profile metadata or model name)
SIZE_MAP = {
    "gemma4:e4b": 10, "qwen3.5-claude-opus-9b-q8_0:latest": 10,
    "qwen3-coder:30b": 18, "qwen3-coder-next-q8:latest": 86,
    "qwen3.6:27b-q8-ud": 35, "qwen3.6:35b-q8-ud": 38,
    "qwen3.5-27b-reasoning:latest": 28, "qwen3.5-35b-q8:latest": 48,
    "gemma4-26b-it:q8_0": 26, "gpt-oss-120b-f16:latest": 65,
    "mistral-medium-3.5-128b-q5_k_xl:latest": 88,
    "nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-q8_k_xl:latest": 39,
    "deepseek-r1-distill-qwen:32b-q8-fixed": 34,
    "glm-4.7-flash-q8:latest": 35, "nomic-embed-text-v2-moe:latest": 1,
    "mistral-small-119b:q6": 89,
}


def estimate_size_gb(model_name):
    for key, sz in SIZE_MAP.items():
        if key in model_name or model_name in key:
            return sz
    # Heuristic: parse number from model name
    import re
    match = re.search(r'(\d+)b', model_name)
    if match:
        return int(match.group(1))
    return 30


def run_test(profile_name, task, timeout_s=600):
    """Run a single test. Returns (profile, task, ok, elapsed, error_summary)."""
    cmd = [
        sys.executable, str(TOOLS / "local_llm_router.py"),
        task, TEST_FILE,
        "--profile", profile_name,
        "--json-only",
    ]
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                timeout=timeout_s, cwd=str(TOOLS.parent))
        elapsed = time.time() - start
        ok = result.returncode == 0
        error = ""
        if not ok:
            error = (result.stderr + result.stdout)[:200]
        return (profile_name, task, ok, elapsed, error)
    except subprocess.TimeoutExpired:
        return (profile_name, task, False, timeout_s, "TIMEOUT")
    except Exception as e:
        return (profile_name, task, False, time.time() - start, str(e))


def main():
    profiles_data = PROFILES["profiles"]
    tasks_data = TASKS["tasks"]

    # Build test queue: each profile with its primary task
    test_queue = []
    for pname, pconf in profiles_data.items():
        if pname == "embedding":
            continue  # skip embedding
        use_for = pconf.get("use_for", [])
        if not use_for:
            continue
        # Pick the most representative task
        task = use_for[0]
        model = pconf.get("model", "")
        size_gb = estimate_size_gb(model)
        test_queue.append((pname, task, model, size_gb))

    # Sort: small models first, then large
    test_queue.sort(key=lambda x: x[3])

    results = []
    small_batch = []

    for pname, task, model, size_gb in test_queue:
        is_small = size_gb < SMALL_THRESHOLD_GB

        if is_small and len(small_batch) < 3:
            small_batch.append((pname, task, model, size_gb))
            continue

        # Flush small batch in parallel
        if small_batch:
            print(f"\n=== Parallel batch ({len(small_batch)} small models) ===")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                futures = {ex.submit(run_test, p, t): (p, t) for p, t, m, s in small_batch}
                for fut in concurrent.futures.as_completed(futures):
                    r = fut.result()
                    results.append(r)
                    status = "OK" if r[2] else "FAIL"
                    print(f"  [{status}] {r[0]:30s} {r[1]:25s} {r[3]:.0f}s {r[4][:80]}")
            small_batch = []
            # Small cooldown
            time.sleep(5)

        # Run large model serial
        if not is_small:
            print(f"\n=== Serial (large model: {size_gb}GB) ===")
            print(f"  Running {pname} ({model[:50]})...")
            r = run_test(pname, task, timeout_s=900)
            results.append(r)
            status = "OK" if r[2] else "FAIL"
            print(f"  [{status}] {r[0]:30s} {r[1]:25s} {r[3]:.0f}s {r[4][:80]}")
            # Cooldown: wait for model unload
            print(f"  Waiting 120s for model unload...")
            time.sleep(120)

    # Flush remaining small batch
    if small_batch:
        print(f"\n=== Final parallel batch ({len(small_batch)} small models) ===")
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futures = {ex.submit(run_test, p, t): (p, t) for p, t, m, s in small_batch}
            for fut in concurrent.futures.as_completed(futures):
                r = fut.result()
                results.append(r)
                status = "OK" if r[2] else "FAIL"
                print(f"  [{status}] {r[0]:30s} {r[1]:25s} {r[3]:.0f}s {r[4][:80]}")

    # Summary
    print(f"\n{'='*80}")
    print(f"RESULTS: {len(results)} profiles tested")
    ok_count = sum(1 for r in results if r[2])
    fail_count = len(results) - ok_count
    print(f"  Pass: {ok_count}, Fail: {fail_count}")
    for r in results:
        if not r[2]:
            print(f"  FAIL: {r[0]} ({r[1]}) — {r[4][:120]}")

    # Save results
    out_path = TOOLS.parent / ".local_llm_out" / "benchmark_all_results.json"
    out_path.parent.mkdir(exist_ok=True)
    json.dump([{"profile": r[0], "task": r[1], "ok": r[2], "elapsed": r[3], "error": r[4]}
               for r in results], out_path.open("w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nResults saved: {out_path}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
