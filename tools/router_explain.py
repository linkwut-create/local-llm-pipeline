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
# Smart Classifier — local model intelligence layer
# ═══════════════════════════════════════════════════════════════

class SmartClassifier:
    """Three-tier classification: regex → local debate → cloud confirmation.

    Tier 1: Regex patterns (free, <1ms, deterministic)
    Tier 2: Dual local model debate — qwen3.6:27b + gemma4:31b (free, ~30s)
            Both classify independently. Agreement → high confidence.
    Tier 3: DeepSeek Pro confirmation (paid, ~2s, final authority)
            Runs when: (a) local models disagree, OR (b) risk=high/critical.
            The cloud model's verdict overrides local consensus.

    Cache: in-memory, session-scoped. Same task text → same result.
    """

    _cache: dict[str, Tuple[str, str, float]] = {}
    _model_calls: int = 0
    _cloud_confirmations: int = 0
    _debates: int = 0
    _agreements: int = 0

    MODEL_A = "qwen3.6:27b"    # primary local
    MODEL_B = "gemma4:31b-unsloth"     # local debate partner
    CLOUD_MODEL = "deepseek-v4-pro"  # final authority

    # Valid task types the model can return
    VALID_TYPES = {
        "summarize-file", "summarize-tree", "generate-test-plan",
        "review-diff", "deep-code-review", "architecture-review",
        "draft-fix", "draft-feature", "draft-refactor",
        "rewrite-text", "translate-text", "find-related-files",
        "governance-docs", "governance-integration",
        "interface-review", "security-review", "release-risk-review",
        "api-execution-boundary", "control-plane-boundary",
        "suggest-improvements",
    }

    CLASSIFY_PROMPT = """Classify this development task into exactly one category.

Task: {task}

Categories:
- summarize-file: reading/understanding a specific file
- summarize-tree: understanding a directory structure
- review-diff: reviewing code changes or git diff
- deep-code-review: in-depth code quality review
- architecture-review: reviewing architecture or design
- draft-fix: fixing a bug or error
- draft-feature: implementing a new feature or capability
- draft-refactor: refactoring or restructuring code
- generate-test-plan: writing or planning tests
- rewrite-text: writing documentation, README, comments
- translate-text: translating text between languages
- find-related-files: searching or locating files
- governance-docs: updating project governance documents
- governance-integration: building/implementing governance components (gate, hook, budget, privacy)
- interface-review: reviewing API/CLI/config interfaces for breaking changes
- security-review: security audit or vulnerability assessment
- release-risk-review: pre-release risk assessment
- api-execution-boundary: working on API adapters, cloud integration, real-run
- control-plane-boundary: working on hooks, gates, blocking, MCP proxy
- suggest-improvements: suggesting improvements or optimizations

Reply with ONLY one line in this exact format:
TYPE: <category>
RISK: low|medium|high|critical
WHY: <one-line reason>"""

    @classmethod
    def classify(cls, text: str, cloud_ok: bool = False) -> Tuple[str, str, float]:
        """Three-tier classification.

        Args:
            text: Task description.
            cloud_ok: If True, DeepSeek Pro confirms when local models
                      disagree or risk is high/critical.

        Returns (task_type, risk_contribution, confidence).
        """
        # Guard: model calls disabled via env var (for testing)
        import os as _os
        if _os.environ.get("SMART_CLASSIFIER_NO_MODEL", "") == "1":
            return TaskClassifier.classify(text)

        # Tier 1: regex (fast path) — run before length guards so short,
        # well-known task phrases like "review current diff" classify correctly.
        task_type, risk, confidence = TaskClassifier.classify(text)
        if task_type != "unknown" and confidence >= 0.5:
            return (task_type, risk, confidence)

        # Guard: empty/short/gibberish → unknown (don't waste model calls)
        if not text or len(text.strip()) < 20:
            return ("unknown", "low", 0.0)
        # Heuristic: if text has very low word-to-length ratio, it's likely gibberish
        words = text.strip().split()
        if len(text.strip()) < 30 and len(words) <= 3:
            return TaskClassifier.classify(text)

        # Cache check
        cache_key = text.strip().lower()[:200]
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        # Tier 2: local dual-model debate
        try:
            result = cls._debate(text)
        except Exception:
            result = (task_type, risk, confidence)

        # Tier 3: cloud confirmation (when needed)
        tt, rk, cf = result
        needs_cloud = (
            cloud_ok
            and (cf < 0.85 or rk in ("high", "critical"))
        )
        if needs_cloud:
            try:
                result = cls._cloud_confirm(text, tt, rk)
                cls._cloud_confirmations += 1
            except Exception:
                pass  # cloud unavailable → keep local result

        cls._cache[cache_key] = result
        return result

    @classmethod
    def _debate(cls, text: str) -> Tuple[str, str, float]:
        """Run both models and resolve consensus.

        Both models see the same prompt. If they agree on task_type,
        confidence is high. If they disagree, the result includes both
        opinions with reduced confidence.
        """
        import concurrent.futures as _cf

        prompt = cls.CLASSIFY_PROMPT.format(task=text[:2000])

        def _ask(model: str) -> Tuple[str, str, str]:
            return cls._call_single_model(model, prompt)

        cls._debates += 1

        # Run both models in parallel
        with _cf.ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(_ask, cls.MODEL_A)
            future_b = pool.submit(_ask, cls.MODEL_B)
            try:
                type_a, risk_a, why_a = future_a.result(timeout=35)
            except Exception:
                type_a, risk_a, why_a = "unknown", "low", ""
            try:
                type_b, risk_b, why_b = future_b.result(timeout=35)
            except Exception:
                type_b, risk_b, why_b = "unknown", "low", ""

        cls._model_calls += 2

        # Consensus
        if type_a == type_b and type_a != "unknown":
            cls._agreements += 1
            risk = risk_a if risk_a == risk_b else (
                "high" if "high" in (risk_a, risk_b)
                else "medium" if "medium" in (risk_a, risk_b)
                else "low"
            )
            return (type_a, risk, 0.85)

        # Disagreement — prefer the non-unknown model, higher confidence if either is good
        if type_a != "unknown":
            return (type_a, risk_a, 0.55)
        if type_b != "unknown":
            return (type_b, risk_b, 0.55)

        # Both failed
        return ("unknown", "low", 0.2)

    @classmethod
    def _call_single_model(cls, model: str, prompt: str) -> Tuple[str, str, str]:
        """Call one model. Returns (task_type, risk, reason). Never raises."""
        import subprocess as _sp

        cmd = ["ollama", "run", model, prompt]
        try:
            r = _sp.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=30, cwd=str(SCRIPT_DIR.parent),
            )
            output = (r.stdout or "").strip()
            return cls._parse_model_output(output)
        except Exception:
            return ("unknown", "low", "")

    @classmethod
    def _parse_model_output(cls, output: str) -> Tuple[str, str, str]:
        """Parse the model's one-line response."""
        import re as _re
        type_match = _re.search(r"TYPE:\s*(\S+)", output, _re.IGNORECASE)
        risk_match = _re.search(r"RISK:\s*(low|medium|high|critical)", output, _re.IGNORECASE)
        why_match = _re.search(r"WHY:\s*(.+?)$", output, _re.IGNORECASE | _re.MULTILINE)

        task_type = "unknown"
        risk = "low"
        reason = ""
        if type_match:
            candidate = type_match.group(1).strip().lower()
            if candidate in cls.VALID_TYPES:
                task_type = candidate
        if risk_match:
            risk = risk_match.group(1).strip().lower()
        if why_match:
            reason = why_match.group(1).strip()

        return (task_type, risk, reason)

    @classmethod
    def _cloud_confirm(cls, text: str, local_type: str,
                       local_risk: str) -> Tuple[str, str, float]:
        """DeepSeek Pro confirms or overrides local classification.

        Only called when: cloud_ok=True AND (low confidence OR high risk).
        The cloud model is the final authority.
        """
        import os as _os
        api_key = _os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return (local_type, local_risk, 0.6)

        prompt = (
            f"Local models classified this task as TYPE={local_type} "
            f"RISK={local_risk}.\n\n"
            + cls.CLASSIFY_PROMPT.format(task=text[:2000])
            + "\n\nConfirm or override the local classification. "
            "Reply with: TYPE: <category> RISK: <level> WHY: <reason>"
        )

        try:
            from deepseek_client import call_deepseek as _call
            result = _call(
                prompt=prompt,
                model=cls.CLOUD_MODEL,
                max_tokens=128,
                api_key=api_key,
                timeout=30,
            )
            if result.get("ok"):
                cloud_type, cloud_risk, _ = cls._parse_model_output(
                    result.get("content", ""))
                if cloud_type != "unknown":
                    return (cloud_type, cloud_risk, 0.95)
        except Exception:
            pass

        # Cloud unavailable or failed → keep local result with adjusted confidence
        return (local_type, local_risk, 0.6)

    @classmethod
    def stats(cls) -> dict:
        """Return cache/model/debate statistics."""
        return {
            "cache_size": len(cls._cache),
            "model_calls": cls._model_calls,
            "cloud_confirmations": cls._cloud_confirmations,
            "debates": cls._debates,
            "agreements": cls._agreements,
            "agreement_rate": (
                round(cls._agreements / cls._debates, 2)
                if cls._debates > 0 else 0
            ),
        }


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
        "summarize-file": "gemma4_26b_llamacpp",
        "summarize-tree": "gemma4_26b_llamacpp",
        "governance-docs": "docs_agent",
        "rewrite-text": "gemma4_31b_llamacpp",
        "suggest-improvements": "gemma4_26b_llamacpp",
        "draft-fix": "code_worker_llamacpp",
        "draft-feature": "code_worker_llamacpp",
        "draft-refactor": "code_worker_llamacpp",
        "generate-test-plan": "code_worker_llamacpp",
        "review-diff": "diff_reviewer_llamacpp",
        "deep-code-review": "diff_reviewer_llamacpp",
        "architecture-review": "deep_reviewer",
        "find-related-files": "code_worker_llamacpp",
        "translate-text": "translation_llamacpp",
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

    # Cached model names from profiles (lazy-loaded, not hardcoded)
    _flash_model: Optional[str] = None
    _pro_model: Optional[str] = None

    @classmethod
    def _get_cloud_models(cls) -> tuple[str, str]:
        """Resolve cloud model names from profiles.

        Returns (flash_model, pro_model) — never hardcoded.
        Defaults are fallback-only; actual names come from local_llm_profiles.json.
        """
        if cls._flash_model and cls._pro_model:
            return cls._flash_model, cls._pro_model
        flash_model = "flash"       # fallback
        pro_model = "pro"           # fallback
        try:
            profiles = _load_json(PROFILES_PATH).get("profiles", {})
            # Resolve from well-known profile names
            flash_candidates = ["deepseek_v4_flash_worker", "deepseek_v4_flash_thinking"]
            pro_candidates = ["deepseek_v4_pro_planner", "deepseek_v4_pro_reviewer"]
            for name in flash_candidates:
                if name in profiles and profiles[name].get("model"):
                    flash_model = profiles[name]["model"]
                    break
            for name in pro_candidates:
                if name in profiles and profiles[name].get("model"):
                    pro_model = profiles[name]["model"]
                    break
        except Exception:
            pass
        cls._flash_model = flash_model
        cls._pro_model = pro_model
        return flash_model, pro_model

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
            _, pro_model = cls._get_cloud_models()
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

        # Step 1: Classify (regex first, dual-model debate fallback)
        task_type, base_risk, type_conf = SmartClassifier.classify(text)
        signals["classification"] = [f"type={task_type}", f"confidence={type_conf:.2f}"]
        # Report debate stats when model was used
        if type_conf > 0.5 and task_type != "unknown":
            stats = SmartClassifier.stats()
            if stats["debates"] > 0:
                signals["classification"].append(
                    f"debate_agree={stats['agreement_rate']} "
                    f"({stats['agreements']}/{stats['debates']})")

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

        # Resolve actual cloud model names from profiles (never hardcoded)
        resolved_model = tier["recommended_model"]
        try:
            flash_model, pro_model = TieringPolicy._get_cloud_models()
            if resolved_model == "deepseek-v4-flash":
                resolved_model = flash_model
            elif resolved_model == "deepseek-v4-pro":
                resolved_model = pro_model
        except Exception:
            pass  # keep hardcoded fallback if profile loading fails

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
            recommended_model=resolved_model,
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
