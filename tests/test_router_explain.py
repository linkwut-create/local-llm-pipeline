"""
Mock-based tests for tools/router_explain.py.

All tests are mock — no real API calls, no file system writes.
Tests cover:
  - Task type classification (all 14 types)
  - Risk level assessment
  - Privacy gate (safe / blocked / needs_sanitization)
  - Local profile mapping
  - Escalation conditions (Flash / Pro)
  - End-to-end RouteDecision output
  - Edge cases (empty input, unknown tasks)
"""

import json
import sys
import os
from pathlib import Path

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from router_explain import (
    TaskClassifier,
    RiskAssessor,
    PrivacyGate,
    ProfileMapper,
    EscalationPolicy,
    TieringPolicy,
    RouterEngine,
    RouteDecision,
    format_explain,
)


# ═══════════════════════════════════════════════════════════════
# 1. TaskType Classification
# ═══════════════════════════════════════════════════════════════

def test_classify_review_diff():
    t, r, c = TaskClassifier.classify("review current diff for bugs")
    assert t == "review-diff", f"Expected review-diff, got {t}"
    assert r == "medium"


def test_classify_release_gate():
    t, r, c = TaskClassifier.classify("prepare release v2.3 for production deployment")
    assert t == "release-risk-review", f"Expected release-risk-review, got {t}"
    assert r == "high"


def test_classify_security_review():
    t, r, c = TaskClassifier.classify("audit codebase for SQL injection vulnerabilities")
    assert t == "security-review", f"Expected security-review, got {t}"
    assert r == "high"


def test_classify_api_execution_boundary_real_run():
    t, r, c = TaskClassifier.classify("implement guarded real-run adapter skeleton")
    assert t == "api-execution-boundary", f"Expected api-execution-boundary, got {t}"
    assert r == "high"


def test_classify_api_execution_boundary_deepseek_adapter():
    t, r, c = TaskClassifier.classify("design DeepSeek API execution adapter")
    assert t == "api-execution-boundary", f"Expected api-execution-boundary, got {t}"
    assert r == "high"


def test_classify_api_execution_boundary_key_handling():
    t, r, c = TaskClassifier.classify("add API key handling for DeepSeek provider call")
    assert t == "api-execution-boundary", f"Expected api-execution-boundary, got {t}"
    assert r == "high"


def test_classify_api_execution_boundary_call_seam():
    t, r, c = TaskClassifier.classify("wire real API call seam behind --real-run")
    assert t == "api-execution-boundary", f"Expected api-execution-boundary, got {t}"
    assert r == "high"


def test_no_false_positive_on_governance_tools():
    """Normal governance tools should NOT be classified as api-execution-boundary."""
    t1, r1, _ = TaskClassifier.classify("update cost ledger summary docs")
    assert t1 != "api-execution-boundary"
    assert r1 != "high"
    t2, r2, _ = TaskClassifier.classify("add privacy gate documentation")
    assert t2 != "api-execution-boundary"
    assert r2 != "high"


def test_classify_interface_change():
    t, r, c = TaskClassifier.classify("change the API interface for user creation")
    assert t == "interface-review", f"Expected interface-review, got {t}"
    assert r == "high"


def test_classify_architecture_refactor():
    t, r, c = TaskClassifier.classify("refactor the payment processing pipeline")
    assert t == "architecture-review", f"Expected architecture-review, got {t}"
    assert r == "medium"


def test_classify_bug_fix():
    t, r, c = TaskClassifier.classify("fix null pointer exception in login handler")
    assert t == "draft-fix", f"Expected draft-fix, got {t}"
    assert r == "medium"


def test_classify_test_failure():
    t, r, c = TaskClassifier.classify("analyze test failure in CI pipeline")
    assert t == "generate-test-plan", f"Expected generate-test-plan, got {t}"
    assert r == "medium"


def test_classify_simple_query():
    t, r, c = TaskClassifier.classify("explain what this function does")
    assert t == "summarize-file", f"Expected summarize-file, got {t}"
    assert r == "low"


