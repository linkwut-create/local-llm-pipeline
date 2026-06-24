"""Pipeline Flash Worker — constrained cloud-model execution contracts.

Flash workers use low-cost cloud models (DeepSeek v4 Flash) for
mid-complexity tasks. All output is advisory — candidates only.

CRITICAL RULES (enforced by contract, not by model instruction):
  - NEVER commit, push, deploy, or modify source files directly
  - Patch output MUST be unified diff format
  - All output goes to artifact store as candidate artifacts
  - Controller (Pro/User) MUST approve before application
"""

from __future__ import annotations

import json
import os
import re
import sys
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from pipeline_local_worker import WorkerContract, WORKERS as ALL_WORKERS, register


# ═══════════════════════════════════════════════════════════════
# Flash worker contracts
# ═══════════════════════════════════════════════════════════════

test_failure_analyzer = register(WorkerContract(
    name="flash_test_failure_analyzer",
    description="Analyze test failures using Flash, produce structured hypotheses",
    input_schema={
        "type": "object",
        "required": ["stderr"],
        "properties": {
            "stderr": {"type": "string"},
            "stdout": {"type": "string"},
            "exit_code": {"type": "integer"},
            "test_command": {"type": "string"},
            "changed_files": {"type": "array", "items": {"type": "string"}},
        },
    },
    output_schema={
        "type": "object",
        "required": ["failure_hypotheses", "repair_strategy"],
        "properties": {
            "failure_hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hypothesis": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "evidence": {"type": "string"},
                    },
                },
            },
            "repair_strategy": {
                "type": "object",
                "properties": {
                    "approach": {"type": "string"},
                    "files_to_modify": {"type": "array", "items": {"type": "string"}},
                    "estimated_complexity": {"type": "string",
                                              "enum": ["trivial", "small", "medium", "large"]},
                    "risks": {"type": "array", "items": {"type": "string"}},
                },
            },
            "requires_pro_escalation": {"type": "boolean"},
        },
    },
    artifact_type="flash_failure_analysis",
    max_input_chars=80000,
    timeout_sec=1000,
    may_read_source=True,
))

patch_worker = register(WorkerContract(
    name="flash_patch_worker",
    description="Generate a patch candidate as unified diff. NEVER applies directly.",
    input_schema={
        "type": "object",
        "required": ["task_description", "target_files"],
        "properties": {
            "task_description": {"type": "string"},
            "target_files": {"type": "array", "items": {"type": "string"}},
            "context": {"type": "string", "description": "Relevant code or error context"},
            "constraints": {"type": "array", "items": {"type": "string"}},
        },
    },
    output_schema={
        "type": "object",
        "required": ["patch", "explanation"],
        "properties": {
            "patch": {"type": "string", "description": "Unified diff format patch"},
            "explanation": {"type": "string"},
            "risk_note": {"type": "string"},
            "suggested_tests": {"type": "array", "items": {"type": "string"}},
            "files_modified": {"type": "array", "items": {"type": "string"}},
            "rollback_instructions": {"type": "string"},
        },
    },
    artifact_type="flash_patch_candidate",
    max_input_chars=100000,
    timeout_sec=1000,
    may_read_source=True,
    # Patch worker is the most dangerous — extra restrictions
    forbidden_actions=("edit", "write", "commit", "push", "deploy", "apply"),
))

diff_reviewer = register(WorkerContract(
    name="flash_diff_reviewer",
    description="Review a git diff using Flash for quick feedback",
    input_schema={
        "type": "object",
        "required": ["diff_text"],
        "properties": {
            "diff_text": {"type": "string"},
            "context": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["verdict", "findings"],
        "properties": {
            "verdict": {"type": "string", "enum": ["looks_good", "needs_review", "blocked"]},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": [
                            "bug", "style", "perf", "security", "test_gap", "compat"]},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "description": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
        },
    },
    artifact_type="flash_review",
    max_input_chars=80000,
    timeout_sec=1000,
    may_read_source=False,
))


# ═══════════════════════════════════════════════════════════════
# Unified diff validator
# ═══════════════════════════════════════════════════════════════

def is_unified_diff(text: str) -> bool:
    """Check if text looks like a unified diff."""
    if not text or not isinstance(text, str):
        return False
    lines = text.strip().split("\n")
    if not lines:
        return False
    # Must have at least one hunk header (@@ ... @@)
    has_hunk = any(re.match(r'^@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@', l) for l in lines)
    # Must have diff header indicators
    has_header = any(l.startswith("--- ") or l.startswith("+++ ") or l.startswith("diff ")
                      for l in lines)
    return has_hunk or has_header


def validate_patch(patch_text: str) -> tuple[bool, str]:
    """Validate that a patch is a safe unified diff.

    Returns (valid, reason).
    """
    if not patch_text or not isinstance(patch_text, str):
        return False, "patch is empty or not a string"
    if not is_unified_diff(patch_text):
        return False, "patch does not appear to be a unified diff (missing @@ hunk headers)"
    # Reject patches that try to modify sensitive files
    for line in patch_text.split("\n"):
        if line.startswith("--- ") or line.startswith("+++ "):
            fname = line[4:].strip().lower()
            if any(s in fname for s in (".env", ".key", ".pem", "id_rsa", "credentials")):
                return False, f"patch attempts to modify sensitive file: {fname}"
    # Reject patches that try to execute shell commands
    if re.search(r'[;&|`$]\s*(rm\s+-rf|wget|curl|bash|sh\b)', patch_text):
        return False, "patch contains suspicious shell commands"
    return True, "valid unified diff"


# ═══════════════════════════════════════════════════════════════
# Flash worker runner
# ═══════════════════════════════════════════════════════════════

