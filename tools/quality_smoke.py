#!/usr/bin/env python3
"""Local model output quality smoke — advisory-only CLI battery.

Runs a fixed set of summarize-file / review-diff / generate-test-plan calls
against known inputs, then runs heuristic checks on each output.  All checks
are advisory — this tool is NOT a gate, hook, or MCP participant.

Usage:
    py -3 tools/quality_smoke.py
    py -3 tools/quality_smoke.py --battery quick
    py -3 tools/quality_smoke.py --battery full --json
    py -3 tools/quality_smoke.py --profile fast_summary --timeout 180

Exit codes:
    0 = all checks pass (WARNs OK, no FAIL)
    1 = at least one FAIL detected
    2 = CLI/config/runtime error (no battery executed)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
WORKER_PATH = SCRIPT_DIR / "local_llm_worker.py"
OUT_DIR = PROJECT_ROOT / ".local_llm_out" / "quality_smoke"

SMOKE_VERSION = 1
DEFAULT_TIMEOUT = 120

_VALID_CONFIDENCE = {"high", "medium", "low"}

# ── Fixed input definitions ────────────────────────────────────────────
# Each entry: (task, target_description, cli_args, domain_keywords, latency_ceiling_ms)

FIXTURE_DIR = SCRIPT_DIR.parent / "tests" / "fixtures"
SMOKE_DIFF_PATH = FIXTURE_DIR / "smoke_diff.txt"

BATTERY_DEFAULT = [
    {
        "task": "summarize-file",
        "label": "summarize small source",
        "args": [str(SCRIPT_DIR / "model_call_result.py")],
        "keywords": ["ModelCallResult", "dataclass", "usage", "token"],
        "ceiling_ms": 120_000,
        "min_chars": 100,
    },
    {
        "task": "summarize-file",
        "label": "summarize medium doc",
        "args": [str(PROJECT_ROOT / "docs" / "mcp-task-policy.md")],
        "keywords": ["MCP", "task", "controller", "review"],
        "ceiling_ms": 120_000,
        "min_chars": 200,
    },
    {
        "task": "review-diff",
        "label": "review docs-only diff",
        "args": ["--stdin"],
        "stdin_source": "smoke_diff",
        "keywords": ["docs", "change"],
        "ceiling_ms": 90_000,
        "min_chars": 50,
    },
    {
        "task": "generate-test-plan",
        "label": "test-plan known test file",
        "args": [str(PROJECT_ROOT / "tests" / "test_model_call_result.py")],
        "keywords": ["test", "ModelCallResult", "usage", "normalize"],
        "ceiling_ms": 120_000,
        "min_chars": 100,
    },
]

BATTERY_QUICK = BATTERY_DEFAULT[:2]

BATTERY_FULL = BATTERY_DEFAULT

BATTERIES = {
    "default": BATTERY_DEFAULT,
    "quick": BATTERY_QUICK,
    "full": BATTERY_FULL,
}

SMOKE_DIFF_TEXT = """\
diff --git a/docs/Z_BASELINE.md b/docs/Z_BASELINE.md
index 15407a2..dummy123 100644
--- a/docs/Z_BASELINE.md
+++ b/docs/Z_BASELINE.md
@@ -10,7 +10,7 @@

-## 1. local-llm-pipeline Current Baseline
+## 1. local-llm-pipeline Updated Baseline

-Captured at Z-1 (2026-05-27):
+Captured at Z-2 (2026-05-27):

 | Item | Value |
"""


# ── Helpers ─────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_output(path: Path) -> dict | None:
    """Load a worker output JSON file. Returns None on failure."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None


def _check_empty(data: dict, min_chars: int) -> dict:
    result_text = data.get("result", "") or ""
    content_len = len(result_text.strip())
    ok = data.get("ok", False)
    if not ok:
        return {"check": "empty_output", "result": "fail",
                "detail": f"worker ok=false, error={data.get('error', 'unknown')}"}
    if content_len < 10:
        return {"check": "empty_output", "result": "fail",
                "detail": f"content: {content_len} chars (< 10)"}
    if content_len < min_chars:
        return {"check": "empty_output", "result": "warn",
                "detail": f"content: {content_len} chars (< {min_chars} minimum)"}
    return {"check": "empty_output", "result": "pass",
            "detail": f"content: {content_len} chars"}


def _check_off_target(data: dict, keywords: list[str], target_path: str) -> dict:
    result_text = (data.get("result", "") or "").lower()
    summary = (data.get("summary", "") or "").lower()
    combined = result_text + " " + summary
    target_name = Path(target_path).name.lower()
    keyword_hits = [kw for kw in keywords if kw.lower() in combined]
    if target_name not in combined and not keyword_hits:
        return {"check": "off_target", "result": "fail",
                "detail": f"target '{target_name}' not found, 0/{len(keywords)} keywords"}
    if target_name not in combined:
        return {"check": "off_target", "result": "warn",
                "detail": f"target filename not found, but {len(keyword_hits)}/{len(keywords)} keywords present"}
    return {"check": "off_target", "result": "pass",
            "detail": f"target and {len(keyword_hits)}/{len(keywords)} keywords found"}


