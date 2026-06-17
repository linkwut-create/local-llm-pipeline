#!/usr/bin/env python3
"""Local Route Committee — Qwen 27B + Gemma 31B structured routing debate.

Architecture (per user design):
  1. Pro outputs plan.json (initial planning artifact)
  2. Evidence pack built: git status + file tree + diff + tests + privacy + phase
  3. Qwen + Gemma independently read: plan.json + evidence pack → route judgement
  4. Deterministic merge rules resolve the two judgements into route.json
  5. route.json is ENFORCED (not advisory) — hook limits Claude Code actions

Design constraints:
  - Evidence pack < 2000 words (local models are slow on long context)
  - One round debate only
  - Deterministic merge (no third model)
  - route.json is machine-readable and enforceable
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


# ═══════════════════════════════════════════════════════════════
# Evidence pack builder — compact context for local models
# ═══════════════════════════════════════════════════════════════

def build_evidence_pack(repo_root: str | Path = ".") -> dict:
    """Gather compact context. Target: < 2000 words total.

    Returns dict with keys:
      git_status, file_tree, current_diff, test_status,
      privacy_scan, project_phase, recent_commits
    """
    root = Path(repo_root).resolve()
    pack = {
        "git_status": "",
        "file_tree": "",
        "current_diff": "",
        "test_status": "unknown",
        "privacy_scan": "safe",
        "project_phase": "development",
        "recent_commits": "",
    }

    # Git status (compact)
    try:
        r = subprocess.run(
            ["git", "status", "--short"], cwd=str(root),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=5,
        )
        lines = r.stdout.strip().split("\n")[:30]
        pack["git_status"] = "\n".join(lines) if lines else "clean"
    except Exception:
        pack["git_status"] = "unknown"

    # File tree (one level only, exclude .git, .local_llm_out, __pycache__)
    try:
        entries = sorted(root.iterdir())
        tree_lines = []
        for e in entries[:40]:
            if e.name.startswith(".") and e.name != ".claude":
                continue
            if e.name in ("__pycache__", "node_modules"):
                continue
            suffix = "/" if e.is_dir() else ""
            tree_lines.append(f"  {e.name}{suffix}")
        pack["file_tree"] = "\n".join(tree_lines)
    except Exception:
        pack["file_tree"] = "unavailable"

    # Current diff (first 30 lines, paths only for large diffs)
    try:
        r = subprocess.run(
            ["git", "diff", "--stat"], cwd=str(root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        stat = r.stdout.strip()
        if stat:
            lines = stat.split("\n")
            if len("\n".join(lines)) > 500:
                pack["current_diff"] = "\n".join(lines[:5]) + "\n... (truncated)"
            else:
                pack["current_diff"] = "\n".join(lines[:15])
        else:
            pack["current_diff"] = "no unstaged changes"
    except Exception:
        pack["current_diff"] = "unavailable"

    # Test status (last run summary)
    try:
        cache_file = root / ".pytest_cache" / "v" / "cache" / "lastrun"
        if cache_file.exists():
            pack["test_status"] = "tests were run recently"
        else:
            pack["test_status"] = "no recent test run found"
    except Exception:
        pack["test_status"] = "unknown"

    # Privacy scan (basic — check .env, secrets, API keys in diff)
    try:
        r = subprocess.run(
            ["git", "diff"], cwd=str(root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        diff_text = r.stdout.lower()
        if any(kw in diff_text for kw in ("api_key", "secret", "password", "token", ".env")):
            pack["privacy_scan"] = "needs_review"
        else:
            pack["privacy_scan"] = "safe"
    except Exception:
        pack["privacy_scan"] = "unknown"

    # Project phase (from VERSION file)
    try:
        version_file = root / "VERSION"
        if version_file.exists():
            pack["project_phase"] = f"v{version_file.read_text().strip()}"
    except Exception:
        pass

    # Recent commits (last 5, one-line)
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-5"], cwd=str(root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        pack["recent_commits"] = r.stdout.strip()
    except Exception:
        pack["recent_commits"] = "unavailable"

    return pack


def format_evidence_pack(pack: dict) -> str:
    """Format evidence pack as compact text for the model prompt."""
    return f"""## Context
