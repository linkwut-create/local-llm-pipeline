#!/usr/bin/env python3
"""Cross-project feedback ledger — manual, CLI-only, append-only JSONL.

Tracks what happened to pipeline suggestions across target projects.
Controllers (Claude Code / Codex) write entries manually.  No automatic
writes from pipeline tools — this keeps the ledger a trusted signal source.

Usage:
    py -3 tools/feedback_ledger.py record \\
        --target-project local-translator-agent \\
        --suggestion-type review_flag \\
        --suggestion-summary "duplicated import in tm_service.py" \\
        --disposition converted_to_fix \\
        --evidence "commit a4c12d2 consolidated the import"

    py -3 tools/feedback_ledger.py summary --format json
    py -3 tools/feedback_ledger.py by-target --format table

Storage: .local_llm_out/feedback/feedback.jsonl (one JSON object per line)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
FEEDBACK_DIR = PROJECT_ROOT / ".local_llm_out" / "feedback"
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.jsonl"

VALID_DISPOSITIONS = frozenset({
    "accepted", "rejected", "false_positive", "converted_to_fix", "deferred",
})

VALID_SUGGESTION_TYPES = frozenset({
    "review_flag", "test_gap", "docs_gap", "risk_note",
    "refactor_suggestion", "baseline_audit", "cost_finding", "quality_finding",
})

FORBIDDEN_KEYS = frozenset({
    "api_key", "token", "password", "secret", "authorization",
    "private_key", "credential", "passphrase",
})

FORBIDDEN_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),     # OpenAI-style keys
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),     # GitHub tokens
    re.compile(r"-----BEGIN.*PRIVATE KEY-----", re.IGNORECASE),
]

MAX_FIELD_LENGTH = {
    "suggestion_summary": 300,
    "evidence": 500,
    "controller_notes": 500,
}

REQUIRED_FIELDS = frozenset({
    "target_project", "suggestion_type", "suggestion_summary", "disposition",
})


# ── Helpers ─────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"fb_{uuid.uuid4().hex[:12]}"


def _detect_project() -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT))
        if result.returncode == 0:
            url = result.stdout.strip()
            name = url.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            return name
    except Exception:
        pass
    return PROJECT_ROOT.name


def _detect_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT))
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _redact_secrets(text: str) -> str:
    for pattern in FORBIDDEN_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _has_forbidden_keys(obj: dict) -> list[str]:
    found: list[str] = []
    for key in obj:
        key_lower = key.lower()
        for fk in FORBIDDEN_KEYS:
            if fk in key_lower:
                found.append(key)
    return found


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[:max_len - 3] + "..."


def _sanitize_record(record: dict) -> dict:
    clean: dict = {}
    bad_keys = _has_forbidden_keys(record)
    for key, value in record.items():
        if key.lower() in FORBIDDEN_KEYS or key.lower() in (fk.lower() for fk in FORBIDDEN_KEYS):
            continue
        if isinstance(value, str):
            value = _redact_secrets(value)
            max_len = MAX_FIELD_LENGTH.get(key)
            if max_len is not None:
                value = _truncate(value, max_len)
        clean[key] = value
    if bad_keys:
        clean["_redacted_keys"] = bad_keys
    return clean


# ── Core operations ──────────────────────────────────────────────────────

def build_record(*,
                 target_project: str,
                 suggestion_type: str,
                 suggestion_summary: str,
                 disposition: str,
                 evidence: str = "",
                 target_commit: str = "",
                 feedback_impact: str = "",
                 controller_notes: str = "",
                 source_project: str = "",
                 source_commit: str = "",
                 created_by: str = "",
                 pipeline_tool: str = "",
                 related_request_id: str = "",
                 privacy_flags: list[str] | None = None) -> dict:
    """Assemble a feedback record dict. Does not write anything."""

    if not source_project:
        source_project = _detect_project()
    if not source_commit:
        source_commit = _detect_commit()

    raw = {
        "id": _new_id(),
        "timestamp": _now_iso(),
        "source_project": source_project,
        "target_project": target_project,
        "source_commit": source_commit,
        "target_commit": target_commit,
        "suggestion_type": suggestion_type,
        "suggestion_summary": suggestion_summary,
        "disposition": disposition,
        "evidence": evidence,
        "feedback_impact": feedback_impact,
        "controller_notes": controller_notes,
        "created_by": created_by or os.environ.get("USER", "unknown"),
        "pipeline_tool": pipeline_tool,
        "related_request_id": related_request_id,
        "privacy_flags": privacy_flags or [],
    }
    return _sanitize_record(raw)


def validate_record(record: dict) -> tuple[bool, list[str]]:
    """Check required fields and enum values. Returns (valid, errors)."""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not record.get(field):
            errors.append(f"missing required field: {field}")
    if record.get("disposition") and record["disposition"] not in VALID_DISPOSITIONS:
        errors.append(f"invalid disposition: {record['disposition']}")
    if record.get("suggestion_type") and record["suggestion_type"] not in VALID_SUGGESTION_TYPES:
        errors.append(f"invalid suggestion_type: {record['suggestion_type']}")
    return len(errors) == 0, errors


def record_feedback(record: dict, path: Path | None = None) -> tuple[bool, str]:
    """Append a feedback record to the JSONL ledger. Never raises.

    Returns (ok, message). Validates before writing.
    """
    target = path if path else FEEDBACK_FILE
    valid, errors = validate_record(record)
    if not valid:
        return False, "validation failed: " + "; ".join(errors)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True, f"recorded {record['id']} → {target}"
    except OSError as exc:
        return False, f"write failed: {exc}"


def read_feedback(path: Path | None = None) -> list[dict]:
    """Read all feedback records. Returns [] if missing. Skips malformed lines."""
    target = path if path else FEEDBACK_FILE
    if not target.exists():
        return []
    records: list[dict] = []
    try:
        with open(target, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
    except OSError:
        return records
    return records


def summarize_feedback(records: list[dict]) -> dict:
    """Aggregate feedback records into a summary."""
    total = len(records)
    dispositions: dict[str, int] = {}
    suggestion_types: dict[str, int] = {}
    targets: dict[str, int] = {}
    for r in records:
        d = r.get("disposition", "unknown") or "unknown"
        dispositions[d] = dispositions.get(d, 0) + 1
        st = r.get("suggestion_type", "unknown") or "unknown"
        suggestion_types[st] = suggestion_types.get(st, 0) + 1
        tp = r.get("target_project", "unknown") or "unknown"
        targets[tp] = targets.get(tp, 0) + 1
    return {
        "total_entries": total,
        "by_disposition": dict(sorted(dispositions.items())),
        "by_suggestion_type": dict(sorted(suggestion_types.items())),
        "by_target_project": dict(sorted(targets.items())),
    }


def by_target(records: list[dict]) -> dict[str, dict]:
    """Group feedback entries by target_project."""
    buckets: dict[str, list[dict]] = {}
    for r in records:
        tp = r.get("target_project", "unknown") or "unknown"
        buckets.setdefault(tp, []).append(r)
    result: dict[str, dict] = {}
    for tp, recs in buckets.items():
        disp: dict[str, int] = {}
        for r in recs:
            d = r.get("disposition", "unknown") or "unknown"
            disp[d] = disp.get(d, 0) + 1
        result[tp] = {
            "total": len(recs),
            "by_disposition": dict(sorted(disp.items())),
        }
    return dict(sorted(result.items(), key=lambda kv: kv[1]["total"], reverse=True))


# ── CLI ─────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cross-project feedback ledger — manual, CLI-only, append-only.")
    p.add_argument("--path", type=str, default=str(FEEDBACK_FILE),
                   help=f"Path to feedback JSONL file (default: {FEEDBACK_FILE})")
    p.add_argument("--format", choices=("table", "json"), default="table",
                   help="Output format")
    sub = p.add_subparsers(dest="command", required=True)

    sp_rec = sub.add_parser("record", help="Write a new feedback entry")
    sp_rec.add_argument("--target-project", required=True)
    sp_rec.add_argument("--suggestion-type", required=True)
    sp_rec.add_argument("--suggestion-summary", required=True)
    sp_rec.add_argument("--disposition", required=True)
    sp_rec.add_argument("--evidence", default="")
    sp_rec.add_argument("--target-commit", default="")
    sp_rec.add_argument("--feedback-impact", default="")
    sp_rec.add_argument("--controller-notes", default="")
    sp_rec.add_argument("--source-project", default="")
    sp_rec.add_argument("--source-commit", default="")
    sp_rec.add_argument("--created-by", default="")
    sp_rec.add_argument("--pipeline-tool", default="")
    sp_rec.add_argument("--related-request-id", default="")
    sp_rec.set_defaults(func=cmd_record)

    sub.add_parser("summary", help="Aggregate overview").set_defaults(func=cmd_summary)

    sub.add_parser("by-target", help="Breakdown by target_project").set_defaults(func=cmd_by_target)

    return p


def cmd_record(args: argparse.Namespace) -> int:
    record = build_record(
        target_project=args.target_project,
        suggestion_type=args.suggestion_type,
        suggestion_summary=args.suggestion_summary,
        disposition=args.disposition,
        evidence=args.evidence,
        target_commit=args.target_commit,
        feedback_impact=args.feedback_impact,
        controller_notes=args.controller_notes,
        source_project=args.source_project,
        source_commit=args.source_commit,
        created_by=args.created_by,
        pipeline_tool=args.pipeline_tool,
        related_request_id=args.related_request_id,
    )
    ok, msg = record_feedback(record, Path(args.path))
    if args.format == "json":
        print(json.dumps({"ok": ok, "message": msg, "record": record if ok else None},
                         ensure_ascii=False, indent=2))
    else:
        print(msg)
    return 0 if ok else 1


def cmd_summary(args: argparse.Namespace) -> int:
    records = read_feedback(Path(args.path))
    summary = summarize_feedback(records)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Feedback ledger: {summary['total_entries']} entries")
        print(f"By disposition:")
        for d, c in summary["by_disposition"].items():
            print(f"  {d}: {c}")
        print(f"By suggestion type:")
        for st, c in summary["by_suggestion_type"].items():
            print(f"  {st}: {c}")
        print(f"By target project:")
        for tp, c in summary["by_target_project"].items():
            print(f"  {tp}: {c}")
    return 0


def cmd_by_target(args: argparse.Namespace) -> int:
    records = read_feedback(Path(args.path))
    buckets = by_target(records)
    if args.format == "json":
        print(json.dumps(buckets, ensure_ascii=False, indent=2))
    else:
        if not buckets:
            print("(no records)")
            return 0
        print(f"{'Target project':<30} {'Total':>6}  Dispositions")
        print("-" * 60)
        for tp, info in buckets.items():
            disp_str = ", ".join(f"{d}={c}" for d, c in info["by_disposition"].items())
            print(f"{tp:<30} {info['total']:>6}  {disp_str}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
