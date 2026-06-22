#!/usr/bin/env python3
"""
Local LLM Debate — multi-model cross-review for a single input.

Three rounds max: coder → reasoning → deep reviewer.
Read-only: never modifies source files.

Usage:
    git diff | python tools/local_llm_debate.py review-diff --stdin
    python tools/local_llm_debate.py risk-analysis docs/plan.md
    python tools/local_llm_debate.py architecture-review docs/local-llm-worker.md
    python tools/local_llm_debate.py review-diff changes.patch --fast
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from local_llm_worker import (
    BLOCKED_PATHS, BLOCKED_EXTENSIONS, BLOCKED_FILENAMES,
    WorkerConfig, _resolve_provider, _resolve_endpoint,
    call_model, is_blocked_path, read_file_safe,
    collect_tree,
)

# P2-C3.1: import call_ledger for per-round debate records.
# Best-effort — debate must not fail if ledger is unavailable.
try:
    from call_ledger import build_record as _ledger_build, record_call as _ledger_record
except Exception:
    _ledger_build = _ledger_record = None

# B1-C3: fields that may be merged into debate round ledger records from
# LOCAL_LLM_LEDGER_EXTRA.  Debate-authoritative fields (debate_mode,
# debate_rounds, debate_round_index, debate_trigger, mcp_tool_name,
# source) are NOT in this set — they can never be overridden by env.
_DEBATE_ENV_MERGEABLE_KEYS = frozenset({
    "diff_risk_level",
    "diff_risk_confidence",
    "debate_skipped",
    "debate_skip_reason",
    "preclassifier_profile",
    "preclassifier_model",
    "preclassifier_request_id",
    "safety_blockers",
    "debate_skip_allowed",
    "skip_debate_recommended",
    "preclassifier_method",
    "changed_files_count",
})


def _load_ledger_env_extra_for_debate() -> dict:
    """Read LOCAL_LLM_LEDGER_EXTRA and return only B1-C3-mergeable fields.

    Never raises.  Returns {} on any failure.
    """
    raw = os.environ.get("LOCAL_LLM_LEDGER_EXTRA")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if k in _DEBATE_ENV_MERGEABLE_KEYS and v is not None}

PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"
TASKS_PATH = SCRIPT_DIR / "local_llm_tasks.json"

MAX_ROUNDS = 3

MAX_FINDINGS = {
    "high_confidence_findings": 5,
    "candidate_findings": 8,
    "disputed_findings": 8,
    "controller_must_verify": 10,
    "test_gaps": 10,
}

DEBATE_TASKS = {
    "review-diff", "risk-analysis", "architecture-review", "failure-mode-analysis",
}

DEFAULT_ROUND_PROFILES = ["commit_reviewer", "fast_summary", "reasoning_checker"]

ROUND_SYSTEM_BASE = """You are a local auxiliary review model, NOT the final decision-maker.
Rules:
- You CANNOT modify files.
- You CANNOT claim you ran tests.
- You CANNOT fabricate project facts.
- You can ONLY analyze based on the provided input and prior round outputs.
- When information is insufficient, say "INSUFFICIENT".
- Your output MUST be structured.
- Final conclusions are made by the controller (Claude Code / Codex), not you.
"""

ROUND_PROMPTS = {
    1: {
        "review-diff": """Round 1: Initial code review of this diff.

Find:
1. Implementation problems (bugs, logic errors, missing edge cases)
2. Test gaps (what is untested or under-tested)
3. Compatibility risks (breaking changes, API changes, dependency issues)
4. Security concerns

Do NOT over-speculate. Only report issues you can justify from the diff.
Output structured sections: PROBLEMS, TEST_GAPS, COMPATIBILITY_RISKS, SECURITY, UNCERTAIN.""",

        "risk-analysis": """Round 1: Initial risk analysis of this content.

Find:
1. Failure modes (what can go wrong)
2. Cascading risks (what fails if this fails)
3. Recovery gaps (what has no fallback)
4. External dependencies that could break