Git status:
{pack['git_status']}

Recent commits:
{pack['recent_commits']}

File tree:
{pack['file_tree']}

Current diff (stat):
{pack['current_diff']}

Test status: {pack['test_status']}
Privacy scan: {pack['privacy_scan']}
Project phase: {pack['project_phase']}"""


# ═══════════════════════════════════════════════════════════════
# Route enforcement — route.json schema
# ═══════════════════════════════════════════════════════════════

# Actions ALLOWED per route (whitelist, not advisory)
ROUTE_PERMISSIONS = {
    "local_only": {
        "allowed_tools": ["Read", "Grep", "Glob", "Bash"],
        "forbidden_tools": ["Edit", "Write", "mcp__github__*"],
        "max_files_to_read": 10,
        "cloud_allowed": False,
        "description": "Read-only local exploration",
    },
    "flash_direct": {
        "allowed_tools": ["Read", "Grep", "Glob", "Bash", "Write"],
        "forbidden_tools": ["mcp__github__*"],
        "max_files_to_read": 20,
        "cloud_allowed": True,
        "description": "Fast cloud for simple tasks (summarize, translate, docs)",
    },
    "flash_subagent": {
        "allowed_tools": ["Read", "Grep", "Glob", "Bash", "Write", "Edit"],
        "forbidden_tools": ["mcp__github__*"],
        "max_files_to_edit": 5,
        "cloud_allowed": True,
        "description": "Cloud agent for analysis tasks (review, test plan)",
    },
    "pro_decision": {
        "allowed_tools": [],  # unrestricted
        "forbidden_tools": [],
        "max_files_to_edit": None,
        "cloud_allowed": True,
        "description": "Full Pro capability (architecture, security, code mod)",
    },
    "blocked": {
        "allowed_tools": [],
        "forbidden_tools": ["*"],
        "max_files_to_read": 0,
        "cloud_allowed": False,
        "description": "Task blocked — cannot proceed",
    },
    "ask_user": {
        "allowed_tools": [],
        "forbidden_tools": ["Edit", "Write"],
        "max_files_to_read": 3,
        "cloud_allowed": False,
        "description": "Need human clarification before proceeding",
    },
}

# ═══════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════

@dataclass
class RouteJudgement:
    """A single model's routing judgement for a task phase."""
    delegability: str              # high | medium | low | blocked
    recommended_route: str         # local_only | flash_direct | flash_subagent | pro_decision | blocked | ask_user
    local_preprocessing_required: bool
    pro_should_execute: bool
    pro_should_adjudicate: bool
    risk_level: str                # low | medium | high | critical
    privacy_status: str            # safe | needs_review | blocked
    reason: str
    required_artifacts: list[str]
    model: str = ""                # which model produced this judgement
    confidence: float = 0.0
    parse_failed: bool = False     # True if the model response could not be parsed

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RouteDecision:
    """Merged route decision from the committee."""
    delegability: str
    recommended_route: str
    local_preprocessing_required: bool
    pro_should_execute: bool
    pro_should_adjudicate: bool
    risk_level: str
    privacy_status: str
    reason: str
    required_artifacts: list[str]
    # Debate metadata
    qwen_judgement: dict
    gemma_judgement: dict
    agreement: bool
    escalated: bool
    escalated_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════

ROUTE_JUDGEMENT_PROMPT = """Route this task. Output ONLY valid JSON, no markdown.

{plan_json}

{evidence}

JSON format (exact):
{{"delegability":"high|medium|low|blocked","recommended_route":"local_only|flash_direct|flash_subagent|pro_decision|blocked|ask_user","local_preprocessing_required":true|false,"pro_should_execute":true|false,"pro_should_adjudicate":true|false,"risk_level":"low|medium|high|critical","privacy_status":"safe|needs_review|blocked","reason":"short","required_artifacts":[]}}

Rules:
- privacy=blocked → blocked
- code modification → pro_should_execute=true
- understanding/reading → local_preprocessing_required=true
- high delegability → prefer flash over pro
- disagreements: blocked wins, high risk → pro, both agree flash → flash"""