def test_classify_schema_migration():
    t, r, c = TaskClassifier.classify("migrate database schema: add new column")
    assert t == "interface-review", f"Expected interface-review, got {t}"
    assert r == "high"


def test_classify_find_files():
    t, r, c = TaskClassifier.classify("search for all TODO comments in the codebase")
    assert t == "find-related-files", f"Expected find-related-files, got {t}"
    assert r == "low"


def test_classify_docs():
    t, r, c = TaskClassifier.classify("update README with new documentation")
    assert t == "rewrite-text", f"Expected rewrite-text, got {t}"
    assert r == "low"


def test_classify_governance_problems():
    t, r, c = TaskClassifier.classify("review PROBLEMS.md for missing entries")
    assert t == "governance-docs", f"Expected governance-docs, got {t}"
    assert r == "low"


def test_classify_governance_longtodo():
    t, r, c = TaskClassifier.classify("update LONGTODO.md with follow-up items")
    assert t == "governance-docs", f"Expected governance-docs, got {t}"
    assert r == "low"


def test_classify_governance_agents():
    t, r, c = TaskClassifier.classify("check AGENTS.md for outdated rules")
    assert t == "governance-docs", f"Expected governance-docs, got {t}"
    assert r == "low"


def test_classify_governance_claude():
    t, r, c = TaskClassifier.classify("update CLAUDE.md with new hook docs")
    assert t == "governance-docs", f"Expected governance-docs, got {t}"
    assert r == "low"


def test_classify_governance_changelog():
    t, r, c = TaskClassifier.classify("summarize CHANGELOG.md and suggest missing entries")
    assert t == "governance-docs", f"Expected governance-docs, got {t}"
    assert r == "low"


def test_classify_multi_service_feature():
    t, r, c = TaskClassifier.classify("add rate limiting to API gateway across 3 services")
    assert t == "draft-feature", f"Expected draft-feature, got {t}"
    assert r == "medium"


def test_classify_refactor_provider_config():
    t, r, c = TaskClassifier.classify("refactor provider config schema")
    assert t == "interface-review", f"Expected interface-review, got {t}"
    assert r == "high"


def test_classify_migration_database_columns():
    t, r, c = TaskClassifier.classify("review migration that changes database columns")
    assert t == "interface-review", f"Expected interface-review, got {t}"
    assert r == "high"


def test_classify_unknown():
    t, r, c = TaskClassifier.classify("xyzzy flurbo gronk")
    assert t == "unknown", f"Expected unknown, got {t}"
    assert r == "low"
    assert c < 0.5  # Low confidence for unknown


# ═══════════════════════════════════════════════════════════════
# 2. Risk Assessment
# ═══════════════════════════════════════════════════════════════

def test_risk_low():
    level, sigs = RiskAssessor.assess("explain what this function does", "low")
    assert level == "low"


def test_risk_medium():
    level, sigs = RiskAssessor.assess("refactor the payment module across multiple files", "medium")
    assert level == "medium"


def test_risk_high_from_base():
    level, sigs = RiskAssessor.assess("prepare release for production", "high")
    assert level == "high"


def test_risk_high_from_signals():
    level, sigs = RiskAssessor.assess(
        "fix authentication vulnerability and encryption issue", "medium"
    )
    assert level == "high"  # auth + encryption signals → high


def test_risk_critical():
    level, sigs = RiskAssessor.assess(
        "fix data loss and production outage causing security breach", "high"
    )
    assert level == "critical"


# ═══════════════════════════════════════════════════════════════
# 3. Privacy Gate
# ═══════════════════════════════════════════════════════════════

def test_privacy_safe():
    status, matches, allowed = PrivacyGate.check("review current diff")
    assert status == "safe"
    assert allowed is True


def test_privacy_api_key_blocked():
    status, matches, allowed = PrivacyGate.check(
        "use this API key: sk-12345678901234567890abcdef"
    )
    assert status == "blocked"
    assert allowed is False


