#!/usr/bin/env python3
"""
Router Explain Mode — DeepSeek V4 Flash/Pro route explanation tool.
=====================================================================
Outputs structured routing decisions: what runs locally, when to escalate
to Flash, when to escalate to Pro, and why.

Integrates with:
  - tools/deepseek_client.py   (privacy gate, escalation resolver)
  - tools/local_llm_tasks.json (task type registry)
  - tools/local_llm_profiles.json (model profile registry)

Usage:
  py -3 tools/router_explain.py "review current diff" --explain
  py -3 tools/router_explain.py "prepare release v2.3" --json
  py -3 tools/router_explain.py --help

Output fields:
  task_type                    — classified task category
  risk_level                   — low | medium | high | critical
  privacy_status               — safe | blocked | needs_sanitization
  recommended_local_profile    — which local model to try first
  flash_escalation_condition   — when to escalate to Flash
  pro_escalation_condition     — when to escalate to Pro
  cloud_allowed                — whether cloud API is permitted
  reason                       — human-readable explanation

Design constraints:
  - Mock-only: no real API calls.
  - Read-only: does not modify profiles, tasks, or source files.
  - Advisory-only: controller makes final routing decision.
  - Backward-compatible: follows INTERFACES.md compatibility policy.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List, Dict, Tuple

# Project paths
SCRIPT_DIR = Path(__file__).parent
TASKS_PATH = SCRIPT_DIR / "local_llm_tasks.json"
PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"


# ═══════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════

@dataclass
class RouteDecision:
    """Complete routing decision for a task."""
    task_type: str
    risk_level: str                    # low | medium | high | critical
    privacy_status: str                # safe | blocked | needs_sanitization
    recommended_local_profile: Optional[str]
    flash_escalation_condition: Optional[str]
    pro_escalation_condition: Optional[str]
    cloud_allowed: bool
    reason: str
    # Diagnostics
    signals: Dict[str, List[str]] = field(default_factory=dict)
    confidence: float = 1.0
    # DeepSeek V4 Flash/Pro cost-tiering (v0.13.0+)
    recommended_execution_route: str = "local_only"  # flash_direct | claude_code_pro | flash_subagent | local_only | blocked | manual_confirm
    recommended_model: Optional[str] = None           # deepseek-v4-flash | deepseek-v4-pro | None
    cost_tier: str = "free"                           # cheap | moderate | expensive | free
    context_overhead_warning: Optional[str] = None     # subagent overhead warning or None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# Config loaders
# ═══════════════════════════════════════════════════════════════

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _get_cloud_profiles() -> dict:
    """Extract cloud (DeepSeek) profiles from local_llm_profiles.json."""
    profiles = _load_json(PROFILES_PATH).get("profiles", {})
    cloud = {}
    for name, cfg in profiles.items():
        if cfg.get("provider") == "deepseek" or cfg.get("_backend_class") == "cloud_deepseek":
            cloud[name] = cfg
    return cloud


def _get_task_registry() -> dict:
    """Load task type registry."""
    return _load_json(TASKS_PATH).get("tasks", {})


# ═══════════════════════════════════════════════════════════════
# Task Classifier
# ═══════════════════════════════════════════════════════════════

class TaskClassifier:
    """Map a free-text task description to a registered task type."""

    # Pattern → task_type mappings (ordered by priority — first match wins)
    PATTERNS: List[Tuple[str, str, str]] = [
        # (task_type, regex, risk_contribution)
        # IMPORTANT: more-specific patterns first, generic fallback later
        ("release-risk-review", r"\brelease\b|\bdeploy\b|\bpublish\b|\bship\b|\bhotfix\b|\bproduction\b", "high"),
        ("security-review", r"\bsecurity\b|\bvulnerab\b|\bexploit\b|\binjection\b|\bxss\b|\bcsrf\b|\bcve\b|\baudit\b.*\bsecurity\b", "high"),
        # API execution boundary: DeepSeek adapter, real-run, API key handling, provider call
        # Must come BEFORE interface-review and draft-feature to correctly escalate to high-risk
        ("api-execution-boundary", r"\bdeepseek\b.*\b(?:adapter|execution|api.call|real)\b|\b(?:real[\s-]run|guarded[\s-]real[\s-]run|execution[\s-]adapter|api[\s-]execution[\s-]boundary|api[\s-]call[\s-]boundary|cloud[\s-]execution[\s-]adapter|provider[\s-]api[\s-]call|api[\s-]call[\s-]seam)\b|\bapi[\s-]key[\s-](?:handling|reading|lookup|access)\b", "high"),
        # C1+C4: Governance integration & soft gate governance tasks
        # Covers: soft gate protocol, convergence audit, calibration plan,
        #   governance integration, control plane design, privacy/budget/ledger/router implementation
        ("governance-integration", r"\bsoft[\s-]gate\b|\bgovernance[\s-]integration\b|\bcontrol[\s-]plane\b|\bagent[\s-]governance\b|\bclaude[\s-]code.*\b(?:governance|control|default)\b|\bdefault[\s-](?:workflow|governance|soft[\s-]gate)\b|\bconvergence[\s-]audit\b|\bcalibration[\s-](?:plan|round)\b|\brouter[\s-]calibration\b|\bcalibrat.*\brouter\b|\bprivacy[\s-]gate.*(?:implement|calibrat|hardening)\b|\bbudget[\s-]gate.*(?:implement|calibrat|hardening)\b|\bcost[\s-]ledger.*(?:implement|calibrat|hardening)\b|\bshadow[\s-]route.*(?:calibrat|implement)\b", "high"),
        # C2+C5: Control plane boundary — hooks, blocking, MCP, proxy, auto-execution
        ("control-plane-boundary", r"\b(?:warning[\s-]gate|stop[\s-]hook|hard[\s-]block|selective[\s-]blocking|automatic[\s-]blocking|blocking[\s-]gate|pre[\s-]tool[\s-]use[\s-]hook|post[\s-]tool[\s-]use[\s-]hook)\b|\b(?:mcp[\s-]gate|llm[\s-]proxy|worker[\s-]auto[\s-]execution|automatic[\s-]worker|automatic[\s-]cloud[\s-]escalation|automatic[\s-]model[\s-]routing|agent[\s-]runtime|controlled[\s-]agent)\b|\bhook[\s-]integration\b|\bexecution[\s-]enforcement\b", "high"),
        # interface change: bidirectional — "change X interface" OR "interface X change"
        ("interface-review", r"\binterface\b.*\b(chang|break|review)|\b(chang|break).*\binterface\b|\bapi\b.*\b(chang|break)|\b(chang|break).*\bapi\b|\bschema\b.*\b(chang|migrat)|\b(chang|migrat).*\bschema\b|\bbackward\b.*\bcompat\b|\bdeprecat\b|\brouter\b.*\bconfig\b|\bprovider\b.*\b(chang|config|schema)|\b(config|schema).*\brefactor\b|\bddl\b|\balter\b.*\btable\b|\bcolumn\b.*\b(add|drop|modif|alter)|\b(add|drop|modif).*\bcolumn\b|\bmigrat.*\b(database|db|column|table|schema)|\b(database|schema).*\bmigrat", "high"),
        # API execution boundary — DeepSeek integration, adapters, real-run, smoke tests
        ("api-execution-boundary", r"\bdeepseek\b(?!.*\bsmoke\b.*\btest\b)|\bapi\b.*\b(adapter|execution|call|real|integration)|\b(?:adapter|execution|real[\s-]run|dry[\s-]run)\b|\bskeleton\b.*\b(?:adapter|execution)|\b(?:adapter|execution).*\bskeleton\b", "high"),
        # governance-docs BEFORE governance-integration (docs about governance = low risk)
        ("governance-docs", r"\bproblems\.md\b|\blongtodo\.md\b|\bagents\.md\b|\binterfaces\.md\b|\bclaude\.md\b|\bgrillme\.md\b|\bchangelog\.md\b|\brelease_notes\.md\b|\bgovernance\b|\baudit\b", "low"),
        # Governance integration — implementing/hardening/building governance components
        ("governance-integration", r"\b(?:enable|disable|implement|add|build|integrate|wire|connect|harden|upgrade)\b.*\b(?:soft[\s-]gate|privacy[\s-]gate|budget[\s-]guard|cost[\s-]ledger|shadow[\s-]rout)\b|\b(?:soft[\s-]gate|privacy[\s-]gate|budget[\s-]guard|cost[\s-]ledger|shadow[\s-]rout)\b.*\b(?:implementation|integration|harden|build|setup|enable|deploy)\b|\bdogfood\b|\bcheckpoint\b.*\b(preparation|report|status)|\bcalibrat\b.*\brouter\b|\brouter\b.*\bcalibrat\b", "high"),
        # review-diff BEFORE architecture-review (more specific)
        ("review-diff", r"\breview\b.*\bdiff\b|\bdiff\b.*\breview\b|\bcommit\b.*\breview\b|\bpr\b.*\breview\b|\bprecommit\b|\bpre-commit\b", "medium"),
        ("deep-code-review", r"\bcode review\b|\bdeep\b.*\breview\b|\breview\b.*\bdeep\b|\breview\b.*\bchange\b|\breview\b.*\bcode\b|\b审查\b.*\b代码\b", "medium"),
        ("architecture-review", r"\barchitect\b|\brefactor\b|\brestructur\b|\bredesign\b|\bdesign pattern\b", "medium"),
        ("draft-refactor", r"\brefactor\b|\brestructur\b|\bclean\b.*\bup\b|\bsimplify\b", "medium-high"),
        ("draft-fix", r"\bfix\b|\bbug\b|\bpatch\b|\bhotfix\b|\berror\b|\bcrash\b|\bexception\b|\bstack.*trace\b|\bnull\b.*\bpointer\b", "medium"),
        ("generate-test-plan", r"\btests?\b.*\bfail|\bfail.*\btests?\b|\bflaky\b|\bassertion\b|\btests?\b.*\berror\b|\btests?\b.*\bplan\b|\btests?\b.*\banaly\b|\btests?\b.*\bsuite\b|\btests?\b.*\bmock\b|\bmock\b.*\btests?\b|\btests?\b.*\brun\b|\bregression\b|\bwrite\b.*\btests?\b", "medium"),
        ("draft-feature", r"\bfeature\b|\bimplement\b|\badd\b.*\b(new|column|service|api|gateway|module|endpoint|handler|support|tool|cli|script|report|exporter)\b|\bbuild\b|\bacross\b.*\bservice\b", "medium"),
        ("suggest-improvements", r"\bimprov\b|\boptimiz\b|\bperformance\b|\bbottleneck\b|\bsuggest\b", "low"),
        ("summarize-file", r"\bsummar(y|ize)\b|\bexplain\b.*\bfile\b|\bwhat\b.*\bdoes\b|\bhow\b.*\bwork\b", "low"),
        ("rewrite-text", r"\bdocument\b|\breadme\b|\bcomment\b|\bdocstring\b|\bchangelog\b", "low"),
        ("translate-text", r"\btranslat\b|\bconvert\b.*\blanguage\b", "low"),
        ("find-related-files", r"\bfind\b|\bsearch\b|\blist\b|\blocate\b|\bgrep\b|\bwhere\b.*\bis\b|\btodo\b", "low"),
    ]

    @classmethod
    def classify(cls, text: str) -> Tuple[str, str, float]:
        """Return (task_type, risk_contribution, confidence)."""
        text_lower = text.lower()
        for task_type, pattern, risk in cls.PATTERNS:
            if re.search(pattern, text_lower):
                # Count matches for confidence
                matches = len(re.findall(pattern, text_lower))
                confidence = min(1.0, matches / 3.0 + 0.33)
                return (task_type, risk, confidence)
        return ("unknown", "low", 0.2)


# ═══════════════════════════════════════════════════════════════
# Risk Assessor
# ═══════════════════════════════════════════════════════════════

class RiskAssessor:
    """Refine risk level based on additional signals."""

    CRITICAL_SIGNALS = {
        "data loss", "corruption", "production outage",
        "security breach", "auth bypass",
    }

    HIGH_SIGNALS = {
        "release", "deploy", "production", "hotfix",
        "security", "vulnerability", "exploit", "injection",
        "interface", "breaking change", "backward compat",
        "schema change", "migration", "migrate",
        "auth", "authentication", "authorization", "credential",
        "encryption", "decrypt", "hash", "signature",
        "race condition", "deadlock", "concurrency",
        "memory leak", "segfault", "core dump",
    }

    MEDIUM_SIGNALS = {
        "refactor", "restructure", "multi-file", "cross-cutting",
        "test fail", "flaky", "regression",
        "optimize", "performance", "bottleneck",
        "async", "parallel", "concurrent",
        "compile", "build", "ci", "pipeline",
    }

    @classmethod
    def assess(cls, text: str, base_risk: str) -> Tuple[str, List[str]]:
        """Return (risk_level, signals_found)."""
        text_lower = text.lower()
        signals = []

        critical = [s for s in cls.CRITICAL_SIGNALS if s in text_lower]
        high = [s for s in cls.HIGH_SIGNALS if s in text_lower and s not in critical]
        medium = [s for s in cls.MEDIUM_SIGNALS if s in text_lower]

        if critical:
            return "critical", critical
        if base_risk == "high" or len(high) >= 2:
            return "high", high + medium
        if base_risk in ("medium", "medium-high") or len(medium) >= 3 or len(high) >= 1:
            return "medium", medium + high
        return "low", medium + high


# ═══════════════════════════════════════════════════════════════
# Privacy Gate (delegates to deepseek_client._check_privacy)
# ═══════════════════════════════════════════════════════════════

class PrivacyGate:
    """Check if content is safe to send to cloud API.

    Delegates to deepseek_client._check_privacy for core checks,
    with additional full-repo and private-document detection.
    """

    FULL_REPO_PATTERNS = [
        r"(?i)export\s+(repo|repository|codebase)",
        r"(?i)(clone|copy|mirror)\s+(repo|repository)",
        r"(?i)(zip|tar|archive)\s+(repo|repository|entire)",
        r"(?i)send\s+(entire|whole|complete)\s+(code|repo)",
        r"(?i)full\s+repo",
        r"(?i)entire\s+codebase",
        r"(?i)whole\s+repository",
    ]

    PRIVATE_DOC_PATTERNS = [
        r"(?i)private\s+(paper|document|article|manuscript|letter|diary)",
        r"(?i)confidential\s+(paper|document|article)",
        r"(?i)unpublished\s+(paper|work|manuscript)",
    ]

    @classmethod
    def check(cls, text: str) -> Tuple[str, List[str], bool]:
        """
        Returns (privacy_status, matched_patterns, cloud_allowed).

        privacy_status: safe | blocked | needs_sanitization
        """
        # Delegate to deepseek_client's core privacy check
        try:
            from deepseek_client import _check_privacy
            safe, reason = _check_privacy(text)
        except ImportError:
            # Fallback: inline privacy check
            safe, reason = cls._inline_privacy_check(text)

        if not safe:
            return ("blocked", [reason], False)

        # Additional full-repo check
        repo_matches = []
        for pat in cls.FULL_REPO_PATTERNS:
            if re.search(pat, text):
                repo_matches.append(pat)

        if repo_matches:
            return ("blocked", repo_matches + ["full_repo_export_detected"], False)

        # Private doc check → needs_sanitization
        doc_matches = []
        for pat in cls.PRIVATE_DOC_PATTERNS:
            if re.search(pat, text):
                doc_matches.append(pat)

        if doc_matches:
            return ("needs_sanitization", doc_matches, False)

        return ("safe", [], True)

    @staticmethod
    def _inline_privacy_check(text: str) -> Tuple[bool, str]:
        """Fallback privacy check when deepseek_client not importable."""
        patterns = [
            (r"sk-[a-zA-Z0-9]{20,}", "API key pattern"),
            (r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----", "private key"),
            (r"-----BEGIN PGP PRIVATE KEY BLOCK-----", "PGP private key"),
        ]
        for pat, label in patterns:
            if re.search(pat, text):
                return False, f"content matches forbidden pattern: {label}"
        return True, ""


# ═══════════════════════════════════════════════════════════════
# Profile Mapper
# ═══════════════════════════════════════════════════════════════

class ProfileMapper:
    """Map task_type → recommended local profile.

    Uses the existing task registry and profile definitions.
    """

    # Override for tasks where local model is unsuitable
    # (risk too high → go straight to cloud)
    LOCAL_BLOCKED_TASKS = {
        "release-risk-review",
        "security-review",
        "interface-review",
    }

    # Default profiles when task registry has no match
    FALLBACK_MAP = {
        "summarize-file": "fast_summary",
        "summarize-tree": "fast_summary",
        "governance-docs": "docs_agent",
        "rewrite-text": "fast_summary",
        "suggest-improvements": "qwen3.6_27b_mtp",
        "draft-fix": "code_worker",
        "draft-feature": "code_worker",
        "draft-refactor": "code_worker",
        "generate-test-plan": "code_worker",
        "review-diff": "commit_reviewer",
        "deep-code-review": "deep_reviewer",
        "architecture-review": "deep_reviewer",
        "find-related-files": "code_worker",
        "translate-text": "translation",
        # Cloud-only tasks — no local profile
        "release-risk-review": None,
        "security-review": None,
        "interface-review": None,
    }

    @classmethod
    def recommend(cls, task_type: str, risk_level: str) -> Optional[str]:
        """Return recommended local profile name, or None."""
        if task_type in cls.LOCAL_BLOCKED_TASKS:
            return None
        if risk_level in ("high", "critical"):
            # Local model can pre-check but final decision → cloud
            profile = cls._lookup_profile(task_type)
            if profile:
                return f"{profile} (pre-check only)"
            return None

        return cls._lookup_profile(task_type)

    @classmethod
    def _lookup_profile(cls, task_type: str) -> Optional[str]:
        """Look up the default profile for a task type."""
        # Check task registry first
        tasks = _get_task_registry()
        if task_type in tasks:
            return tasks[task_type].get("default_profile")

        # Check fallback map
        return cls.FALLBACK_MAP.get(task_type)


# ═══════════════════════════════════════════════════════════════
# Escalation Policy
# ═══════════════════════════════════════════════════════════════

class EscalationPolicy:
    """
    Define escalation conditions from local → Flash → Pro.

    Default: local-first
    → Flash: local failure >= 2, medium multi-file, unresolved test
    → Pro: release gate, interface change, security, Flash-local conflict
    → Blocked: privacy gate fails → local-only
    """

    @classmethod
    def get_flash_condition(cls, task_type: str, risk_level: str,
                            privacy_status: str) -> Optional[str]:
        """When to escalate to Flash. None = never escalate."""
        if privacy_status == "blocked":
            return None

        conditions = ["local failure >= 2 consecutive"]
        conditions.append("local output empty or invalid JSON")

        if task_type in ("draft-fix", "draft-feature", "draft-refactor",
                         "generate-test-plan"):
            conditions.append(f"task_type={task_type} → Flash suitable")

        if risk_level == "medium":
            conditions.append("risk=medium → Flash as default worker")

        if task_type == "generate-test-plan":
            conditions.append("test failure analysis unresolved after local")

        return " ; ".join(conditions)

    @classmethod
    def get_pro_condition(cls, task_type: str, risk_level: str,
                          privacy_status: str) -> Optional[str]:
        """When to escalate to Pro. None = never escalate."""
        if privacy_status == "blocked":
            return None

        conditions = []

        if task_type in ("release-risk-review", "security-review"):
            conditions.append(f"task_type={task_type} → requires Pro review")

        if task_type in ("interface-review", "architecture-review"):
            conditions.append("interface/schema/provider/router/config change → Pro gate")

        if risk_level in ("high", "critical"):
            conditions.append(f"risk={risk_level} → Pro required for final decision")

        conditions.append("Flash output conflicts with local → Pro arbitration")

        return " ; ".join(conditions)


# ═══════════════════════════════════════════════════════════════
# DeepSeek V4 Flash/Pro Cost-Tiering Policy
# ═══════════════════════════════════════════════════════════════

class TieringPolicy:
    """
    Map task_type + risk_level + privacy_status → execution route,
    recommended model, cost tier, and context overhead warning.

    Rules (priority order):
      1. privacy=blocked → blocked
      2. release/security/interface/architecture/API/governance → claude_code_pro
      2b. draft-fix/feature/refactor → claude_code_pro (code mod ≠ subagent)
      3. risk=high/critical → claude_code_pro
      4. review-diff/generate-test-plan → flash_subagent (moderate, +overhead warning)
      5. summarize/docs/translate/find-files → flash_direct (cheap)
      6. unknown → manual_confirm
      7. fallback → local_only (free)

    Design constraints:
      - Pure function: no I/O, no API calls, no file reads.
      - Advisory-only: controller makes final routing decision.
      - Mock-only: never calls DeepSeek API.
    """

    # Task types that should use Flash direct (no subagent overhead)
    FLASH_DIRECT_TASKS = {
        "summarize-file",
        "summarize-tree",
        "rewrite-text",
        "translate-text",
        "find-related-files",
        "governance-docs",
        "suggest-improvements",
    }

    # Task types that should use Claude Code Pro (complex/high-stakes)
    PRO_TASKS = {
        "release-risk-review",
        "security-review",
        "interface-review",
        "architecture-review",
        "deep-code-review",
        "api-execution-boundary",
        "governance-integration",
        "control-plane-boundary",
    }

    # Code-modification tasks: real code changes — Claude Code Pro only.
    # Flash subagent has ~90k token overhead; not a safe default for
    # fix/feature/refactor work. Controller may downgrade with explicit approval.
    CODE_MODIFICATION_TASKS = {
        "draft-fix",
        "draft-feature",
        "draft-refactor",
    }

    # Task types suitable for Flash subagent (needs agent, not critical,
    # no code modification — review/analysis only)
    FLASH_SUBAGENT_TASKS = {
        "generate-test-plan",
        "review-diff",
    }

    @classmethod
    def resolve(cls, task_type: str, risk_level: str,
                privacy_status: str) -> dict:
        """
        Return tiering fields as a dict:
          recommended_execution_route, recommended_model,
          cost_tier, context_overhead_warning
        """
        # Rule 1: Privacy blocked → local-only or blocked
        if privacy_status == "blocked":
            return {
                "recommended_execution_route": "blocked",
                "recommended_model": None,
                "cost_tier": "free",
                "context_overhead_warning": None,
            }

        # Rule 2: Pro tasks → claude_code_pro
        if task_type in cls.PRO_TASKS:
            return {
                "recommended_execution_route": "claude_code_pro",
                "recommended_model": "deepseek-v4-pro",
                "cost_tier": "expensive",
                "context_overhead_warning": (
                    "Pro includes reasoning tokens; ~4x Flash cost per token. "
                    "Use only for high-stakes decisions."
                ),
            }

        # Rule 2b: Code-modification tasks → claude_code_pro
        # Flash subagent ~90k token overhead is NOT a safe default for
        # fix/feature/refactor work. Controller may downgrade with explicit approval.
        if task_type in cls.CODE_MODIFICATION_TASKS:
            return {
                "recommended_execution_route": "claude_code_pro",
                "recommended_model": "deepseek-v4-pro",
                "cost_tier": "expensive",
                "context_overhead_warning": (
                    "Code modification should stay in Claude Code Pro "
                    "unless explicitly approved. Flash subagent has ~90k "
                    "token overhead and is not a safe default for "
                    "fix/feature/refactor work."
                ),
            }

        # Rule 3: High/critical risk → claude_code_pro (even if not in PRO_TASKS)
        if risk_level in ("high", "critical"):
            return {
                "recommended_execution_route": "claude_code_pro",
                "recommended_model": "deepseek-v4-pro",
                "cost_tier": "expensive",
                "context_overhead_warning": (
                    f"risk={risk_level} → Pro required for final decision"
                ),
            }

        # Rule 4: Flash subagent tasks → flash_subagent
        if task_type in cls.FLASH_SUBAGENT_TASKS:
            return {
                "recommended_execution_route": "flash_subagent",
                "recommended_model": "deepseek-v4-flash",
                "cost_tier": "moderate",
                "context_overhead_warning": (
                    "Subagent overhead ~90k tokens per call. "
                    "Prefer flash_direct for simple/single-step tasks."
                ),
            }

        # Rule 5: Flash direct tasks → flash_direct
        if task_type in cls.FLASH_DIRECT_TASKS:
            return {
                "recommended_execution_route": "flash_direct",
                "recommended_model": "deepseek-v4-flash",
                "cost_tier": "cheap",
                "context_overhead_warning": None,
            }

        # Rule 6: Unknown → manual_confirm
        if task_type == "unknown":
            return {
                "recommended_execution_route": "manual_confirm",
                "recommended_model": None,
                "cost_tier": "free",
                "context_overhead_warning": (
                    "Task unclassified — human should clarify intent "
                    "before routing to any paid model."
                ),
            }

        # Rule 7: Fallback → local_only (safe default)
        return {
            "recommended_execution_route": "local_only",
            "recommended_model": None,
            "cost_tier": "free",
            "context_overhead_warning": None,
        }


# ═══════════════════════════════════════════════════════════════
# Router Engine
# ═══════════════════════════════════════════════════════════════

class RouterEngine:
    """Unified routing decision engine."""

    def analyze(self, task_description: str, context: dict = None) -> RouteDecision:
        """Analyze a task and return a complete routing decision."""
        text = task_description
        if context:
            extra = ""
            for key in ("system", "messages"):
                val = context.get(key, "")
                if isinstance(val, str):
                    extra += " " + val
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            extra += " " + item
                        elif isinstance(item, dict):
                            extra += " " + str(item.get("content", ""))
            text = task_description + " " + extra

        signals = {}

        # Step 1: Classify
        task_type, base_risk, type_conf = TaskClassifier.classify(text)
        signals["classification"] = [f"type={task_type}", f"confidence={type_conf:.2f}"]

        # Step 2: Assess risk
        risk_level, risk_signals = RiskAssessor.assess(text, base_risk)
        signals["risk"] = risk_signals[:8] if risk_signals else ["no specific risk signals"]

        # Step 3: Privacy gate
        privacy_status, privacy_matches, cloud_allowed = PrivacyGate.check(text)
        signals["privacy"] = privacy_matches if privacy_matches else ["clean"]

        # Step 4: Local profile
        local_profile = ProfileMapper.recommend(task_type, risk_level)
        signals["profile"] = [local_profile] if local_profile else ["no local profile — go to cloud"]

        # Step 5: Escalation conditions
        flash_cond = EscalationPolicy.get_flash_condition(task_type, risk_level, privacy_status)
        pro_cond = EscalationPolicy.get_pro_condition(task_type, risk_level, privacy_status)

        # Step 6: DeepSeek V4 Flash/Pro cost-tiering
        tier = TieringPolicy.resolve(task_type, risk_level, privacy_status)
        signals["tiering"] = [
            f"route={tier['recommended_execution_route']}",
            f"model={tier['recommended_model'] or 'none'}",
            f"cost={tier['cost_tier']}",
        ]
        if tier.get("context_overhead_warning"):
            signals["tiering"].append(
                f"warning={tier['context_overhead_warning'][:80]}"
            )

        # Step 7: Build reason
        reason_parts = [f"task classified as '{task_type}'"]

        if risk_level in ("high", "critical"):
            reason_parts.append(f"risk={risk_level} — requires careful handling")
        elif risk_level == "medium":
            reason_parts.append(f"risk={risk_level} — Flash-suitable for most cases")
        else:
            reason_parts.append(f"risk={risk_level} — local-first is appropriate")

        if privacy_status == "blocked":
            reason_parts.append("CLOUD BLOCKED: sensitive data detected")
        elif privacy_status == "needs_sanitization":
            reason_parts.append("CLOUD RESTRICTED: needs sanitization before sending")
        else:
            reason_parts.append("privacy gate passed")

        if local_profile:
            reason_parts.append(f"local model available: {local_profile}")
        else:
            reason_parts.append("no suitable local model — direct to cloud")

        reason_parts.append(
            f"execution route: {tier['recommended_execution_route']} "
            f"(cost: {tier['cost_tier']})"
        )

        return RouteDecision(
            task_type=task_type,
            risk_level=risk_level,
            privacy_status=privacy_status,
            recommended_local_profile=local_profile,
            flash_escalation_condition=flash_cond,
            pro_escalation_condition=pro_cond,
            cloud_allowed=cloud_allowed,
            reason=" ; ".join(reason_parts),
            signals=signals,
            confidence=type_conf,
            recommended_execution_route=tier["recommended_execution_route"],
            recommended_model=tier["recommended_model"],
            cost_tier=tier["cost_tier"],
            context_overhead_warning=tier.get("context_overhead_warning"),
        )


# ═══════════════════════════════════════════════════════════════
# Formatters
# ═══════════════════════════════════════════════════════════════

def format_explain(decision: RouteDecision) -> str:
    """Format a RouteDecision as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("  ROUTER EXPLAIN — Decision Analysis")
    lines.append("=" * 60)
    lines.append(f"  Task type    : {decision.task_type}")
    lines.append(f"  Risk level   : {decision.risk_level}")
    lines.append(f"  Privacy      : {decision.privacy_status}")
    lines.append(f"  Cloud allowed: {'YES' if decision.cloud_allowed else 'NO'}")
    lines.append("")

    if decision.recommended_local_profile:
        lines.append(f"  Recommended local profile: {decision.recommended_local_profile}")
    else:
        lines.append(f"  Recommended local profile: (none — go straight to cloud)")

    lines.append("")
    lines.append("  Escalation path:")
    lines.append(f"    Local first -> {decision.recommended_local_profile or '(skip)'}")

    if decision.flash_escalation_condition:
        lines.append(f"    -> Flash when: {decision.flash_escalation_condition}")
    else:
        lines.append(f"    -> Flash: NOT ALLOWED (privacy blocked)")

    if decision.pro_escalation_condition:
        lines.append(f"    -> Pro when:   {decision.pro_escalation_condition}")
    else:
        lines.append(f"    -> Pro: NOT ALLOWED (privacy blocked)")

    lines.append("")
    lines.append(f"  DeepSeek V4 Tiering:")
    lines.append(f"    Execution route: {decision.recommended_execution_route}")
    lines.append(f"    Recommended model: {decision.recommended_model or '(none)'}")
    lines.append(f"    Cost tier: {decision.cost_tier}")
    if decision.context_overhead_warning:
        lines.append(f"    WARNING: {decision.context_overhead_warning}")
    lines.append("")
    lines.append(f"  Reason: {decision.reason}")
    lines.append("")

    if decision.signals:
        lines.append("  Signals detected:")
        for category, sigs in decision.signals.items():
            if sigs:
                lines.append(f"    [{category}]: {', '.join(sigs[:5])}")
                if len(sigs) > 5:
                    lines.append(f"               ... and {len(sigs) - 5} more")

    lines.append("=" * 60)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Router Explain Mode — explain task routing decisions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py -3 tools/router_explain.py "review current diff" --explain
  py -3 tools/router_explain.py "prepare release v2.3" --json
  py -3 tools/router_explain.py "fix null pointer in login" --json
  py -3 tools/router_explain.py --demo
        """,
    )
    parser.add_argument(
        "task", nargs="*",
        help="Task description (e.g., 'review current diff for bugs')"
    )
    parser.add_argument(
        "--explain", action="store_true",
        help="Output human-readable explanation"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run demo with sample tasks"
    )
    args = parser.parse_args()

    engine = RouterEngine()

    if args.demo:
        _run_demo(engine)
        return

    task = " ".join(args.task) if args.task else ""
    if not task:
        parser.print_help()
        sys.exit(1)

    decision = engine.analyze(task)

    if args.json:
        print(decision.to_json())
    else:
        # Default: explain mode
        print(format_explain(decision))


def _run_demo(engine: RouterEngine):
    """Run demo with sample tasks."""
    samples = [
        "review current diff for bugs",
        "prepare release v2.3 for production deployment",
        "fix null pointer exception in login handler",
        "audit codebase for SQL injection vulnerabilities",
        "refactor the payment processing pipeline",
        "explain what this function does",
        "analyze test failure in CI pipeline",
        "change the API interface for user creation endpoint",
        "migrate database schema: add new column to users table",
        "search for all TODO comments in the codebase",
    ]

    print("Router Explain Engine — Sample Analysis\n")
    for i, task in enumerate(samples, 1):
        decision = engine.analyze(task)
        print(f"[{i}] {task}")
        print(f"    type={decision.task_type}  risk={decision.risk_level}  "
              f"privacy={decision.privacy_status}  cloud={decision.cloud_allowed}")
        print(f"    local={decision.recommended_local_profile or '(none)'}")
        flash = decision.flash_escalation_condition
        pro = decision.pro_escalation_condition
        print(f"    flash: {flash[:100] if flash else '(blocked)'}{'...' if flash and len(flash) > 100 else ''}")
        print(f"    pro:   {pro[:100] if pro else '(blocked)'}{'...' if pro and len(pro) > 100 else ''}")
        print(f"    tier:  route={decision.recommended_execution_route}  "
              f"model={decision.recommended_model or '(none)'}  "
              f"cost={decision.cost_tier}")
        if decision.context_overhead_warning:
            print(f"    WARNING: {decision.context_overhead_warning[:120]}")
        print()


if __name__ == "__main__":
    main()