# ═══════════════════════════════════════════════════════════════
# Deterministic merge rules
# ═══════════════════════════════════════════════════════════════

def _single_model_decision(j: RouteJudgement) -> RouteDecision:
    """When only one model responds, use its judgement directly."""
    return RouteDecision(
        delegability=j.delegability,
        recommended_route=j.recommended_route,
        local_preprocessing_required=j.local_preprocessing_required,
        pro_should_execute=j.pro_should_execute,
        pro_should_adjudicate=j.pro_should_adjudicate,
        risk_level=j.risk_level,
        privacy_status=j.privacy_status,
        reason=f"Single model ({j.model}): {j.reason}",
        required_artifacts=j.required_artifacts,
        qwen_judgement=j.to_dict() if "qwen" in j.model else {},
        gemma_judgement=j.to_dict() if "gemma" in j.model else {},
        agreement=True,
        escalated=j.recommended_route in ("pro_decision", "blocked"),
        escalated_reason="single model decision (partner unavailable)",
    )


def merge_judgements(qwen: RouteJudgement,
                     gemma: RouteJudgement) -> RouteDecision:
    """Deterministic merge of two route judgements. No third model needed.

    Rules (priority order):
      1. Either model says blocked → blocked
      2. Either model says high/critical risk → pro_decision
      3. Both agree on local/flash → execute at that level
      4. Disagreement → escalate to pro_decision or ask_user
    """
    # Rule 1: blocked
    if "blocked" in (qwen.recommended_route, gemma.recommended_route):
        blocked_reasons = [
            qwen.reason if qwen.recommended_route == "blocked" else "",
            gemma.reason if gemma.recommended_route == "blocked" else "",
        ]
        reason = "Blocked: " + "; ".join(filter(None, blocked_reasons)).strip()
        return RouteDecision(
            delegability="blocked",
            recommended_route="blocked",
            local_preprocessing_required=False,
            pro_should_execute=False,
            pro_should_adjudicate=True,
            risk_level="critical",
            privacy_status=(
                "blocked" if "blocked" in (qwen.privacy_status, gemma.privacy_status)
                else "needs_review"
            ),
            reason=reason,
            required_artifacts=[],
            qwen_judgement=qwen.to_dict(),
            gemma_judgement=gemma.to_dict(),
            agreement=(qwen.recommended_route == gemma.recommended_route),
            escalated=True,
            escalated_reason="one model voted blocked",
        )

    # Rule 2: high/critical risk → pro
    high_risks = {"high", "critical"}
    if qwen.risk_level in high_risks or gemma.risk_level in high_risks:
        return RouteDecision(
            delegability="low",
            recommended_route="pro_decision",
            local_preprocessing_required=(
                qwen.local_preprocessing_required or gemma.local_preprocessing_required
            ),
            pro_should_execute=True,
            pro_should_adjudicate=True,
            risk_level=(
                "critical" if "critical" in (qwen.risk_level, gemma.risk_level)
                else "high"
            ),
            privacy_status=(
                "blocked" if "blocked" in (qwen.privacy_status, gemma.privacy_status)
                else "needs_review" if "needs_review" in (qwen.privacy_status, gemma.privacy_status)
                else "safe"
            ),
            reason=f"Escalated for high risk: qwen={qwen.risk_level}, gemma={gemma.risk_level}",
            required_artifacts=list(set(
                qwen.required_artifacts + gemma.required_artifacts)),
            qwen_judgement=qwen.to_dict(),
            gemma_judgement=gemma.to_dict(),
            agreement=(qwen.risk_level == gemma.risk_level),
            escalated=True,
            escalated_reason="high/critical risk from at least one model",
        )

    # Rule 3: both agree on local/flash → execute
    local_flash_routes = {"local_only", "flash_direct", "flash_subagent"}
    if (qwen.recommended_route in local_flash_routes
            and gemma.recommended_route in local_flash_routes):
        # Prefer flash if either model recommends it
        route = "flash_subagent"
        if qwen.recommended_route == "flash_subagent" or gemma.recommended_route == "flash_subagent":
            route = "flash_subagent"
        elif qwen.recommended_route == "flash_direct" or gemma.recommended_route == "flash_direct":
            route = "flash_direct"
        else:
            route = "local_only"

        return RouteDecision(
            delegability="high",
            recommended_route=route,
            local_preprocessing_required=(
                qwen.local_preprocessing_required or gemma.local_preprocessing_required
            ),
            pro_should_execute=False,
            pro_should_adjudicate=False,
            risk_level=(
                "medium" if "medium" in (qwen.risk_level, gemma.risk_level)
                else "low"
            ),
            privacy_status=(
                "blocked" if "blocked" in (qwen.privacy_status, gemma.privacy_status)
                else "needs_review" if "needs_review" in (qwen.privacy_status, gemma.privacy_status)
                else "safe"
            ),
            reason=f"Consensus: {route} (qwen={qwen.recommended_route}, gemma={gemma.recommended_route})",
            required_artifacts=list(set(
                qwen.required_artifacts + gemma.required_artifacts)),
            qwen_judgement=qwen.to_dict(),
            gemma_judgement=gemma.to_dict(),
            agreement=True,
            escalated=False,
            escalated_reason="",
        )

    # Rule 4: Both agree on non-executable route → use it
    if qwen.recommended_route == gemma.recommended_route:
        route = qwen.recommended_route
        return RouteDecision(
            delegability="low",
            recommended_route=route,
            local_preprocessing_required=(
                qwen.local_preprocessing_required or gemma.local_preprocessing_required
            ),
            pro_should_execute=qwen.pro_should_execute or gemma.pro_should_execute,
            pro_should_adjudicate=qwen.pro_should_adjudicate or gemma.pro_should_adjudicate,
            risk_level=(
                "high" if "high" in (qwen.risk_level, gemma.risk_level)
                else "medium" if "medium" in (qwen.risk_level, gemma.risk_level)
                else "low"
            ),
            privacy_status=(
                "blocked" if "blocked" in (qwen.privacy_status, gemma.privacy_status)
                else "needs_review" if "needs_review" in (qwen.privacy_status, gemma.privacy_status)
                else "safe"
            ),
            reason=f"Consensus: {route} ({qwen.reason[:80]})",
            required_artifacts=list(set(qwen.required_artifacts + gemma.required_artifacts)),
            qwen_judgement=qwen.to_dict(),
            gemma_judgement=gemma.to_dict(),
            agreement=True,
            escalated=(route in ("pro_decision", "ask_user", "blocked")),
            escalated_reason=f"both models agreed: {route}",
        )

    # Rule 5: true disagreement → escalate
    return RouteDecision(
        delegability="low",
        recommended_route="ask_user",
        local_preprocessing_required=True,
        pro_should_execute=False,
        pro_should_adjudicate=True,
        risk_level="medium",
        privacy_status=(
            "blocked" if "blocked" in (qwen.privacy_status, gemma.privacy_status)
            else "needs_review" if "needs_review" in (qwen.privacy_status, gemma.privacy_status)
            else "safe"
        ),
        reason=(
            f"Disagreement: qwen={qwen.recommended_route}, "
            f"gemma={gemma.recommended_route}. Human decision needed."
        ),
        required_artifacts=[],
        qwen_judgement=qwen.to_dict(),
        gemma_judgement=gemma.to_dict(),
        agreement=False,
        escalated=True,
        escalated_reason="committee disagreement",
    )


