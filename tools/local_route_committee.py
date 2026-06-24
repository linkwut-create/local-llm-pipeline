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
# Committee model configuration (env var overridable)
# ═══════════════════════════════════════════════════════════════

_LOCAL_ROUTE_QWEN_MODEL = os.environ.get("LOCAL_ROUTE_QWEN_MODEL", "qwen3.6-deep")
_LOCAL_ROUTE_GEMMA_MODEL = os.environ.get("LOCAL_ROUTE_GEMMA_MODEL", "qwen3-coder-30b")


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

# Route permissions and policy — single source of truth in pipeline_route_policy
from pipeline_route_policy import (
    ROUTE_PERMISSIONS,
    VALID_ROUTES,
    get_permissions,
    validate_route_json,
)

# Legacy alias for internal use
def _route_permissions_for(route: str) -> dict:
    return get_permissions(route)
VALID_DELEGABILITY = {"high", "medium", "low", "blocked"}
VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}
VALID_PRIVACY_STATUSES = {"safe", "needs_review", "blocked"}


def _unique_ordered(values: list[str]) -> list[str]:
    """Return unique string values in first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not isinstance(value, str) or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _merged_required_artifacts(*judgements: RouteJudgement) -> list[str]:
    """Merge required artifacts deterministically across model judgements."""
    values: list[str] = []
    for judgement in judgements:
        values.extend(judgement.required_artifacts)
    return _unique_ordered(values)


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
    # Pro audit (Pro does NOT vote, only audits on disagreement)
    pro_audit_requested: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# Prompt
# ═══════════════════════════════════════════════════════════════

ROUTE_JUDGEMENT_SCHEMA = '{"delegability":"high|medium|low|blocked","recommended_route":"local_only|flash_direct|flash_subagent|pro_decision|blocked|ask_user","local_preprocessing_required":true|false,"pro_should_execute":true|false,"pro_should_adjudicate":true|false,"risk_level":"low|medium|high|critical","privacy_status":"safe|needs_review|blocked","reason":"short","required_artifacts":[]}'

QWEN_ROLE_INSTRUCTIONS = """Role: Qwen engineering delegate.
Focus on delegability, execution route, and required artifacts.
- Prefer local_only for read-only discovery, summaries, repo maps, and test planning.
- Prefer flash_direct only for simple bounded writing or rewriting.
- Prefer flash_subagent when a bounded worker can produce a candidate artifact.
- Use pro_decision for architecture, interface, security, release, or broad code changes.
- Set required_artifacts to the evidence a controller must inspect before continuing."""

GEMMA_ROLE_INSTRUCTIONS = """Role: Gemma risk and privacy reviewer.
Focus on conservatism, privacy, route safety, and escalation boundaries.
- Set privacy_status=blocked for secrets, credentials, private keys, or .env exposure.
- Set privacy_status=needs_review when sensitive intent or unclear private data appears.
- Set risk_level=high for hooks, routing, MCP, gate, security, release, or interface changes.
- Prefer ask_user when the task is ambiguous or missing authorization.
- Prefer pro_decision when local or flash execution would cross a safety boundary."""

ROUTE_JUDGEMENT_PROMPT = """Route this task. Output ONLY valid JSON, no markdown.

{role_instructions}

{plan_json}

{evidence}

JSON format (exact):
{schema}

