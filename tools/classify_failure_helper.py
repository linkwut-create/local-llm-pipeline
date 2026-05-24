#!/usr/bin/env python3
"""Manual test-failure classifier — advisory-only CLI helper.

Calls the existing classify-test-failure worker via local_llm_router.py.
Does NOT integrate with hooks, commit gate, release guard, background queue,
or any automation path.  Classification is advisory — never a gate.

Usage:
    py -3 tools/classify_failure_helper.py --stderr "AssertionError: ..."
    py -3 tools/classify_failure_helper.py --stderr-file /tmp/err.txt
    echo '{"stderr":"..."}' | py -3 tools/classify_failure_helper.py --stdin-json

Exit codes:
    0 = helper completed, classification produced
    2 = invalid input, worker not called
    3 = worker/router failure
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ROUTER_PATH = SCRIPT_DIR / "local_llm_router.py"
OUT_DIR = PROJECT_ROOT / ".local_llm_out"

_STDERR_MAX_CHARS = 50_000
_STDOUT_MAX_CHARS = 20_000
_TEST_COMMAND_MAX_CHARS = 1_000
_CHANGED_FILES_MAX = 50

_VALID_CLASSES = {
    "assertion", "import_error", "syntax_error", "dependency",
    "timeout", "environment", "flaky", "unknown",
}
_VALID_CONFIDENCE = {"low", "medium", "high"}


def _strip_json_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return s


def build_error(code: int, error_type: str, error: str, suggestion: str = "") -> dict:
    return {
        "ok": False,
        "error_type": error_type,
        "error": error,
        "suggestion": suggestion,
        "exit_code": code,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual test-failure classifier — advisory-only CLI helper.",
    )
    parser.add_argument("--stderr", type=str, default="")
    parser.add_argument("--stdout", type=str, default="")
    parser.add_argument("--exit-code", type=int, dest="exit_code", default=None)
    parser.add_argument("--test-command", type=str, default="")
    parser.add_argument("--changed-file", type=str, action="append", dest="changed_files", default=[])
    parser.add_argument("--profile", type=str, default="")
    parser.add_argument("--model", type=str, default="")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--stderr-file", type=str, default="")
    parser.add_argument("--stdout-file", type=str, default="")
    parser.add_argument("--stdin-json", action="store_true", dest="stdin_json")
    return parser.parse_args(argv)


def validate_inputs(args: argparse.Namespace) -> dict | None:
    """Return error dict if input is invalid, None if valid."""
    stderr_text = args.stderr or ""
    stdout_text = args.stdout or ""

    # --stdin-json is mutually exclusive with direct args and file args
    if args.stdin_json:
        if (args.stderr or args.stdout or str(args.exit_code) != "None"
                or args.test_command or args.changed_files
                or args.stderr_file or args.stdout_file
                or args.profile or args.model):
            return build_error(2, "invalid_input",
                               "--stdin-json cannot be combined with other input options",
                               "use --stdin-json alone, or use direct args without --stdin-json")
        return None  # valid — will parse from stdin later

    # --stderr-file / --stdout-file mutually exclusive with --stderr / --stdout
    if args.stderr_file and args.stderr:
        return build_error(2, "invalid_input",
                           "--stderr-file and --stderr are mutually exclusive")
    if args.stdout_file and args.stdout:
        return build_error(2, "invalid_input",
                           "--stdout-file and --stdout are mutually exclusive")

    if args.stderr_file:
        try:
            stderr_text = Path(args.stderr_file).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return build_error(2, "invalid_input",
                               f"stderr-file not found: {args.stderr_file}")
        except Exception as e:
            return build_error(2, "invalid_input",
                               f"cannot read stderr-file: {e}")

    if args.stdout_file:
        try:
            stdout_text = Path(args.stdout_file).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return build_error(2, "invalid_input",
                               f"stdout-file not found: {args.stdout_file}")
        except Exception as e:
            return build_error(2, "invalid_input",
                               f"cannot read stdout-file: {e}")

    if not stderr_text.strip() and not stdout_text.strip():
        return build_error(2, "invalid_input",
                           "at least one of stderr or stdout must be non-empty",
                           "provide test failure output to classify")

    # Store validated values back on args for downstream use
    args._stderr_text = stderr_text
    args._stdout_text = stdout_text
    return None


def parse_stdin_json() -> dict | None:
    """Parse JSON payload from stdin. Return error dict or parsed args-Namespace-like dict."""
    try:
        raw = sys.stdin.read()
    except Exception as e:
        return build_error(2, "invalid_input", f"cannot read stdin: {e}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return build_error(2, "invalid_input", f"stdin is not valid JSON: {e}")

    if not isinstance(data, dict):
        return build_error(2, "invalid_input", "stdin JSON must be a JSON object")

    stderr = data.get("stderr", "")
    stdout = data.get("stdout", "")
    exit_code = data.get("exit_code")
    test_command = data.get("test_command", "")
    changed_files = data.get("changed_files", [])

    if not isinstance(stderr, str):
        return build_error(2, "invalid_input", "stderr must be a string")
    if not isinstance(stdout, str):
        return build_error(2, "invalid_input", "stdout must be a string")
    if exit_code is not None and not isinstance(exit_code, int):
        return build_error(2, "invalid_input", "exit_code must be an int")
    if not isinstance(test_command, str):
        return build_error(2, "invalid_input", "test_command must be a string")
    if not isinstance(changed_files, list) or not all(isinstance(x, str) for x in changed_files):
        return build_error(2, "invalid_input", "changed_files must be a list of strings")

    if not stderr.strip() and not stdout.strip():
        return build_error(2, "invalid_input",
                           "at least one of stderr or stdout must be non-empty")

    return {
        "stderr": stderr,
        "stdout": stdout,
        "exit_code": exit_code,
        "test_command": test_command,
        "changed_files": changed_files,
        "profile": data.get("profile", ""),
        "model": data.get("model", ""),
    }


def truncate_and_build_payload(
    stderr_raw: str,
    stdout_raw: str,
    exit_code: int | None,
    test_command: str,
    changed_files: list[str],
) -> tuple[dict, dict]:
    """Truncate inputs and build the worker payload. Returns (payload, lengths_info)."""
    input_lengths = {
        "stderr": len(stderr_raw),
        "stdout": len(stdout_raw),
        "test_command": len(test_command),
        "changed_files": len(changed_files),
    }

    stderr_text = stderr_raw[:_STDERR_MAX_CHARS]
    stdout_text = stdout_raw[:_STDOUT_MAX_CHARS]
    tc_text = test_command[:_TEST_COMMAND_MAX_CHARS] if test_command else ""
    cf_list = changed_files[:_CHANGED_FILES_MAX] if changed_files else []

    truncated = (
        len(stderr_raw) > _STDERR_MAX_CHARS
        or len(stdout_raw) > _STDOUT_MAX_CHARS
        or len(test_command) > _TEST_COMMAND_MAX_CHARS
        or len(changed_files) > _CHANGED_FILES_MAX
    )

    payload = {
        "stderr": stderr_text,
        "stdout": stdout_text,
    }
    if exit_code is not None:
        payload["exit_code"] = exit_code
    if tc_text:
        payload["test_command"] = tc_text
    if cf_list:
        payload["changed_files"] = cf_list

    return payload, {"truncated": truncated, "input_lengths": input_lengths}


def call_router(payload: dict, profile: str = "", model: str = "") -> tuple[bool, str, str | None, float]:
    """Call the classify-test-failure worker via router. Returns (ok, stdout, output_path, elapsed)."""
    t0 = time.perf_counter()
    cmd = [
        sys.executable, str(ROUTER_PATH),
        "classify-test-failure", "--stdin",
    ]
    if profile:
        cmd.extend(["--profile", profile])
    if model:
        cmd.extend(["--model", model])

    stdin_data = json.dumps(payload, ensure_ascii=False)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return False, "", None, time.perf_counter() - t0
    except Exception as e:
        return False, str(e), None, time.perf_counter() - t0

    elapsed = time.perf_counter() - t0
    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0:
        return False, stderr or stdout or f"router exit code {result.returncode}", None, elapsed

    # Find the output file the router wrote
    output_path = find_router_output()
    return True, stdout, output_path, elapsed


def find_router_output() -> str | None:
    """Find the most recent classify-test-failure JSON written by the router."""
    candidates = sorted(
        OUT_DIR.glob("*_classify-test-failure.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return str(candidates[0].relative_to(PROJECT_ROOT))
    return None


def parse_worker_result(router_stdout: str, output_path: str | None) -> dict:
    """Parse the router/worker output for classification fields."""
    # Try reading the output JSON file first (has structured result)
    classification = None
    if output_path:
        try:
            raw = Path(PROJECT_ROOT, output_path).read_text(encoding="utf-8", errors="replace")
            router_result = json.loads(raw)
        except (json.JSONDecodeError, FileNotFoundError):
            router_result = None

        if isinstance(router_result, dict):
            result_field = router_result.get("result", "")
            w = None
            if isinstance(result_field, dict):
                inner = result_field.get("result", "")
                if isinstance(inner, str):
                    inner_stripped = _strip_json_code_fence(inner)
                    if inner_stripped.startswith("{"):
                        try:
                            w = json.loads(inner_stripped)
                        except json.JSONDecodeError:
                            w = None
                elif isinstance(inner, dict):
                    w = inner
                elif result_field.get("failure_class"):
                    w = result_field
            elif isinstance(result_field, str):
                field_stripped = _strip_json_code_fence(result_field)
                if field_stripped.startswith("{"):
                    try:
                        w = json.loads(field_stripped)
                    except json.JSONDecodeError:
                        w = None

            if isinstance(w, dict) and w.get("ok"):
                classification = w

    # Fallback: try parsing router stdout as JSON
    if classification is None:
        stdout_stripped = _strip_json_code_fence(router_stdout)
        if stdout_stripped.startswith("{"):
            try:
                classification = json.loads(stdout_stripped)
            except json.JSONDecodeError:
                pass

    return classification


def classify_failure(args: argparse.Namespace) -> dict:
    """Main classification flow. Returns result dict with exit_code key."""
    start = time.perf_counter()

    # --- input source ---
    if args.stdin_json:
        parsed = parse_stdin_json()
        if isinstance(parsed, dict) and parsed.get("ok") is False:
            return parsed  # error dict
        stderr_raw = parsed["stderr"]
        stdout_raw = parsed["stdout"]
        exit_code = parsed["exit_code"]
        test_command = parsed["test_command"]
        changed_files = parsed["changed_files"]
        profile = parsed.get("profile", "")
        model = parsed.get("model", "")
    else:
        validation_error = validate_inputs(args)
        if validation_error:
            return validation_error
        stderr_raw = getattr(args, "_stderr_text", args.stderr)
        stdout_raw = getattr(args, "_stdout_text", args.stdout)
        exit_code = args.exit_code
        test_command = args.test_command
        changed_files = args.changed_files or []
        profile = args.profile or ""
        model = args.model or ""

    # --- truncate ---
    payload, trunc_info = truncate_and_build_payload(
        stderr_raw, stdout_raw, exit_code, test_command, changed_files,
    )

    # --- call worker ---
    router_ok, router_stdout, output_path, router_elapsed = call_router(payload, profile, model)

    if not router_ok:
        return {
            "ok": False,
            "error_type": "worker_failure",
            "error": router_stdout or "router/worker call failed",
            "suggestion": "check Ollama is running and the model is available",
            "exit_code": 3,
            "elapsed_seconds": round(router_elapsed, 2),
        }

    # --- parse classification ---
    classification = parse_worker_result(router_stdout, output_path)

    if classification is None:
        return {
            "ok": False,
            "error_type": "worker_failure",
            "error": "could not parse classification from worker output",
            "suggestion": "check worker output file for details",
            "exit_code": 3,
            "elapsed_seconds": round(router_elapsed, 2),
            "output_path": output_path,
        }

    # --- validate and build result ---
    fc = classification.get("failure_class", "unknown")
    if fc not in _VALID_CLASSES:
        fc = "unknown"
    conf = classification.get("confidence", "low")
    if conf not in _VALID_CONFIDENCE:
        conf = "low"

    result = {
        "ok": True,
        "advisory_only": True,
        "failure_class": fc,
        "confidence": conf,
        "summary": classification.get("summary", ""),
        "likely_cause": classification.get("likely_cause", ""),
        "files_to_inspect": classification.get("files_to_inspect", []),
        "recommended_action": classification.get("recommended_action", ""),
        "truncated": trunc_info["truncated"],
        "input_lengths": trunc_info["input_lengths"],
        "output_path": output_path,
        "elapsed_seconds": round(time.perf_counter() - start, 2),
        "profile": profile or "code_worker",
        "model": classification.get("model", ""),
    }

    return result


def print_human(result: dict):
    """Print human-readable classification to stdout."""
    print(f"classification: {result.get('failure_class', '?')}")
    print(f"confidence:     {result.get('confidence', '?')}")
    print(f"summary:        {result.get('summary', '')}")
    print(f"likely_cause:   {result.get('likely_cause', '')}")
    files = result.get("files_to_inspect", [])
    print(f"files:          {', '.join(files) if files else '(none)'}")
    print(f"action:         {result.get('recommended_action', '')}")
    if result.get("truncated"):
        lengths = result.get("input_lengths", {})
        print(f"(input was truncated — original sizes: stderr={lengths.get('stderr',0)}, "
              f"stdout={lengths.get('stdout',0)})")
    out = result.get("output_path")
    if out:
        print(f"raw output:     {out}")


def main():
    args = parse_args(sys.argv[1:])
    result = classify_failure(args)

    # --- handle errors ---
    if not result.get("ok"):
        if args.json_output:
            json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            print(f"Error: {result.get('error', 'unknown error')}", file=sys.stderr)
            suggestion = result.get("suggestion", "")
            if suggestion:
                print(f"Tip: {suggestion}", file=sys.stderr)
        sys.exit(result.get("exit_code", 3))

    # --- success output ---
    exit_code_val = result.pop("exit_code", 0)
    if args.json_output:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print_human(result)

    sys.exit(exit_code_val)


if __name__ == "__main__":
    main()