# ═══════════════════════════════════════════════════════════════
# Committee
# ═══════════════════════════════════════════════════════════════

def _call_model(model: str, prompt: str, timeout: int = 90) -> str:
    """Call Ollama model via API (not CLI) to avoid terminal artifacts."""
    import urllib.request as _ur
    import json as _json

    # Allow env override for very slow local GPUs
    env_timeout = os.environ.get("LOCAL_LLM_COMMITTEE_TIMEOUT")
    if env_timeout:
        try:
            timeout = max(int(env_timeout), 10)
        except ValueError:
            pass

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 256, "temperature": 0.0},
    }
    keep_alive = os.environ.get("LOCAL_LLM_KEEP_ALIVE")
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    body = _json.dumps(payload).encode("utf-8")

    base = os.environ.get("OLLAMA_HOST", "http://193.168.2.2:11434")
    url = base.rstrip("/") + "/api/generate"

    try:
        req = _ur.Request(url, data=body, headers={"Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        return data.get("response", "").strip()
    except Exception:
        # Fallback to CLI
        try:
            r = subprocess.run(
                ["ollama", "run", model, prompt],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            return (r.stdout or "").strip()
        except Exception:
            return ""


def _call_model_with_retry(model: str, prompt: str, timeout: int = 120, max_retries: int = 1) -> str:
    """Call a model and retry once if the response is not parseable."""
    raw = _call_model(model, prompt, timeout=timeout)
    parsed = _parse_judgement(raw, model)
    if not parsed.parse_failed or max_retries <= 0:
        return raw
    raw = _call_model(model, prompt, timeout=timeout)
    return raw


def _parse_judgement(raw: str, model: str) -> RouteJudgement:
    """Extract JSON from model output and parse into RouteJudgement."""
    # Strip ANSI escape sequences and terminal control chars
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', clean)
    # Find the first complete JSON object
    depth = 0; start = -1
    for i, ch in enumerate(clean):
        if ch == '{':
            if depth == 0: start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                json_match = re.match(r'', '')  # dummy
                json_str = clean[start:i+1]
                break
    else:
        json_str = None
    if not json_str:
        return RouteJudgement(
            delegability="low",
            recommended_route="ask_user",
            local_preprocessing_required=False,
            pro_should_execute=False,
            pro_should_adjudicate=True,
            risk_level="medium",
            privacy_status="safe",
            reason=f"{model} returned unparseable output",
            required_artifacts=[],
            model=model,
            confidence=0.0,
            parse_failed=True,
        )

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return RouteJudgement(
            delegability="low",
            recommended_route="ask_user",
            local_preprocessing_required=False,
            pro_should_execute=False,
            pro_should_adjudicate=True,
            risk_level="medium",
            privacy_status="safe",
            reason=f"{model} returned invalid JSON",
            required_artifacts=[],
            model=model,
            confidence=0.0,
            parse_failed=True,
        )

    return RouteJudgement(
        delegability=data.get("delegability", "low"),
        recommended_route=data.get("recommended_route", "ask_user"),
        local_preprocessing_required=data.get("local_preprocessing_required", False),
        pro_should_execute=data.get("pro_should_execute", False),
        pro_should_adjudicate=data.get("pro_should_adjudicate", False),
        risk_level=data.get("risk_level", "medium"),
        privacy_status=data.get("privacy_status", "safe"),
        reason=data.get("reason", f"{model} judgement"),
        required_artifacts=data.get("required_artifacts", []),
        model=model,
        confidence=0.75 if data.get("delegability") else 0.5,
    )


def convene(task_description: str,
            plan_json: str = "{}",
            evidence_pack: dict | None = None,
            repo_root: str | Path = ".") -> RouteDecision:
    """Convene the local route committee.

    Qwen 27B and Gemma 31B independently judge the routing, then
    deterministic rules merge their judgements into one decision.

    Args:
        task_description: The user's task.
        plan_json: Pro's plan.json (if available).
        evidence_pack: Pre-built evidence pack (or None to auto-build).
        repo_root: Repo root for auto-building evidence pack.

    Returns:
        RouteDecision with merged judgement and enforced permissions.
    """
    # Build evidence pack if not provided
    if evidence_pack is None:
        evidence_pack = build_evidence_pack(repo_root)
    evidence_text = format_evidence_pack(evidence_pack)

    prompt = ROUTE_JUDGEMENT_PROMPT.format(
        plan_json=plan_json or f'{{"task": "{task_description[:500]}"}}',
        evidence=evidence_text,
    )

    # Allow env override for slow GPUs; default 120s per model call
    model_timeout = int(os.environ.get("LOCAL_LLM_COMMITTEE_TIMEOUT", 120))
    result_timeout = model_timeout + 30  # headroom for threading overhead

    import concurrent.futures as _cf

    with _cf.ThreadPoolExecutor(max_workers=2) as pool:
        future_qwen = pool.submit(_call_model_with_retry, "qwen3.6:27b", prompt, model_timeout)
        future_gemma = pool.submit(_call_model_with_retry, "gemma4:31b-unsloth", prompt, model_timeout)
        try:
            raw_qwen = future_qwen.result(timeout=result_timeout)
        except Exception:
            raw_qwen = ""
        try:
            raw_gemma = future_gemma.result(timeout=result_timeout)
        except Exception:
            raw_gemma = ""

    qwen = _parse_judgement(raw_qwen, "qwen3.6:27b")
    gemma = _parse_judgement(raw_gemma, "gemma4:31b-unsloth")

    # If both models could not be parsed even after retry, fall back to pro_decision
    # rather than deadlocking the session with ask_user.
    if qwen.parse_failed and gemma.parse_failed:
        return RouteDecision(
            delegability="low",
            recommended_route="pro_decision",
            local_preprocessing_required=False,
            pro_should_execute=True,
            pro_should_adjudicate=True,
            risk_level="medium",
            privacy_status="safe",
            reason="Local committee could not parse either model response; falling back to pro_decision.",
            required_artifacts=[],
            qwen_judgement=qwen.to_dict(),
            gemma_judgement=gemma.to_dict(),
            agreement=False,
            escalated=True,
            escalated_reason="both models unparseable after retry",
        )

    # If exactly one model failed, use the other alone
    if qwen.parse_failed and not gemma.parse_failed:
        return _single_model_decision(gemma)
    if gemma.parse_failed and not qwen.parse_failed:
        return _single_model_decision(qwen)

    return merge_judgements(qwen, gemma)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Local Route Committee — Qwen+Gemma structured routing debate")
    parser.add_argument("task", nargs="+", help="Task description")
    parser.add_argument("--plan", default=None, help="Path to plan.json (from Pro)")
    parser.add_argument("--git-status", default="unknown", help="Git status summary")
    parser.add_argument("--privacy", default="safe",
                        help="Privacy gate result: safe|needs_review|blocked")
    parser.add_argument("--phase", default="development",
                        help="Project phase")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--output", default=None,
                        help="Write JSON decision to this file (implies --json)")
    args = parser.parse_args()

    task = " ".join(args.task)
    plan_json = "{}"
    if args.plan:
        try:
            plan_json = Path(args.plan).read_text(encoding="utf-8")
        except Exception:
            pass

    # Auto-build evidence pack
    evidence = build_evidence_pack()

    decision = convene(
        task_description=task,
        plan_json=plan_json,
        evidence_pack=evidence,
    )

    # Attach enforcement permissions to output
    permissions = ROUTE_PERMISSIONS.get(
        decision.recommended_route,
        ROUTE_PERMISSIONS["ask_user"],
    )

    output = decision.to_dict()
    output["_enforcement"] = {
        "allowed": list(permissions.get("allowed_tools", [])) or ["all"],
        "denied": list(permissions.get("forbidden_tools", [])),
        "cloud_ok": permissions.get("cloud_allowed", False),
    }

    if args.output:
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.json or args.output:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Task: {task[:80]}")
        print(f"Route: {decision.recommended_route}")
        print(f"Risk: {decision.risk_level}")
        print(f"Agreement: {decision.agreement}")
        print(f"Escalated: {decision.escalated} ({decision.escalated_reason})")
        print(f"Reason: {decision.reason}")
        print(f"Artifacts: {decision.required_artifacts}")
        print(f"\nENFORCEMENT:")
        allowed = "all" if not permissions.get("allowed_tools") else ", ".join(sorted(permissions["allowed_tools"]))
        denied = "none" if not permissions.get("forbidden_tools") else ", ".join(sorted(permissions["forbidden_tools"]))
        print(f"  Allowed: {allowed}")
        print(f"  Denied: {denied}")
        print(f"  Cloud: {permissions.get('cloud_allowed', False)}")
        if not decision.agreement:
            print(f"\nQwen: {decision.qwen_judgement.get('recommended_route')}")
            print(f"Gemma: {decision.gemma_judgement.get('recommended_route')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