def test_privacy_private_key_blocked():
    status, matches, allowed = PrivacyGate.check("""
    here is my key:
    -----BEGIN RSA PRIVATE KEY-----
    MIIEpAIBAAKCAQEA...
    -----END RSA PRIVATE KEY-----
    """)
    assert status == "blocked"
    assert allowed is False


def test_privacy_env_reference():
    # ".env" matches deepseek_client._check_privacy forbidden pattern -> blocked
    status, matches, allowed = PrivacyGate.check("update the .env file with new values")
    assert status == "blocked"
    assert allowed is False


def test_privacy_full_repo_blocked():
    status, matches, allowed = PrivacyGate.check("export the entire codebase to a zip file")
    assert status == "blocked"
    assert allowed is False


def test_privacy_credential_mention():
    # "credentials" without assignment (= or :) is safe
    status, matches, allowed = PrivacyGate.check("check the credentials for the database")
    assert status == "safe"
    assert allowed is True


# ═══════════════════════════════════════════════════════════════
# 4. Profile Mapping
# ═══════════════════════════════════════════════════════════════

def test_profile_diff_review():
    p = ProfileMapper.recommend("review-diff", "medium")
    assert p == "commit_reviewer", f"Expected commit_reviewer, got {p}"


def test_profile_bug_fix():
    p = ProfileMapper.recommend("draft-fix", "medium")
    assert p == "code_worker", f"Expected code_worker, got {p}"


def test_profile_simple_query():
    p = ProfileMapper.recommend("summarize-file", "low")
    assert p == "fast_summary", f"Expected fast_summary, got {p}"


def test_profile_governance_docs():
    p = ProfileMapper.recommend("governance-docs", "low")
    assert p == "docs_agent", f"Expected docs_agent, got {p}"


def test_profile_release_gate():
    p = ProfileMapper.recommend("release-risk-review", "high")
    assert p is None  # Too risky for local only


def test_profile_security_review():
    p = ProfileMapper.recommend("security-review", "high")
    assert p is None  # Too risky for local only


def test_profile_interface_change():
    p = ProfileMapper.recommend("interface-review", "high")
    assert p is None  # Too risky for local only


def test_profile_high_risk_local():
    # High risk but not blocked → pre-check only
    p = ProfileMapper.recommend("architecture-review", "high")
    assert p is not None
    assert "pre-check" in p.lower()


# ═══════════════════════════════════════════════════════════════
# 5. Escalation Policy
# ═══════════════════════════════════════════════════════════════

def test_escalation_flash_for_diff_review():
    cond = EscalationPolicy.get_flash_condition("review-diff", "medium", "safe")
    assert cond is not None
    assert "local failure" in cond


def test_escalation_pro_for_release():
    cond = EscalationPolicy.get_pro_condition("release-risk-review", "high", "safe")
    assert cond is not None
    assert "Pro review" in cond


def test_escalation_blocked_by_privacy():
    flash = EscalationPolicy.get_flash_condition("review-diff", "medium", "blocked")
    pro = EscalationPolicy.get_pro_condition("review-diff", "medium", "blocked")
    assert flash is None
    assert pro is None


def test_escalation_pro_for_security():
    cond = EscalationPolicy.get_pro_condition("security-review", "high", "safe")
    assert "Pro review" in cond


def test_escalation_pro_for_interface():
    cond = EscalationPolicy.get_pro_condition("interface-review", "high", "safe")
    assert "Pro gate" in cond


def test_escalation_flash_for_test_failure():
    cond = EscalationPolicy.get_flash_condition("generate-test-plan", "medium", "safe")
    assert "unresolved" in cond.lower() or "Flash" in cond


# ═══════════════════════════════════════════════════════════════
# 6. End-to-End RouterEngine
# ═══════════════════════════════════════════════════════════════

def test_engine_diff_review():
    engine = RouterEngine()
    d = engine.analyze("review current diff for bugs")
    assert d.task_type == "review-diff"
    assert d.risk_level == "medium"
    assert d.privacy_status == "safe"
    assert d.cloud_allowed is True
    assert d.recommended_local_profile is not None
    assert d.flash_escalation_condition is not None
    assert d.pro_escalation_condition is not None
    assert len(d.reason) > 20