def _check_malformed_json(data: dict) -> dict:
    result_raw = data.get("result", "")
    if isinstance(result_raw, str) and result_raw.strip().startswith("{"):
        try:
            json.loads(result_raw)
        except json.JSONDecodeError:
            return {"check": "malformed_json", "result": "fail",
                    "detail": "result field looks like JSON but does not parse"}
    return {"check": "malformed_json", "result": "pass",
            "detail": "no JSON parsing issues detected"}


def _check_confidence(data: dict) -> dict:
    confidence = data.get("confidence", "")
    if not confidence:
        return {"check": "abnormal_confidence", "result": "fail",
                "detail": "confidence field missing or empty"}
    if confidence not in _VALID_CONFIDENCE:
        return {"check": "abnormal_confidence", "result": "fail",
                "detail": f"confidence='{confidence}' not in {_VALID_CONFIDENCE}"}
    if confidence == "low":
        return {"check": "abnormal_confidence", "result": "warn",
                "detail": "confidence=low"}
    return {"check": "abnormal_confidence", "result": "pass",
            "detail": f"confidence={confidence}"}


def _collect_real_paths() -> set[str]:
    """Collect real file paths from the project for hallucination cross-check."""
    paths: set[str] = set()
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in {".git", ".local_llm_out", "__pycache__",
                                                  "node_modules", "venv", ".venv", "dist"}]
        for f in files:
            paths.add(Path(root, f).name.lower())
    return paths


def _check_hallucination(data: dict, real_paths: set[str]) -> dict:
    result_text = data.get("result", "") or ""
    fabricated: list[str] = []
    import re
    candidates = re.findall(r'`([a-zA-Z0-9_/.-]+\.[a-zA-Z]+)`', result_text)
    seen = set()
    for c in candidates:
        name = Path(c).name.lower()
        if name in seen:
            continue
        seen.add(name)
        if name not in real_paths and "/" not in c and "\\" not in c:
            fabricated.append(c)
    n = len(fabricated)
    if n > 3:
        return {"check": "hallucination", "result": "fail",
                "detail": f"{n} fabricated paths: {fabricated[:5]}"}
    if n > 0:
        return {"check": "hallucination", "result": "warn",
                "detail": f"{n} possible fabricated paths: {fabricated[:5]}"}
    return {"check": "hallucination", "result": "pass",
            "detail": "0 fabricated paths detected"}


def _check_latency(duration_ms: int, ceiling_ms: int) -> dict:
    if duration_ms > ceiling_ms * 1.5:
        return {"check": "latency", "result": "fail",
                "detail": f"{duration_ms}ms > {int(ceiling_ms * 1.5)}ms ceiling"}
    if duration_ms > ceiling_ms:
        return {"check": "latency", "result": "warn",
                "detail": f"{duration_ms}ms > {ceiling_ms}ms ceiling"}
    return {"check": "latency", "result": "pass",
            "detail": f"{duration_ms}ms within {ceiling_ms}ms ceiling"}


def _run_checks(data: dict, entry: dict, real_paths: set[str]) -> list[dict]:
    target_path = entry["args"][0] if entry["args"] and not entry["args"][0].startswith("--") else ""
    return [
        _check_empty(data, entry.get("min_chars", 50)),
        _check_off_target(data, entry.get("keywords", []), target_path),
        _check_malformed_json(data),
        _check_confidence(data),
        _check_hallucination(data, real_paths),
        _check_latency(data.get("_duration_ms", 0), entry.get("ceiling_ms", 120_000)),
    ]


