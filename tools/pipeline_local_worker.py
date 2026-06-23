"""Pipeline Local Worker — structured local-model execution contracts.

Each worker defines:
  - input schema: what data it needs
  - output schema: what artifact it produces
  - limits: max_chars, timeout, forbidden actions
  - artifact type: for the artifact store

Workers NEVER edit source files. All output goes to artifacts/.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# Worker contract
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkerContract:
    """Defines the bounds of a single pipeline worker invocation."""
    name: str
    description: str
    input_schema: dict          # JSON Schema for inputs
    output_schema: dict         # JSON Schema for outputs
    max_input_chars: int = 60000
    max_output_chars: int = 8000
    timeout_sec: int = 120
    artifact_type: str = "local_worker_output"
    may_read_artifacts: bool = True
    may_read_source: bool = True
    may_call_model: bool = True
    forbidden_actions: tuple[str, ...] = ("edit", "write", "commit", "push", "deploy")


# ═══════════════════════════════════════════════════════════════
# Worker registry
# ═══════════════════════════════════════════════════════════════

WORKERS: dict[str, WorkerContract] = {}


def register(contract: WorkerContract) -> WorkerContract:
    WORKERS[contract.name] = contract
    return contract


# ═══════════════════════════════════════════════════════════════
# Defined workers
# ═══════════════════════════════════════════════════════════════

log_summary = register(WorkerContract(
    name="log_summary",
    description="Analyze test failure logs and produce a structured failure summary",
    input_schema={
        "type": "object",
        "required": ["stderr"],
        "properties": {
            "stderr": {"type": "string", "description": "Test failure stderr"},
            "stdout": {"type": "string", "description": "Optional test stdout"},
            "exit_code": {"type": "integer"},
            "test_command": {"type": "string"},
            "changed_files": {"type": "array", "items": {"type": "string"}},
        },
    },
    output_schema={
        "type": "object",
        "required": ["failure_type", "summary", "hypotheses"],
        "properties": {
            "failure_type": {"type": "string", "enum": ["assertion", "import_error", "syntax_error",
                                 "timeout", "segfault", "unknown"]},
            "summary": {"type": "string"},
            "hypotheses": {"type": "array", "items": {"type": "string"}},
            "likely_cause": {"type": "string"},
            "suggested_fix": {"type": "string"},
        },
    },
    artifact_type="log_summary",
))

file_summary = register(WorkerContract(
    name="file_summary",
    description="Summarize a source file: purpose, key functions, dependencies, issues",
    input_schema={
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "question": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["purpose", "key_functions", "dependencies"],
        "properties": {
            "purpose": {"type": "string"},
            "key_functions": {"type": "array", "items": {"type": "string"}},
            "dependencies": {"type": "array", "items": {"type": "string"}},
            "potential_issues": {"type": "array", "items": {"type": "string"}},
            "suggested_tests": {"type": "array", "items": {"type": "string"}},
        },
    },
    artifact_type="file_summary",
    max_input_chars=100000,
))

diff_review = register(WorkerContract(
    name="diff_review",
    description="Review a git diff for bugs, test gaps, compatibility, and security",
    input_schema={
        "type": "object",
        "required": ["diff_text"],
        "properties": {
            "diff_text": {"type": "string"},
            "commit_gate": {"type": "boolean"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["problems", "test_gaps", "recommendation"],
        "properties": {
            "problems": {"type": "array", "items": {"type": "object", "properties": {
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "description": {"type": "string"},
                "location": {"type": "string"},
            }}},
            "test_gaps": {"type": "array", "items": {"type": "string"}},
            "compatibility_risks": {"type": "array", "items": {"type": "string"}},
            "security_concerns": {"type": "array", "items": {"type": "string"}},
            "recommendation": {"type": "string", "enum": ["approve", "review", "reject"]},
        },
    },
    artifact_type="diff_review",
    max_input_chars=80000,
    timeout_sec=180,
))

repo_map = register(WorkerContract(
    name="repo_map",
    description="Produce a structured map of the repository: subsystems, entrypoints, risks",
    input_schema={
        "type": "object",
        "required": ["file_list"],
        "properties": {
            "file_list": {"type": "array", "items": {"type": "string"}},
            "config_files": {"type": "array", "items": {"type": "string"}},
            "test_dirs": {"type": "array", "items": {"type": "string"}},
        },
    },
    output_schema={
        "type": "object",
        "required": ["subsystems", "entrypoints"],
        "properties": {
            "subsystems": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "purpose": {"type": "string"},
            }}},
            "entrypoints": {"type": "array", "items": {"type": "string"}},
            "test_mapping": {"type": "object"},
            "risk_areas": {"type": "array", "items": {"type": "string"}},
            "suggested_reading_order": {"type": "array", "items": {"type": "string"}},
        },
    },
    artifact_type="repo_map",
    max_input_chars=50000,
))


# ═══════════════════════════════════════════════════════════════
# Worker runner
# ═══════════════════════════════════════════════════════════════

def _detect_python() -> str:
    if sys.executable:
        return sys.executable
    return "python3"


def _call_local_worker(task_description: str, prompt: str,
                       timeout: int = 120) -> tuple[str, dict]:
    """Call the local LLM worker via subprocess. Returns (output, metrics)."""
    import time as _time
    t0 = _time.monotonic()

    worker_script = Path(__file__).parent / "local_llm_worker.py"
    if not worker_script.exists():
        return "", {"ok": False, "error": "worker script not found"}

    metrics = {"ok": False, "latency_sec": 0, "input_chars": len(prompt),
               "output_chars": 0, "error": None}

    try:
        result = subprocess.run(
            [_detect_python(), str(worker_script), task_description],
            input=prompt, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        output = (result.stdout or "").strip()
        if result.returncode != 0:
            err = (result.stderr or "")[:500]
            metrics["error"] = err
            if not output:
                output = err
        else:
            metrics["ok"] = True
        metrics["output_chars"] = len(output)
        metrics["latency_sec"] = round(_time.monotonic() - t0, 3)
        return output, metrics
    except subprocess.TimeoutExpired:
        metrics["error"] = "timeout"
        metrics["latency_sec"] = round(_time.monotonic() - t0, 3)
        return "", metrics
    except Exception as e:
        metrics["error"] = str(e)[:200]
        metrics["latency_sec"] = round(_time.monotonic() - t0, 3)
        return "", metrics


def run_worker(worker_name: str, task_id: str, inputs: dict,
               task_description: str = "pipeline task") -> dict | None:
    """Run a named worker, save output as artifact, return result dict.

    Returns None if the worker is not found.
    """
    contract = WORKERS.get(worker_name)
    if contract is None:
        return None

    # Build prompt from contract + inputs
    prompt_parts = [
        f"Task: {task_description[:500]}",
        f"Worker: {contract.name} — {contract.description}",
        f"\nInput:",
        json.dumps(inputs, ensure_ascii=False, indent=2),
        f"\nOutput schema (JSON only, no markdown):",
        json.dumps(contract.output_schema, ensure_ascii=False, indent=2),
    ]
    prompt = "\n".join(prompt_parts)

    # Truncate input if needed
    if len(prompt) > contract.max_input_chars:
        prompt = prompt[:contract.max_input_chars]

    output, metrics = _call_local_worker(prompt, prompt, timeout=contract.timeout_sec)

    # Try to parse structured output
    result = None
    if output:
        try:
            # Try to extract JSON from output
            import re
            match = re.search(r'\{.*\}', output, re.DOTALL)
            if match:
                result = json.loads(match.group())
        except Exception:
            pass

    # Save to artifact store
    from pipeline_artifact_store import save_artifact
    save_artifact(
        task_id, f"{worker_name}.json",
        output or "(no output)",
        artifact_type=contract.artifact_type,
        tool_name="pipeline_local_worker",
        creator=metrics.get("model", "local-model"),
        metadata={"contract": worker_name, "metrics": metrics,
                  "parsed": result is not None},
    )

    # Save raw output
    save_artifact(
        task_id, f"{worker_name}_raw.txt",
        output or "(no output)",
        artifact_type=contract.artifact_type,
        tool_name="pipeline_local_worker",
        creator="local-model",
        metadata={"metrics": metrics},
    )

    return {
        "worker": worker_name,
        "parsed": result,
        "metrics": metrics,
        "artifact": f"{worker_name}.json",
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Pipeline Local Worker — structured local-model execution")
    sub = parser.add_subparsers(dest="cmd")

    list_cmd = sub.add_parser("list", help="List available workers")

    run_cmd = sub.add_parser("run", help="Run a worker")
    run_cmd.add_argument("worker", help="Worker name")
    run_cmd.add_argument("task_id", help="Task ID for artifact storage")
    run_cmd.add_argument("--input", default=None, help="JSON input file or '-' for stdin")
    run_cmd.add_argument("--description", default="pipeline task", help="Task description")

    contract_cmd = sub.add_parser("contract", help="Show worker contract")
    contract_cmd.add_argument("worker", help="Worker name")

    args = parser.parse_args()

    try:
        if args.cmd == "list":
            for name, c in WORKERS.items():
                print(f"  {name:20s}  {c.description}")
            return 0
        elif args.cmd == "run":
            if args.input == "-":
                inputs = json.loads(sys.stdin.read())
            elif args.input:
                inputs = json.loads(Path(args.input).read_text(encoding="utf-8"))
            else:
                inputs = {}
            result = run_worker(args.worker, args.task_id, inputs, args.description)
            if result is None:
                print(f"Worker not found: {args.worker}", file=sys.stderr)
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        elif args.cmd == "contract":
            c = WORKERS.get(args.worker)
            if c is None:
                print(f"Worker not found: {args.worker}", file=sys.stderr)
                return 1
            print(json.dumps(asdict(c), ensure_ascii=False, indent=2, default=str))
            return 0
        else:
            parser.print_help()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