def test_engine_release_gate():
    engine = RouterEngine()
    d = engine.analyze("prepare release v2.3 for production deployment")
    assert d.task_type == "release-risk-review"
    assert d.risk_level in ("high", "critical")
    assert d.recommended_local_profile is None  # Go to cloud directly
    assert "Pro review" in d.pro_escalation_condition


def test_engine_security_audit():
    engine = RouterEngine()
    d = engine.analyze("audit codebase for SQL injection vulnerabilities")
    assert d.task_type == "security-review"
    assert d.risk_level == "high"
    assert d.recommended_local_profile is None


def test_engine_simple_query():
    engine = RouterEngine()
    d = engine.analyze("explain what this function does")
    assert d.task_type == "summarize-file"
    assert d.risk_level == "low"
    assert d.cloud_allowed is True
    assert d.recommended_local_profile is not None


def test_engine_governance_docs():
    engine = RouterEngine()
    d = engine.analyze("review PROBLEMS.md for missing entries and update LONGTODO.md")
    assert d.task_type == "governance-docs"
    assert d.risk_level == "low"
    assert d.recommended_local_profile == "docs_agent"


def test_engine_multi_service_feature():
    engine = RouterEngine()
    d = engine.analyze("add rate limiting to API gateway across 3 services")
    assert d.task_type == "draft-feature"
    assert d.risk_level == "medium"
    assert d.recommended_local_profile == "code_worker"
    assert d.flash_escalation_condition is not None


def test_engine_refactor_provider_config():
    engine = RouterEngine()
    d = engine.analyze("refactor provider config schema")
    assert d.task_type == "interface-review"
    assert d.risk_level == "high"
    assert "Pro" in d.pro_escalation_condition


def test_engine_migration_columns():
    engine = RouterEngine()
    d = engine.analyze("review migration that changes database columns")
    assert d.task_type == "interface-review"
    assert d.risk_level == "high"
    assert "Pro" in d.pro_escalation_condition


def test_engine_changelog_governance():
    engine = RouterEngine()
    d = engine.analyze("summarize CHANGELOG.md and suggest missing entries")
    assert d.task_type == "governance-docs"
    assert d.risk_level == "low"
    assert d.recommended_local_profile == "docs_agent"


def test_engine_privacy_blocked():
    engine = RouterEngine()
    d = engine.analyze("use this API key: sk-12345678901234567890abcdef to access")
    assert d.privacy_status == "blocked"
    assert d.cloud_allowed is False
    assert d.flash_escalation_condition is None
    assert d.pro_escalation_condition is None


def test_engine_schema_migration():
    engine = RouterEngine()
    d = engine.analyze("migrate database schema: add new column to users table")
    assert d.task_type == "interface-review"
    assert d.risk_level == "high"
    assert d.recommended_local_profile is None
    assert "Pro" in d.pro_escalation_condition


# ═══════════════════════════════════════════════════════════════
# 7. Output Format
# ═══════════════════════════════════════════════════════════════

def test_to_dict_has_all_fields():
    engine = RouterEngine()
    d = engine.analyze("review current diff")
    data = d.to_dict()
    required = [
        "task_type", "risk_level", "privacy_status",
        "recommended_local_profile", "flash_escalation_condition",
        "pro_escalation_condition", "cloud_allowed", "reason",
    ]
    for field in required:
        assert field in data, f"Missing field: {field}"


def test_to_json_is_valid():
    engine = RouterEngine()
    d = engine.analyze("review current diff")
    j = d.to_json()
    parsed = json.loads(j)
    assert parsed["task_type"] == "review-diff"


def test_format_explain_output():
    engine = RouterEngine()
    d = engine.analyze("review current diff")
    text = format_explain(d)
    assert "ROUTER EXPLAIN" in text
    assert "Task type" in text
    assert "Risk level" in text
    assert "Privacy" in text
    assert "Cloud allowed" in text
    assert "Escalation path" in text
    assert "Reason:" in text