def _run_one(entry: dict, profile: str, model: str, timeout: int) -> dict:
    """Run a single battery entry via direct worker subprocess call."""
    task = entry["task"]
    label = entry["label"]
    args = list(entry["args"])
    stdin_text = ""

    if entry.get("stdin_source") == "smoke_diff":
        stdin_text = SMOKE_DIFF_TEXT

    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out_path = out_dir / f"{ts}_{task}.json"

    cmd = [
        sys.executable, str(WORKER_PATH),
        task,
        "--profile", profile,
        "--model", model,
        "--output", str(out_path),
    ] + args

    started = time.time()
    try:
        if stdin_text:
            result = subprocess.run(
                cmd, input=stdin_text, text=True, encoding="utf-8", errors="replace",
                capture_output=True, timeout=timeout)
        else:
            result = subprocess.run(
                cmd, text=True, encoding="utf-8", errors="replace",
                capture_output=True, timeout=timeout)
        duration_ms = int((time.time() - started) * 1000)
    except subprocess.TimeoutExpired:
        duration_ms = timeout * 1000
        return {
            "task": task, "label": label, "profile": profile, "model": model,
            "duration_ms": duration_ms, "output_path": str(out_path),
            "worker_ok": False, "worker_error": "timeout",
            "checks": [{"check": "latency", "result": "fail",
                        "detail": f"worker timed out after {timeout}s"}],
        }
    except OSError as exc:
        return {
            "task": task, "label": label, "profile": profile, "model": model,
            "duration_ms": 0, "output_path": str(out_path),
            "worker_ok": False, "worker_error": str(exc),
            "checks": [{"check": "empty_output", "result": "fail",
                        "detail": f"worker failed to start: {exc}"}],
        }

    data = _load_output(out_path)
    if data is None:
        # Worker may have written output to stdout instead of file.
        # Try parsing stdout.
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return {
                "task": task, "label": label, "profile": profile, "model": model,
                "duration_ms": duration_ms, "output_path": str(out_path),
                "worker_ok": False, "worker_error": "no_output_file",
                "checks": [{"check": "empty_output", "result": "fail",
                            "detail": "worker produced no parseable output"}],
            }

    data["_duration_ms"] = duration_ms

    real_paths = _collect_real_paths()
    checks = _run_checks(data, entry, real_paths)

    return {
        "task": task,
        "label": label,
        "profile": profile,
        "model": model,
        "duration_ms": duration_ms,
        "output_path": str(out_path),
        "worker_ok": data.get("ok", False),
        "checks": checks,
    }


def _build_report(call_results: list[dict], profile: str, model: str,
                  battery_name: str, baseline_commit: str) -> dict:
    all_checks: list[dict] = []
    for cr in call_results:
        all_checks.extend(cr.get("checks", []))

    total = len(all_checks)
    passed = sum(1 for c in all_checks if c["result"] == "pass")
    warned = sum(1 for c in all_checks if c["result"] == "warn")
    failed = sum(1 for c in all_checks if c["result"] == "fail")

    overall = "pass" if failed == 0 else "degraded"

    return {
        "smoke_version": SMOKE_VERSION,
        "generated_at": _now_iso(),
        "baseline_commit": baseline_commit,
        "baseline_version": "0.12.0",
        "battery": battery_name,
        "profile": profile,
        "model": model,
        "summary": {
            "total_checks": total,
            "passed": passed,
            "warned": warned,
            "failed": failed,
            "overall": overall,
        },
        "calls": call_results,
        "advisory_only": True,
        "not_a_gate": True,
    }


def _get_baseline_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ── CLI ─────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local model output quality smoke — advisory-only CLI battery.")
    parser.add_argument("--battery", choices=["default", "quick", "full"],
                        default="default",
                        help="Smoke battery size (default: 4 calls, quick: 2, full: 4)")
    parser.add_argument("--output-dir", type=str, default=str(OUT_DIR),
                        help=f"Output directory (default: {OUT_DIR})")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Print JSON report to stdout")
    parser.add_argument("--profile", type=str, default="fast_summary",
                        help="Profile for summarize tasks")
    parser.add_argument("--review-profile", type=str, default="commit_reviewer",
                        help="Profile for review-diff tasks")
    parser.add_argument("--test-plan-profile", type=str, default="code_worker",
                        help="Profile for generate-test-plan tasks")
    parser.add_argument("--model", type=str, default="",
                        help="Model override (passed to worker)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Per-call timeout in seconds (default: {DEFAULT_TIMEOUT})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    global OUT_DIR
    OUT_DIR = Path(args.output_dir)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    battery = BATTERIES.get(args.battery, BATTERY_DEFAULT)

    call_results: list[dict] = []
    for entry in battery:
        task = entry["task"]
        if task == "review-diff":
            profile = args.review_profile
        elif task == "generate-test-plan":
            profile = args.test_plan_profile
        else:
            profile = args.profile

        model = args.model
        if model:
            entry["_explicit_model"] = model

        cr = _run_one(entry, profile, model, args.timeout)
        call_results.append(cr)

    baseline_commit = _get_baseline_commit()
    report = _build_report(call_results, args.profile, args.model,
                           args.battery, baseline_commit)

    # Write report to output dir
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = OUT_DIR / f"smoke_report_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = report["summary"]
        print(f"Smoke {report['battery']} battery: {s['overall'].upper()}")
        print(f"  {s['passed']}/{s['total_checks']} passed, "
              f"{s['warned']} warned, {s['failed']} failed")
        for cr in call_results:
            failures = [c for c in cr["checks"] if c["result"] == "fail"]
            warns = [c for c in cr["checks"] if c["result"] == "warn"]
            status = "PASS" if not failures else "FAIL"
            extra = ""
            if warns:
                extra += f" ({len(warns)} warns)"
            print(f"  {cr['label']}: {status}{extra}")
        print(f"Report: {report_path}")

    failed = report["summary"]["failed"]
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