def _call_flash(prompt: str, timeout: int = 1000) -> tuple[str, dict]:
    """Call DeepSeek v4 Flash via the local worker infrastructure."""
    import time as _time
    t0 = _time.monotonic()

    metrics = {"model": "deepseek-v4-flash", "ok": False,
               "latency_sec": 0, "input_chars": len(prompt),
               "output_chars": 0, "error": None}

    worker_script = Path(__file__).parent / "local_llm_worker.py"
    if not worker_script.exists():
        return "", metrics

    # Use DeepSeek Pro endpoint (cloud, but flash tier)
    env = os.environ.copy()
    # If local worker is configured, use it; otherwise note that Flash requires cloud
    try:
        result = subprocess.run(
            [sys.executable or "python3", str(worker_script), "flash worker task"],
            input=prompt, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            env=env,
        )
        output = (result.stdout or "").strip()
        if result.returncode == 0 and output:
            metrics["ok"] = True
        else:
            err = (result.stderr or "")[:500]
            if not output:
                output = err
            metrics["error"] = err
        metrics["output_chars"] = len(output)
    except subprocess.TimeoutExpired:
        metrics["error"] = "timeout"
        output = ""
    except Exception as e:
        metrics["error"] = str(e)[:200]
        output = ""

    metrics["latency_sec"] = round(_time.monotonic() - t0, 3)
    return output, metrics


def run_flash_worker(worker_name: str, task_id: str, inputs: dict,
                     task_description: str = "flash task") -> dict | None:
    """Run a Flash worker, validate output, save as candidate artifact."""
    contract = ALL_WORKERS.get(worker_name)
    # Also check our own workers
    if contract is None:
        # Try local registry
        for w in (test_failure_analyzer, patch_worker, diff_reviewer):
            if w.name == worker_name:
                contract = w
                break
    if contract is None:
        return None

    prompt_parts = [
        f"Task: {task_description[:500]}",
        f"Worker: {contract.name} — {contract.description}",
        f"\nInput:",
        json.dumps(inputs, ensure_ascii=False, indent=2),
        f"\nOutput schema (JSON only, no markdown):",
        json.dumps(contract.output_schema, ensure_ascii=False, indent=2),
    ]
    if "patch" in contract.output_schema.get("required", []):
        prompt_parts.append(
            "\nIMPORTANT: The 'patch' field MUST be a valid unified diff format. "
            "Each hunk must start with @@ -line,count +line,count @@."
        )
    prompt = "\n".join(prompt_parts)

    if len(prompt) > contract.max_input_chars:
        prompt = prompt[:contract.max_input_chars]

    output, metrics = _call_flash(prompt, timeout=contract.timeout_sec)

    # Parse JSON from output
    result = None
    patch_text = None
    if output:
        try:
            match = re.search(r'\{.*\}', output, re.DOTALL)
            if match:
                result = json.loads(match.group())
                # Extract patch for validation
                if isinstance(result, dict):
                    patch_text = result.get("patch")
        except Exception:
            pass

    # Validations
    validations = []
    if contract.name == "flash_patch_worker" and patch_text:
        valid, reason = validate_patch(patch_text)
        validations.append({"patch_valid": valid, "reason": reason})
        if not valid:
            result = (result or {})
            result["_patch_rejected"] = True
            result["_patch_rejection_reason"] = reason

    # Save to artifact store
    from pipeline_artifact_store import save_artifact
    # Save parsed JSON
    save_artifact(
        task_id, f"{worker_name}.json",
        json.dumps(result, ensure_ascii=False, indent=2) if result else (output or "(no output)"),
        artifact_type=contract.artifact_type,
        tool_name="pipeline_flash_worker",
        creator="deepseek-v4-flash",
        metadata={"contract": worker_name, "metrics": metrics,
                  "validations": validations},
    )
    # Save patch separately if present
    if patch_text:
        save_artifact(
            task_id, f"{worker_name}_patch.diff",
            patch_text,
            artifact_type="patch_candidate",
            tool_name="pipeline_flash_worker",
            creator="deepseek-v4-flash",
            metadata={"worker": worker_name},
        )

    return {
        "worker": worker_name,
        "parsed": result,
        "metrics": metrics,
        "validations": validations,
        "artifact": f"{worker_name}.json",
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Pipeline Flash Worker — constrained cloud-model execution")
    sub = parser.add_subparsers(dest="cmd")

    list_cmd = sub.add_parser("list", help="List flash workers")
    run_cmd = sub.add_parser("run", help="Run a flash worker")
    run_cmd.add_argument("worker", help="Worker name")
    run_cmd.add_argument("task_id", help="Task ID")
    run_cmd.add_argument("--input", default=None, help="JSON input file or '-' for stdin")
    run_cmd.add_argument("--description", default="flash task")
    validate_cmd = sub.add_parser("validate-patch", help="Validate a patch file")
    validate_cmd.add_argument("file", help="Patch file to validate")

    args = parser.parse_args()
    try:
        if args.cmd == "list":
            for name in ("test_failure_analyzer", "patch_worker", "diff_reviewer"):
                c = ALL_WORKERS.get(name)
                print(f"  {name:30s}  {c.description if c else ''}")
        elif args.cmd == "run":
            inputs = {}
            if args.input == "-":
                inputs = json.loads(sys.stdin.read())
            elif args.input:
                inputs = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = run_flash_worker(args.worker, args.task_id, inputs, args.description)
            if result is None:
                print(f"Worker not found: {args.worker}", file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        elif args.cmd == "validate-patch":
            text = Path(args.file).read_text(encoding="utf-8")
            valid, reason = validate_patch(text)
            print(f"Valid: {valid}\nReason: {reason}")
        else:
            parser.print_help()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