Rules:
- privacy=blocked → blocked
- code modification → pro_should_execute=true
- understanding/reading → local_preprocessing_required=true
- high delegability → prefer flash over pro
- disagreements: blocked wins, high risk → pro, both agree flash → flash"""


# ═══════════════════════════════════════════════════════════════
# Deterministic merge rules
# ═══════════════════════════════════════════════════════════════

def build_route_prompt(role_instructions: str, plan_json: str, evidence: str) -> str:
    """Build one model-specific prompt while preserving the shared JSON schema."""
    return ROUTE_JUDGEMENT_PROMPT.format(
        role_instructions=role_instructions.strip(),
        plan_json=plan_json,
        evidence=evidence,
        schema=ROUTE_JUDGEMENT_SCHEMA,
    )


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
            required_artifacts=_merged_required_artifacts(qwen, gemma),
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
            required_artifacts=_merged_required_artifacts(qwen, gemma),
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
            required_artifacts=_merged_required_artifacts(qwen, gemma),
            qwen_judgement=qwen.to_dict(),
            gemma_judgement=gemma.to_dict(),
            agreement=True,
            escalated=(route in ("pro_decision", "ask_user", "blocked")),
            escalated_reason=f"both models agreed: {route}",
        )

    # Rule 5: true disagreement → escalate with Pro audit
    return RouteDecision(
        delegability="low",
        recommended_route="ask_user",
        local_preprocessing_required=True,
        pro_should_execute=False,
        pro_should_adjudicate=True,
        pro_audit_requested=True,
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

def _resolve_committee_endpoint() -> str:
    """Resolve the LiteLLM/llama.cpp base URL for committee model calls.

    Uses the same resolver as the worker so the committee always targets
    the same backend, whether invoked from MCP or CLI.
    """
    try:
        from local_llm_worker import _resolve_endpoint
        return _resolve_endpoint("openai-compatible")
    except Exception:
        return os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:4000/v1")


def _check_model_availability(model: str, base_url: str | None = None,
                               timeout: int = 5) -> tuple[bool, str]:
    """Check if a model endpoint is reachable via /v1/models or health check.

    Returns (available: bool, detail: str).
    """
    import urllib.request as _ur
    import json as _json

    base = base_url or _resolve_committee_endpoint()
    # Try /v1/models first (OpenAI-compatible)
    models_url = base.rstrip("/") + "/models"
    try:
        req = _ur.Request(models_url, headers={"Content-Type": "application/json"})
        api_key = os.environ.get("LOCAL_LLM_API_KEY")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with _ur.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        model_ids = []
        if isinstance(data, dict):
            for item in data.get("data") or []:
                if isinstance(item, dict) and item.get("id"):
                    model_ids.append(item["id"])
        if model in model_ids:
            return True, f"model '{model}' found in {len(model_ids)} available models"
        if not model_ids:
            return True, "endpoint reachable (model list empty or unexpected format)"
        return True, f"endpoint reachable ({len(model_ids)} models, '{model}' not in list)"
    except Exception as e:
        # Fallback: try /health
        try:
            health_url = base.rstrip("/v1").rstrip("/") + "/health"
            req = _ur.Request(health_url)
            with _ur.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return True, "health check passed"
        except Exception:
            pass
        return False, f"endpoint not reachable: {e}"


def _call_model(model: str, prompt: str, timeout: int = 1000) -> tuple[str, dict]:
    """Call local model via OpenAI-compatible API (LiteLLM/llama.cpp).

    Returns ``(text: str, metrics: dict)``.
    """
    import urllib.request as _ur
    import json as _json
    import time as _time

    t0 = _time.monotonic()
    metrics = {
        "model": model, "latency_sec": 0.0, "input_chars": len(prompt),
        "output_chars": 0, "ok": False, "error": None,
    }

    env_timeout = os.environ.get("LOCAL_LLM_COMMITTEE_TIMEOUT")
    if env_timeout:
        try:
            timeout = max(int(env_timeout), 10)
        except ValueError:
            pass

    base = os.environ.get("LOCAL_LLM_BASE_URL") or _resolve_committee_endpoint()
    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "stream": False, "temperature": 0.0, "max_tokens": 2048,
    }
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("LOCAL_LLM_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = _json.dumps(payload).encode("utf-8")
    text = ""

    try:
        req = _ur.Request(url, data=body, headers=headers)
        with _ur.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            # Prefer content; fall back to reasoning_content (Qwen3.6 reasoning models)
            text = (message.get("content") or message.get("reasoning_content") or "").strip()
        metrics["ok"] = True
        metrics["output_chars"] = len(text)
    except Exception as e:
        metrics["error"] = str(e)[:200]
    finally:
        metrics["latency_sec"] = round(_time.monotonic() - t0, 3)

    return text, metrics


def _call_model_with_retry(model: str, prompt: str, timeout: int = 1000,
                            max_retries: int = 1) -> tuple[str, list[dict]]:
    """Call a model, retry once if unparseable. Returns (text, metrics_list)."""
    all_metrics: list[dict] = []
    raw, m1 = _call_model(model, prompt, timeout=timeout)
    all_metrics.append(m1)
    parsed = _parse_judgement(raw, model)
    if not parsed.parse_failed or max_retries <= 0:
        return raw, all_metrics
    raw, m2 = _call_model(model, prompt, timeout=timeout)
    all_metrics.append(m2)
    return raw, all_metrics


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


def _save_committee_artifacts(
    task_id: str | None,
    evidence_pack: dict,
    qwen_prompt: str, gemma_prompt: str,
    raw_qwen: str, raw_gemma: str,
    cross_raw_qwen: str, cross_raw_gemma: str,
    decision: RouteDecision,
    metrics: list[dict],
) -> Path | None:
    """Save committee inputs/outputs to the task artifact directory."""
    if not task_id:
        return None
    import time as _time
    tasks_dir = Path(".local_llm_out/tasks") / task_id
    committee_dir = tasks_dir / "committee"
    committee_dir.mkdir(parents=True, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")

    (committee_dir / "evidence_pack.json").write_text(
        json.dumps(evidence_pack, ensure_ascii=False, indent=2), encoding="utf-8")
    (committee_dir / "qwen_initial_prompt.txt").write_text(qwen_prompt, encoding="utf-8")
    (committee_dir / "gemma_initial_prompt.txt").write_text(gemma_prompt, encoding="utf-8")
    (committee_dir / "qwen_initial.json").write_text(raw_qwen, encoding="utf-8")
    (committee_dir / "gemma_initial.json").write_text(raw_gemma, encoding="utf-8")
    if cross_raw_qwen:
        (committee_dir / "qwen_cross_review.json").write_text(cross_raw_qwen, encoding="utf-8")
    if cross_raw_gemma:
        (committee_dir / "gemma_cross_review.json").write_text(cross_raw_gemma, encoding="utf-8")
    (committee_dir / "decision.json").write_text(
        json.dumps(decision.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (committee_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return committee_dir


def convene(task_description: str,
            plan_json: str = "{}",
            evidence_pack: dict | None = None,
            repo_root: str | Path = ".",
            task_id: str | None = None) -> RouteDecision:
    """Convene the local route committee.

    Qwen 27B + Gemma 31B independently judge routing, then one round of
    controlled cross-review resolves disagreements. Deterministic merge
    rules produce the final route decision.

    Returns:
        RouteDecision with merged judgement, metrics, and saved artifacts.
    """
    import concurrent.futures as _cf
    import time as _time

    all_metrics: list[dict] = []

    # Build evidence pack
    if evidence_pack is None:
        evidence_pack = build_evidence_pack(repo_root)
    evidence_text = format_evidence_pack(evidence_pack)

    plan_text = plan_json or json.dumps(
        {"task": task_description[:500]}, ensure_ascii=False)

    qwen_prompt = build_route_prompt(QWEN_ROLE_INSTRUCTIONS, plan_text, evidence_text)
    gemma_prompt = build_route_prompt(GEMMA_ROLE_INSTRUCTIONS, plan_text, evidence_text)

    # Phase 4: Check model availability
    qwen_avail, qwen_avail_detail = _check_model_availability(_LOCAL_ROUTE_QWEN_MODEL)
    gemma_avail, gemma_avail_detail = _check_model_availability(_LOCAL_ROUTE_GEMMA_MODEL)
    all_metrics.append({
        "step": "availability", "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "qwen_available": qwen_avail, "qwen_detail": qwen_avail_detail,
        "gemma_available": gemma_avail, "gemma_detail": gemma_avail_detail,
    })

    model_timeout = int(os.environ.get("LOCAL_LLM_COMMITTEE_TIMEOUT", 1000))
    result_timeout = model_timeout + 60

    # --- Round 1: Independent judgements (parallel) ---
    raw_qwen, raw_gemma = "", ""
    qwen_metrics_list, gemma_metrics_list = [], []
    cross_raw_qwen, cross_raw_gemma = "", ""

    with _cf.ThreadPoolExecutor(max_workers=2) as pool:
        fq = pool.submit(_call_model_with_retry, _LOCAL_ROUTE_QWEN_MODEL, qwen_prompt, model_timeout)
        fg = pool.submit(_call_model_with_retry, _LOCAL_ROUTE_GEMMA_MODEL, gemma_prompt, model_timeout)
        try:
            raw_qwen, qwen_metrics_list = fq.result(timeout=result_timeout)
        except Exception:
            raw_qwen, qwen_metrics_list = "", [{"error": "timeout or exception"}]
        try:
            raw_gemma, gemma_metrics_list = fg.result(timeout=result_timeout)
        except Exception:
            raw_gemma, gemma_metrics_list = "", [{"error": "timeout or exception"}]

    for m in qwen_metrics_list:
        m["role"] = "qwen"; m["round"] = "initial"
        all_metrics.append(m)
    for m in gemma_metrics_list:
        m["role"] = "gemma"; m["round"] = "initial"
        all_metrics.append(m)

    qwen = _parse_judgement(raw_qwen, _LOCAL_ROUTE_QWEN_MODEL)
    gemma = _parse_judgement(raw_gemma, _LOCAL_ROUTE_GEMMA_MODEL)

    # --- Round 2: Controlled cross-review (one round only) ---
    if not qwen.parse_failed and not gemma.parse_failed:
        if qwen.recommended_route != gemma.recommended_route:
            # Each model reads the other's conclusion, outputs only disagreement
            cross_qwen_prompt = (
                f"{QWEN_ROLE_INSTRUCTIONS}\n\n"
                f"Your initial judgement: {json.dumps(qwen.to_dict())}\n\n"
                f"Gemma's judgement: {json.dumps(gemma.to_dict())}\n\n"
                f"If you still disagree, explain specifically why. "
                f"If you agree with Gemma after review, state 'CONVERGED: <route>'."
                f"\nOutput ONLY valid JSON per schema:\n{ROUTE_JUDGEMENT_SCHEMA}"
            )
            cross_gemma_prompt = (
                f"{GEMMA_ROLE_INSTRUCTIONS}\n\n"
                f"Your initial judgement: {json.dumps(gemma.to_dict())}\n\n"
                f"Qwen's judgement: {json.dumps(qwen.to_dict())}\n\n"
                f"If you still disagree, explain specifically why. "
                f"If you agree with Qwen after review, state 'CONVERGED: <route>'."
                f"\nOutput ONLY valid JSON per schema:\n{ROUTE_JUDGEMENT_SCHEMA}"
            )

            with _cf.ThreadPoolExecutor(max_workers=2) as pool:
                fcq = pool.submit(_call_model, _LOCAL_ROUTE_QWEN_MODEL, cross_qwen_prompt, model_timeout)
                fcg = pool.submit(_call_model, _LOCAL_ROUTE_GEMMA_MODEL, cross_gemma_prompt, model_timeout)
                try:
                    cross_raw_qwen, cm_qwen = fcq.result(timeout=result_timeout)
                except Exception:
                    cross_raw_qwen, cm_qwen = "", {"error": "cross-review timeout"}
                try:
                    cross_raw_gemma, cm_gemma = fcg.result(timeout=result_timeout)
                except Exception:
                    cross_raw_gemma, cm_gemma = "", {"error": "cross-review timeout"}

            cm_qwen["role"] = "qwen"; cm_qwen["round"] = "cross"
            cm_gemma["role"] = "gemma"; cm_gemma["round"] = "cross"
            all_metrics.append(cm_qwen)
            all_metrics.append(cm_gemma)

            # Parse cross-review outputs
            cross_qwen_parsed = _parse_judgement(cross_raw_qwen, _LOCAL_ROUTE_QWEN_MODEL)
            cross_gemma_parsed = _parse_judgement(cross_raw_gemma, _LOCAL_ROUTE_GEMMA_MODEL)
            if not cross_qwen_parsed.parse_failed:
                qwen = cross_qwen_parsed
            if not cross_gemma_parsed.parse_failed:
                gemma = cross_gemma_parsed

    # --- Merge ---

    if qwen.parse_failed and gemma.parse_failed:
        decision = RouteDecision(
            delegability="low",
            recommended_route="pro_decision",
            local_preprocessing_required=False,
            pro_should_execute=True, pro_should_adjudicate=True,
            risk_level="medium", privacy_status="safe",
            reason="Local committee could not parse either model response; falling back to pro_decision.",
            required_artifacts=[],
            qwen_judgement=qwen.to_dict(), gemma_judgement=gemma.to_dict(),
            agreement=False, escalated=True,
            escalated_reason="both models unparseable after retry",
        )
        decision.metrics = all_metrics  # type: ignore[attr-defined]
        _save_committee_artifacts(task_id, evidence_pack,
            qwen_prompt, gemma_prompt, raw_qwen, raw_gemma,
            cross_raw_qwen, cross_raw_gemma, decision, all_metrics)
        return decision

    if qwen.parse_failed and not gemma.parse_failed:
        decision = _single_model_decision(gemma)
        decision.metrics = all_metrics  # type: ignore[attr-defined]
        _save_committee_artifacts(task_id, evidence_pack,
            qwen_prompt, gemma_prompt, raw_qwen, raw_gemma,
            cross_raw_qwen, cross_raw_gemma, decision, all_metrics)
        return decision
    if gemma.parse_failed and not qwen.parse_failed:
        decision = _single_model_decision(qwen)
        decision.metrics = all_metrics  # type: ignore[attr-defined]
        _save_committee_artifacts(task_id, evidence_pack,
            qwen_prompt, gemma_prompt, raw_qwen, raw_gemma,
            cross_raw_qwen, cross_raw_gemma, decision, all_metrics)
        return decision

    decision = merge_judgements(qwen, gemma)
    decision.metrics = all_metrics  # type: ignore[attr-defined]
    _save_committee_artifacts(task_id, evidence_pack,
        qwen_prompt, gemma_prompt, raw_qwen, raw_gemma,
        cross_raw_qwen, cross_raw_gemma, decision, all_metrics)
    return decision


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def _is_list_of_strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def build_route_output(decision: RouteDecision) -> dict:
    """Build the route.json payload from a RouteDecision.

    Wildcard entries (``mcp__local-llm__*`` etc.) are expanded to concrete
    tool names so Claude Code's built-in enforcement (exact match) works.
    """
    permissions = _route_permissions_for(decision.recommended_route)
    output = decision.to_dict()
    allowed = set(permissions.get("allowed", set()))
    denied = set(permissions.get("denied", set()))

    # Expand wildcard tool families
    from pipeline_route_policy import _expand_tool_name
    expanded = set()
    for name in allowed:
        expanded |= _expand_tool_name(name)

    # Known MCP tool names for wildcard expansion
    _MCP_KNOWN = {
        "mcp__local-llm__*": [
            "mcp__local-llm__local_review_diff", "mcp__local-llm__local_route_explain",
            "mcp__local-llm__local_check", "mcp__local-llm__local_summarize_file",
            "mcp__local-llm__local_summarize_tree", "mcp__local-llm__local_debate_review_diff",
            "mcp__local-llm__local_generate_test_plan", "mcp__local-llm__local_draft_code",
            "mcp__local-llm__local_contextual_analyze", "mcp__local-llm__local_repo_map",
            "mcp__local-llm__local_classify_test_failure", "mcp__local-llm__local_workflow_plan",
        ],
        "mcp__git__*": [
            "mcp__git__git_add", "mcp__git__git_commit", "mcp__git__git_diff",
            "mcp__git__git_status", "mcp__git__git_log", "mcp__git__git_set_working_dir",
            "mcp__git__git_branch", "mcp__git__git_checkout", "mcp__git__git_stash",
        ],
    }
    for wildcard, concrete in _MCP_KNOWN.items():
        if wildcard in allowed:
            expanded |= set(concrete)

    enforcement_allowed = sorted(t for t in expanded if not t.endswith("*"))
    output["_enforcement"] = {
        "allowed": enforcement_allowed if enforcement_allowed else ["all"],
        "denied": sorted(denied),
        "cloud_ok": permissions.get("cloud_ok", False),
        "pro_audit_requested": decision.pro_audit_requested,
    }
    output["allowed_tools"] = enforcement_allowed if enforcement_allowed != ["all"] else []
    return output


def validate_route_output(output: dict) -> list[str]:
    """Validate a full route.json payload (delegates to policy module)."""
    from pipeline_route_policy import validate_route_json
    return validate_route_json(output)


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

    output = build_route_output(decision)
    validation_errors = validate_route_output(output)
    if validation_errors:
        error_payload = {
            "ok": False,
            "error": "invalid route output",
            "validation_errors": validation_errors,
        }
        if args.json or args.output:
            print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        else:
            print(
                "ERROR: invalid route output: " + "; ".join(validation_errors),
                file=sys.stderr,
            )
        return 2

    if args.output:
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.json or args.output:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        permissions = _route_permissions_for(decision.recommended_route)
        print(f"Task: {task[:80]}")
        print(f"Route: {decision.recommended_route}")
        print(f"Risk: {decision.risk_level}")
        print(f"Agreement: {decision.agreement}")
        print(f"Escalated: {decision.escalated} ({decision.escalated_reason})")
        print(f"Reason: {decision.reason}")
        print(f"Artifacts: {decision.required_artifacts}")
        print(f"\nENFORCEMENT:")
        allowed = "all" if not permissions.get("allowed") else ", ".join(sorted(permissions["allowed"]))
        denied = "none" if not permissions.get("denied") else ", ".join(sorted(permissions["denied"]))
        print(f"  Allowed: {allowed}")
        print(f"  Denied: {denied}")
        print(f"  Cloud: {permissions.get('cloud_ok', False)}")
        if not decision.agreement:
            print(f"\nQwen: {decision.qwen_judgement.get('recommended_route')}")
            print(f"Gemma: {decision.gemma_judgement.get('recommended_route')}")

    return 0


if __name__ == "__main__":