Do NOT claim exhaustive coverage.
Output structured sections: FAILURE_MODES, CASCADE_RISKS, RECOVERY_GAPS, EXTERNAL_RISKS, UNCERTAIN.""",

        "architecture-review": """Round 1: Initial architecture review.

Analyze:
1. Component responsibilities (clear or muddled)
2. Coupling and cohesion issues
3. Scalability concerns
4. Maintainability risks
5. Missing abstractions or over-abstraction

Output structured sections: RESPONSIBILITIES, COUPLING, SCALABILITY, MAINTAINABILITY, UNCERTAIN.""",

        "failure-mode-analysis": """Round 1: Initial failure mode analysis.

Enumerate:
1. Single points of failure
2. Race conditions or timing issues
3. Resource exhaustion scenarios
4. Data corruption paths
5. Partial failure states

Output structured sections: SINGLE_POINTS, TIMING, RESOURCES, DATA_CORRUPTION, PARTIAL_FAILURES, UNCERTAIN.""",
    },
    2: {
        "_default": """Round 2: Challenge the Round 1 analysis.

You received the original input AND Round 1's output. Your job:
1. Find logical flaws in Round 1's reasoning
2. Identify over-speculation (claims without evidence from the input)
3. Find missed boundary conditions Round 1 overlooked
4. Mark unreliable conclusions
5. Do NOT repeat Round 1 content — only add NEW observations

Output structured sections: LOGICAL_FLAWS, OVER_SPECULATION, MISSED_BOUNDARIES, UNRELIABLE_CONCLUSIONS, NEW_OBSERVATIONS.""",
    },
    3: {
        "_default": """Round 3: Synthesize Rounds 1 and 2 into a final candidate report.

You received the original input, Round 1's output, and Round 2's critique.
Classify every finding into exactly one category:

1. HIGH_CONFIDENCE: Both rounds agree, evidence is clear from input
2. CANDIDATE: Plausible but needs controller verification
3. DISPUTED: Rounds disagree — state both sides
4. CONTROLLER_MUST_VERIFY: Cannot be determined without running tests or reading more code

Also list:
- TEST_GAPS: What should be tested but isn't
- WARNINGS: Process or methodology concerns