# ═══════════════════════════════════════════════════════════════
# 8. Edge Cases
# ═══════════════════════════════════════════════════════════════

def test_empty_input():
    engine = RouterEngine()
    d = engine.analyze("")
    assert d.task_type == "unknown"
    assert d.risk_level == "low"


def test_very_long_input():
    engine = RouterEngine()
    d = engine.analyze("fix bug " * 1000)
    assert d.task_type == "draft-fix"


def test_confidence_range():
    engine = RouterEngine()
    d = engine.analyze("review current diff for bugs and check for security issues")
    assert 0.0 <= d.confidence <= 1.0


# ═══════════════════════════════════════════════════════════════
# C1-C5 Calibration Round: governance-integration + control-plane-boundary
# ═══════════════════════════════════════════════════════════════

def test_c1_soft_gate_design_high():
    t, r, _ = TaskClassifier.classify("design Claude Code soft gate integration")
    assert t in ("governance-integration", "api-execution-boundary")
    assert r == "high"

def test_c1_convergence_audit_high():
    t, r, _ = TaskClassifier.classify("audit Claude Code soft gate skeleton convergence")
    assert t in ("governance-integration", "api-execution-boundary")
    assert r == "high"

def test_c1_calibration_plan_high():
    t, r, _ = TaskClassifier.classify("plan soft gate dogfood calibration after protocol")
    assert t in ("governance-integration", "api-execution-boundary")
    assert r == "high"

def test_c2_warning_gate_high():
    t, r, _ = TaskClassifier.classify("implement warning gate for Claude Code governance")
    assert t in ("governance-integration", "control-plane-boundary", "api-execution-boundary")
    assert r == "high"

def test_c2_stop_hook_high():
    t, r, _ = TaskClassifier.classify("integrate Stop hook into Claude Code workflow")
    assert t == "control-plane-boundary"
    assert r == "high"

def test_c2_hard_block_high():
    t, r, _ = TaskClassifier.classify("implement hard block for secret detection")
    assert t == "control-plane-boundary"
    assert r == "high"

def test_c5_mcp_gate_high():
    t, r, _ = TaskClassifier.classify("integrate MCP gate for tool-level access control")
    assert t == "control-plane-boundary"
    assert r == "high"

def test_c5_llm_proxy_high():
    t, r, _ = TaskClassifier.classify("implement llm-proxy for cloud model routing")
    assert t == "control-plane-boundary"
    assert r == "high"

def test_c5_auto_worker_high():
    t, r, _ = TaskClassifier.classify("implement automatic worker execution")
    assert t == "control-plane-boundary"
    assert r == "high"

def test_safe_readme_not_high():
    t, r, _ = TaskClassifier.classify("update README with new project description")
    assert r != "high"
    assert t not in ("governance-integration", "control-plane-boundary")

def test_safe_summarize_not_high():
    t, r, _ = TaskClassifier.classify("summarize the utils module for documentation")
    assert r == "low"


def test_signals_not_empty():
    engine = RouterEngine()
    d = engine.analyze("review current diff for bugs")
    assert len(d.signals) >= 3  # classification, risk, privacy, profile


# ═══════════════════════════════════════════════════════════════
# 9. DeepSeek V4 Flash/Pro Cost-Tiering Policy
# ═══════════════════════════════════════════════════════════════

def test_tier_flash_direct_summarize():
    r = TieringPolicy.resolve("summarize-file", "low", "safe")
    assert r["recommended_execution_route"] == "flash_direct"
    assert r["recommended_model"] == "deepseek-v4-flash"
    assert r["cost_tier"] == "cheap"
    assert r["context_overhead_warning"] is None


def test_tier_flash_direct_governance():
    r = TieringPolicy.resolve("governance-docs", "low", "safe")
    assert r["recommended_execution_route"] == "flash_direct"
    assert r["recommended_model"] == "deepseek-v4-flash"
    assert r["cost_tier"] == "cheap"