Do NOT claim the review is complete. The controller will make final decisions.""",
    },
}


def load_profiles() -> dict:
    if not PROFILES_PATH.exists():
        return {}
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8")).get("profiles", {})


# v0.10.0-M: resolve_base_url delegates to the shared _resolve_endpoint in
# local_llm_worker so worker and debate use the same priority chain.
# args_base_url is accepted so CLI --base-url overrides env vars.
def resolve_base_url(provider: str, args_base_url: str | None = None) -> str:
    return _resolve_endpoint(provider, args_base_url)


def _format_call_error(e: Exception) -> str:
    """Build a diagnostic error string that distinguishes failure types.

    requests.HTTPError's str() is just the response body — e.g. "fail" when
    Ollama returns HTTP 500.  This helper prepends the status code so the
    ledger and CLI output can distinguish "HTTP 500: fail" (model load
    failure) from "HTTP 404: Not Found" (missing model) from "ConnectionError"
    or "Timeout".
    """
    try:
        import requests as _requests
    except ImportError:
        return f"{type(e).__name__}: {e}"[:300]

    if isinstance(e, _requests.HTTPError):
        status = "?"
        body = ""
        try:
            resp = getattr(e, "response", None)
            if resp is not None:
                status = resp.status_code
                body = (resp.text or "")[:200].replace("\n", " ").strip()
        except Exception:
            pass
        return f"HTTP {status}: {body}"[:300]
    if isinstance(e, _requests.ConnectionError):
        return f"ConnectionError: {e}"[:300]
    if isinstance(e, _requests.Timeout):
        return f"Timeout: {e}"[:300]
    return f"{type(e).__name__}: {e}"[:300]


def get_round_prompt(round_num: int, task: str) -> str:
    round_prompts = ROUND_PROMPTS.get(round_num, {})
    return round_prompts.get(task, round_prompts.get("_default", f"Round {round_num}: Analyze the input."))


def _emit_debate_round_ledger(
    *,
    task_type: str,
    profile: str,
    provider: str,
    model: str,
    success: bool,
    elapsed_seconds: float,
    input_text: str,
    output_text: str,
    usage: dict | None,
    error: str | None,
    debate_round_index: int,
    debate_rounds: int,
    debate_trigger: str,
) -> None:
    """Write one call ledger record per debate round.  Never raises.

    B1-C3: merges preclassifier fields from LOCAL_LLM_LEDGER_EXTRA
    (safely) then overrides with debate-authoritative fields.
    ``debate_skipped`` and ``debate_skip_allowed`` are forced to
    ``False`` while the debate runner is executing.
    """
    if not (_ledger_build and _ledger_record):
        return
    try:
        input_tokens = None
        output_tokens = None
        cached_tokens = None
        cache_miss_tokens = None
        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            cached_tokens = usage.get("cached_tokens")
            cache_miss_tokens = usage.get("cache_miss_tokens")

        # B1-C3: merge preclassifier fields from env, then force
        # debate-authoritative fields and safety invariants.
        extra = _load_ledger_env_extra_for_debate()
        extra["debate_mode"] = True
        extra["debate_rounds"] = debate_rounds
        extra["debate_round_index"] = debate_round_index
        extra["debate_trigger"] = debate_trigger
        extra["mcp_tool_name"] = "local_debate_review_diff"
        extra["source"] = debate_trigger
        # Hard safety invariants — if the debate runner is executing,
        # the debate was NOT skipped and skipping is NOT allowed.
        extra["debate_skipped"] = False
        extra["debate_skip_allowed"] = False

        rec = _ledger_build(
            task_type=task_type,
            tool_name="local_debate_review_diff",
            profile=profile,
            model=model,
            provider=provider,
            input_chars=len(input_text),
            output_chars=len(output_text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_miss_tokens=cache_miss_tokens,
            duration_ms=int(elapsed_seconds * 1000),
            success=success,
            failure_reason=error,
            result_summary=(output_text[:300] if output_text else None),
            extra=extra,
        )
        _ledger_record(rec)
    except Exception:
        pass  # ledger failures must never break debate output


def run_round(round_num: int, task: str, original_input: str,
              prior_outputs: list[str], profile_name: str,
              profiles: dict, provider: str, timeout: int,
              max_output_chars: int,
              total_rounds: int = MAX_ROUNDS,
              debate_trigger: str = "cli",
              base_url: str | None = None) -> dict:
    profile = profiles.get(profile_name, {})
    model = profile.get("model", "unknown")

    config = WorkerConfig(
        provider=provider,
        model=model,
        profile=profile_name,
        base_url=base_url or resolve_base_url(provider),
        timeout=timeout,
        max_output_chars=max_output_chars or profile.get("max_output_chars", 5000),
        api_key=os.environ.get("LOCAL_LLM_API_KEY", "").strip(),
    )

    system = ROUND_SYSTEM_BASE + f"\nTask: {task}\nRound: {round_num} of {MAX_ROUNDS}\nProfile: {profile_name}\n"
    round_prompt = get_round_prompt(round_num, task)

    user_parts = [round_prompt, "\n\n=== ORIGINAL INPUT ===\n", original_input]
    for i, prior in enumerate(prior_outputs, 1):
        user_parts.append(f"\n\n=== ROUND {i} OUTPUT ===\n")
        user_parts.append(prior)
    user = "\n".join(user_parts)

    start = time.time()
    try:
        # P2-C3.1: capture full ModelCallResult to extract real provider
        # usage for the call ledger instead of dropping it.
        model_result = call_model(system, user, config)
        raw = model_result.content
        usage = getattr(model_result, "usage", None)
        elapsed = round(time.time() - start, 2)
        _emit_debate_round_ledger(
            task_type=f"debate-{task}",
            profile=profile_name,
            provider=provider,
            model=model,
            success=True,
            elapsed_seconds=elapsed,
            input_text=user,
            output_text=raw or "",
            usage=usage if isinstance(usage, dict) else None,
            error=None,
            debate_round_index=round_num,
            debate_rounds=total_rounds,
            debate_trigger=debate_trigger,
        )
        return {
            "round": round_num,
            "profile": profile_name,
            "model": model,
            "summary": raw[:500] if raw else "",
            "raw_output": raw,
            "elapsed_seconds": elapsed,
            "ok": True,
            "error": None,
        }
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        error_str = _format_call_error(e)
        _emit_debate_round_ledger(
            task_type=f"debate-{task}",
            profile=profile_name,
            provider=provider,
            model=model,
            success=False,
            elapsed_seconds=elapsed,
            input_text=user,
            output_text="",
            usage=None,
            error=error_str,
            debate_round_index=round_num,
            debate_rounds=total_rounds,
            debate_trigger=debate_trigger,
        )
        return {
            "round": round_num,
            "profile": profile_name,
            "model": model,
            "summary": "",
            "raw_output": "",
            "elapsed_seconds": elapsed,
            "ok": False,
            "error": error_str,
        }


def classify_findings(rounds: list[dict]) -> dict:
    """Extract structured findings from the best available round output.

    In 3-round mode, the last round (synthesis) produces structured findings.
    In 2-round (fast) mode, the second round is a critic — attempt to parse it
    for structured headers; if none found, fall back to round 1 and extract
    substantive lines as candidate findings."""
    synthesis_round = None
    for r in reversed(rounds):
        if r.get("ok") and r.get("raw_output"):
            synthesis_round = r
            break

    result = {
        "high_confidence_findings": [],
        "candidate_findings": [],
        "disputed_findings": [],
        "controller_must_verify": [],
        "test_gaps": [],
    }

    if not synthesis_round:
        return result

    raw = synthesis_round["raw_output"]
    lines = raw.split("\n")

    current_section = None
    section_map = {
        "high_confidence": "high_confidence_findings",
        "high confidence": "high_confidence_findings",
        "candidate": "candidate_findings",
        "disputed": "disputed_findings",
        "controller_must_verify": "controller_must_verify",
        "controller must verify": "controller_must_verify",
        "test_gap": "test_gaps",
        "test gap": "test_gaps",
    }

    for line in lines:
        lower = line.lower().strip()
        for keyword, section in section_map.items():
            if keyword in lower and (lower.startswith("#") or lower.startswith("**") or lower.endswith(":")):
                current_section = section
                break
        else:
            if current_section and line.strip() and not line.strip().startswith("#"):
                clean = line.strip().lstrip("-*• ").strip()
                if clean and len(clean) > 5:
                    result[current_section].append(clean)

    # Fallback: if no structured findings were extracted and we only have 2 rounds
    # (fast mode), try round 1's output or extract substantive lines as
    # low-confidence candidate findings.
    has_any = any(result[k] for k in result)
    if not has_any and len(rounds) > 0:
        # Try the first successful round (coder output) — more likely to have
        # findings than the critic.
        for r in rounds:
            if r.get("ok") and r.get("raw_output"):
                fallback_raw = r["raw_output"]
                for line in fallback_raw.split("\n"):
                    clean = line.strip().lstrip("-*•# ").strip()
                    if clean and len(clean) > 10 and not clean.lower().startswith("debate"):
                        result["candidate_findings"].append(clean)
                if result["candidate_findings"]:
                    break

    for key, limit in MAX_FINDINGS.items():
        if key in result:
            result[key] = result[key][:limit]

    return result


def build_markdown(task: str, rounds: list[dict], findings: dict,
                   models: dict, elapsed_total: float,
                   summary_only: bool = False) -> str:
    lines = [
        f"# Debate: {task}",
        f"\nTotal time: {elapsed_total:.1f}s | Rounds: {len(rounds)}",
        f"\nModels: {', '.join(f'{k}={v}' for k, v in models.items())}",
        "",
    ]

    if not summary_only:
        for r in rounds:
            status = "OK" if r["ok"] else f"FAILED: {r.get('error', 'unknown')}"
            lines.append(f"## Round {r['round']}: {r['profile']} ({r['model']}) [{r['elapsed_seconds']}s] {status}")
            lines.append("")
            if r.get("raw_output"):
                lines.append(r["raw_output"])
            lines.append("")

    lines.append("## Synthesis")
    lines.append("")
    for category, items in findings.items():
        if items:
            lines.append(f"### {category}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")

    lines.append("---")
    lines.append("**Not verified:** Local models did not run tests, did not modify code. Controller must verify all important claims.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Multi-model debate cross-review")
    parser.add_argument("task", choices=sorted(DEBATE_TASKS),
                        help="Debate task type")
    parser.add_argument("input", nargs="?", default=None,
                        help="Input file or directory path")
    parser.add_argument("--stdin", action="store_true",
                        help="Read input from stdin (e.g. git diff)")
    parser.add_argument("--rounds", type=int, default=3,
                        help="Number of rounds (max 3)")
    parser.add_argument("--fast", action="store_true",
                        help="Skip deep_reviewer, only run coder + reasoning (2 rounds)")
    parser.add_argument("--profiles", default=None,
                        help="Comma-separated profile names for each round")
    parser.add_argument("--max-chars", type=int, default=None,
                        help="Max input characters")
    parser.add_argument("--max-output-chars", type=int, default=None,
                        help="Max output characters per round")
    parser.add_argument("--output-dir", default=".local_llm_out",
                        help="Output directory")
    parser.add_argument("--json-only", action="store_true",
                        help="Only write JSON, not Markdown")
    parser.add_argument("--no-markdown", action="store_true",
                        help="Alias for --json-only")
    parser.add_argument("--provider", default=None,
                        choices=["ollama", "openai-compatible"])
    parser.add_argument("--base-url", default=None,
                        help="Override the model endpoint base URL")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout per round in seconds")
    parser.add_argument("--summary-only", action="store_true",
                        help="Output only findings summary (no per-round details)")
    parser.add_argument("--debate-trigger", default="cli",
                        choices=["cli", "manual-mcp", "auto-escalate"],
                        help="Trigger context for call ledger (default: cli)")

    args = parser.parse_args()

    num_rounds = min(args.rounds, MAX_ROUNDS)
    if args.fast:
        num_rounds = min(num_rounds, 2)

    all_profiles = load_profiles()
    if not all_profiles:
        print("ERROR: No profiles found in local_llm_profiles.json.", file=sys.stderr)
        sys.exit(1)

    if args.profiles:
        round_profiles = args.profiles.split(",")[:num_rounds]
    elif args.fast:
        round_profiles = DEFAULT_ROUND_PROFILES[:2]
    else:
        round_profiles = DEFAULT_ROUND_PROFILES[:num_rounds]

    for p in round_profiles:
        if p not in all_profiles:
            print(f"ERROR: Profile '{p}' not found in profiles.json.", file=sys.stderr)
            sys.exit(1)

    # Read input
    if args.stdin:
        original_input = sys.stdin.read()
        input_source = "stdin"
    elif args.input:
        input_path = Path(args.input)
        if is_blocked_path(input_path):
            print(f"ERROR: Path '{args.input}' is blocked.", file=sys.stderr)
            sys.exit(1)
        if input_path.is_dir():
            max_chars = args.max_chars or all_profiles.get(round_profiles[0], {}).get("max_chars", 60000)
            original_input, warnings, _ = collect_tree(input_path, max_files=20, max_chars=max_chars)
        elif input_path.is_file():
            max_chars = args.max_chars or all_profiles.get(round_profiles[0], {}).get("max_chars", 60000)
            original_input, warnings = read_file_safe(input_path, max_chars)
        else:
            print(f"ERROR: '{args.input}' not found.", file=sys.stderr)
            sys.exit(1)
        input_source = str(args.input)
    else:
        print("ERROR: Provide input file/dir or --stdin.", file=sys.stderr)
        sys.exit(1)

    if not original_input.strip():
        print("ERROR: Empty input.", file=sys.stderr)
        sys.exit(1)

    models = {p: all_profiles[p].get("model", "unknown") for p in round_profiles}

    print(f"Debate: task={args.task} rounds={num_rounds} input={input_source}", file=sys.stderr)
    print(f"Profiles: {' → '.join(round_profiles)}", file=sys.stderr)
    print(f"Models: {', '.join(f'{k}={v}' for k, v in models.items())}", file=sys.stderr)
    print("", file=sys.stderr)

    rounds = []
    prior_outputs = []
    total_start = time.time()

    # v0.10.0-M: resolve provider and endpoint once for all rounds via the
    # shared helpers from local_llm_worker — same priority chain as the
    # worker so the two can never silently diverge.
    resolved_provider = _resolve_provider(args.provider)
    resolved_base_url = _resolve_endpoint(resolved_provider, args.base_url)

    for i, profile_name in enumerate(round_profiles, 1):
        print(f"Round {i}/{num_rounds}: {profile_name} ({models[profile_name]})...", end=" ", flush=True, file=sys.stderr)

        result = run_round(
            round_num=i,
            task=args.task,
            original_input=original_input,
            prior_outputs=prior_outputs,
            profile_name=profile_name,
            profiles=all_profiles,
            provider=resolved_provider,
            base_url=resolved_base_url,
            timeout=args.timeout,
            max_output_chars=args.max_output_chars,
            total_rounds=num_rounds,
            debate_trigger=args.debate_trigger,
        )
        rounds.append(result)

        if result["ok"]:
            prior_outputs.append(result["raw_output"])
            print(f"{result['elapsed_seconds']}s", file=sys.stderr)
        else:
            print(f"FAILED: {result.get('error', 'unknown')[:80]}", file=sys.stderr)

    elapsed_total = round(time.time() - total_start, 2)

    findings = classify_findings(rounds)

    # Clean rounds for JSON output (remove raw_output to keep size manageable)
    clean_rounds = []
    for r in rounds:
        clean = dict(r)
        raw = clean.pop("raw_output", "")
        if r["round"] == 1:
            clean["findings"] = [l.strip() for l in raw.split("\n") if l.strip() and not l.strip().startswith("#")][:20]
            clean["warnings"] = []
        elif r["round"] == 2:
            clean["criticisms"] = [l.strip() for l in raw.split("\n") if l.strip() and not l.strip().startswith("#")][:20]
            clean["disputed_points"] = []
        elif r["round"] == 3:
            clean["synthesis"] = [l.strip() for l in raw.split("\n") if l.strip() and not l.strip().startswith("#")][:30]
        clean.pop("ok", None)
        clean.pop("error", None)
        clean_rounds.append(clean)

    all_ok = all(r["ok"] for r in rounds)
    error_msg = None if all_ok else "; ".join(
        f"Round {r['round']}: {r['error']}" for r in rounds if not r["ok"]
    )

    output = {
        "task": args.task,
        "mode": "debate",
        "profiles": round_profiles,
        "models": models,
        "ok": all_ok,
        "input": {"source": input_source, "chars": len(original_input)},
        "high_confidence_findings": findings["high_confidence_findings"],
        "candidate_findings": findings["candidate_findings"],
        "controller_must_verify": findings["controller_must_verify"],
        "not_verified": [
            "Local models did not run tests",
            "Local models did not modify code",
            "Controller must verify all important claims",
        ],
        "warnings": [],
        "error": error_msg,
        "elapsed_seconds": elapsed_total,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not args.summary_only:
        output["rounds"] = clean_rounds
        output["disputed_findings"] = findings["disputed_findings"]
        output["test_gaps"] = findings["test_gaps"]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"{ts}_debate-{args.task}.json"
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    if not args.json_only and not args.no_markdown:
        md = build_markdown(args.task, rounds, findings, models, elapsed_total,
                            summary_only=args.summary_only)
        md_path = out_dir / f"{ts}_debate-{args.task}.md"
        md_path.write_text(md, encoding="utf-8")

    print(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nSaved: {json_path}", file=sys.stderr)

    return 0 if output["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