def test_tier_flash_direct_translate():
    r = TieringPolicy.resolve("translate-text", "low", "safe")
    assert r["recommended_execution_route"] == "flash_direct"
    assert r["cost_tier"] == "cheap"


def test_tier_flash_direct_find_files():
    r = TieringPolicy.resolve("find-related-files", "low", "safe")
    assert r["recommended_execution_route"] == "flash_direct"
    assert r["cost_tier"] == "cheap"


def test_tier_pro_code_modification_draft_fix():
    """draft-fix is code modification → claude_code_pro, not flash_subagent."""
    r = TieringPolicy.resolve("draft-fix", "medium", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["recommended_model"] == "deepseek-v4-pro"
    assert r["cost_tier"] == "expensive"
    assert "Code modification" in r["context_overhead_warning"]


def test_tier_pro_code_modification_draft_feature():
    r = TieringPolicy.resolve("draft-feature", "medium", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["recommended_model"] == "deepseek-v4-pro"
    assert r["cost_tier"] == "expensive"
    assert "Code modification" in r["context_overhead_warning"]


def test_tier_pro_code_modification_draft_refactor():
    r = TieringPolicy.resolve("draft-refactor", "medium", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["recommended_model"] == "deepseek-v4-pro"
    assert r["cost_tier"] == "expensive"
    assert "Code modification" in r["context_overhead_warning"]


def test_tier_flash_subagent_review_diff():
    r = TieringPolicy.resolve("review-diff", "medium", "safe")
    assert r["recommended_execution_route"] == "flash_subagent"
    assert r["cost_tier"] == "moderate"
    assert r["context_overhead_warning"] is not None


def test_tier_flash_subagent_test_plan():
    r = TieringPolicy.resolve("generate-test-plan", "medium", "safe")
    assert r["recommended_execution_route"] == "flash_subagent"
    assert r["cost_tier"] == "moderate"


def test_tier_pro_release():
    r = TieringPolicy.resolve("release-risk-review", "high", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["recommended_model"] == "deepseek-v4-pro"
    assert r["cost_tier"] == "expensive"
    assert "4x Flash cost" in r["context_overhead_warning"]


def test_tier_pro_security():
    r = TieringPolicy.resolve("security-review", "high", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["recommended_model"] == "deepseek-v4-pro"
    assert r["cost_tier"] == "expensive"


def test_tier_pro_interface():
    r = TieringPolicy.resolve("interface-review", "high", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["cost_tier"] == "expensive"


def test_tier_pro_architecture():
    r = TieringPolicy.resolve("architecture-review", "medium", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["cost_tier"] == "expensive"


def test_tier_pro_api_execution_boundary():
    r = TieringPolicy.resolve("api-execution-boundary", "high", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"


def test_tier_pro_governance_integration():
    r = TieringPolicy.resolve("governance-integration", "high", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"


def test_tier_pro_control_plane():
    r = TieringPolicy.resolve("control-plane-boundary", "high", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"


def test_tier_high_risk_escalates_to_pro():
    """Even non-Pro task types escalate to Pro when risk=high."""
    r = TieringPolicy.resolve("draft-fix", "high", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"
    assert r["recommended_model"] == "deepseek-v4-pro"
    assert r["cost_tier"] == "expensive"


def test_tier_critical_risk_escalates_to_pro():
    r = TieringPolicy.resolve("draft-feature", "critical", "safe")
    assert r["recommended_execution_route"] == "claude_code_pro"


def test_tier_privacy_blocked():
    r = TieringPolicy.resolve("draft-fix", "medium", "blocked")
    assert r["recommended_execution_route"] == "blocked"
    assert r["recommended_model"] is None
    assert r["cost_tier"] == "free"
    assert r["context_overhead_warning"] is None


def test_tier_privacy_needs_sanitization():
    r = TieringPolicy.resolve("summarize-file", "low", "needs_sanitization")
    # needs_sanitization is NOT blocked → should still route normally
    assert r["recommended_execution_route"] == "flash_direct"
    assert r["cost_tier"] == "cheap"


def test_tier_unknown_manual_confirm():
    r = TieringPolicy.resolve("unknown", "low", "safe")
    assert r["recommended_execution_route"] == "manual_confirm"
    assert r["recommended_model"] is None
    assert r["cost_tier"] == "free"
    assert "unclassified" in r["context_overhead_warning"].lower()


def test_tier_fallback_local_only():
    """Unrecognized task_type with low risk → local_only fallback."""
    # Use a task_type that's not in any set
    r = TieringPolicy.resolve("hypothetical-future-task", "low", "safe")
    assert r["recommended_execution_route"] == "local_only"
    assert r["recommended_model"] is None
    assert r["cost_tier"] == "free"


# ═══════════════════════════════════════════════════════════════
# 10. Tiering integration in RouterEngine output
# ═══════════════════════════════════════════════════════════════

def test_engine_output_includes_tier_fields():
    engine = RouterEngine()
    d = engine.analyze("summarize this file for me")
    assert d.recommended_execution_route == "flash_direct"
    assert d.recommended_model == "deepseek-v4-flash"
    assert d.cost_tier == "cheap"
    assert d.context_overhead_warning is None


def test_engine_output_pro_fields():
    engine = RouterEngine()
    d = engine.analyze("prepare release v2.3 for production deployment")
    assert d.recommended_execution_route == "claude_code_pro"
    assert d.recommended_model == "deepseek-v4-pro"
    assert d.cost_tier == "expensive"


def test_engine_output_code_modification_warning():
    """draft-fix → claude_code_pro, NOT flash_subagent."""
    engine = RouterEngine()
    d = engine.analyze("fix null pointer exception in login handler")
    assert d.recommended_execution_route == "claude_code_pro"
    assert d.recommended_model == "deepseek-v4-pro"
    assert d.cost_tier == "expensive"
    assert "Code modification" in d.context_overhead_warning


def test_engine_output_subagent_for_review():
    """review-diff → flash_subagent (review, not code modification)."""
    engine = RouterEngine()
    d = engine.analyze("review current diff for bugs")
    assert d.recommended_execution_route == "flash_subagent"
    assert d.recommended_model == "deepseek-v4-flash"
    assert d.cost_tier == "moderate"
    assert "90k tokens" in d.context_overhead_warning


def test_engine_output_blocked_tier():
    engine = RouterEngine()
    d = engine.analyze("use this API key: sk-12345678901234567890abcdef")
    assert d.recommended_execution_route == "blocked"
    assert d.recommended_model is None
    assert d.cost_tier == "free"


def test_to_dict_includes_tier_fields():
    engine = RouterEngine()
    d = engine.analyze("review current diff for bugs")
    data = d.to_dict()
    tier_fields = [
        "recommended_execution_route",
        "recommended_model",
        "cost_tier",
        "context_overhead_warning",
    ]
    for field in tier_fields:
        assert field in data, f"Missing tier field: {field}"


def test_tiering_signals_in_output():
    engine = RouterEngine()
    d = engine.analyze("review current diff for bugs")
    assert "tiering" in d.signals
    assert any("route=" in s for s in d.signals["tiering"])
    assert any("model=" in s for s in d.signals["tiering"])
    assert any("cost=" in s for s in d.signals["tiering"])


def test_tiering_policy_no_api_calls():
    """TieringPolicy.resolve is pure function — no API calls, no I/O.

    Note: "deepseek-v4-flash" / "deepseek-v4-pro" appear as string literals
    (recommended model names), not as API calls. That's expected and safe.
    """
    import inspect
    source = inspect.getsource(TieringPolicy.resolve)
    assert "requests" not in source
    assert "http" not in source
    assert "openai" not in source.lower()
    assert "urllib" not in source
    assert "subprocess" not in source
    assert "os.environ" not in source
    # Verify no DeepSeek SDK import or client call (model name strings are OK)
    assert "DeepSeekClient" not in source
    assert "deepseek_client" not in source
    assert "api_key" not in source.lower()
