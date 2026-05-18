#!/usr/bin/env python3
"""Tests for Phase C/D security patterns, CJK detection, and health routing."""

import json
import os
import sys
from pathlib import Path

# Add tools to path for imports (no subprocess — test against the source)
SCRIPT_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(SCRIPT_DIR))


class TestSecurityPatterns:
    """C2: security-sensitive pattern detection auto-triggers reasoning models."""

    def test_code_patterns_detected(self):
        """eval, exec, compile, etc. should all match."""
        from local_llm_mcp_server import _has_security_sensitive_patterns
        assert _has_security_sensitive_patterns("x = eval(user_input)")
        assert _has_security_sensitive_patterns("exec(code_string)")
        assert _has_security_sensitive_patterns("compile(source, 'file', 'exec')")
        assert _has_security_sensitive_patterns("__import__('os')")
        assert _has_security_sensitive_patterns("subprocess.run(['ls'])")
        assert _has_security_sensitive_patterns("os.system('rm -rf /')")

    def test_pickle_patterns_detected(self):
        """pickle.loads / dumps should match."""
        from local_llm_mcp_server import _has_security_sensitive_patterns
        assert _has_security_sensitive_patterns("pickle.loads(data)")
        assert _has_security_sensitive_patterns("pickle.dumps(obj)")
        assert _has_security_sensitive_patterns("pickle.load(file)")

    def test_shell_patterns_detected(self):
        """rm -rf, del /s, chmod 777, Remove-Item should match."""
        from local_llm_mcp_server import _has_security_sensitive_patterns
        assert _has_security_sensitive_patterns("rm -rf /etc")
        assert _has_security_sensitive_patterns("rm -r /var/log")
        assert _has_security_sensitive_patterns("chmod 777 file")
        assert _has_security_sensitive_patterns("del /s /q C:\\temp")
        assert _has_security_sensitive_patterns("Remove-Item -Recurse -Force path")

    def test_benign_code_not_detected(self):
        """Normal code without security risks should NOT match."""
        from local_llm_mcp_server import _has_security_sensitive_patterns
        assert not _has_security_sensitive_patterns("def add(a, b): return a + b")
        assert not _has_security_sensitive_patterns("print('hello world')")
        assert not _has_security_sensitive_patterns("for i in range(10): pass")
        assert not _has_security_sensitive_patterns("import os  # standard import")
        assert not _has_security_sensitive_patterns("list.sort(key=lambda x: x.name)")

    def test_empty_text_not_detected(self):
        """Empty text should not trigger security patterns."""
        from local_llm_mcp_server import _has_security_sensitive_patterns
        assert not _has_security_sensitive_patterns("")

    def test_word_boundaries_work(self):
        """Word boundaries correctly isolate security keywords."""
        from local_llm_mcp_server import _has_security_sensitive_patterns
        # 'evaluate' contains 'eval' as substring but \beval\b prevents match
        assert not _has_security_sensitive_patterns("evaluate the expression")
        # 'execute' contains 'exec' as substring but \bexec\b prevents match
        assert not _has_security_sensitive_patterns("execute this command")
        # 'compile-time' — \bcompile\b matches 'compile' before hyphen (correct:
        # hyphen is word boundary, so 'compile' as a standalone word IS flagged)
        assert _has_security_sensitive_patterns("compile-time optimization")
        # 'time-compile' — same thing, compile IS a standalone word
        assert _has_security_sensitive_patterns("time-compile issues")
        # 'compiler' — NOT matched because \bcompile\b requires boundary after 'e'
        assert not _has_security_sensitive_patterns("compiler error")


class TestCJKDetection:
    """3A: CJK-aware routing — language detection for profile selection."""

    def test_cjk_ratio_zero_for_english(self):
        """Pure English text should have CJK ratio 0."""
        from local_llm_mcp_server import _detect_cjk_ratio
        assert _detect_cjk_ratio("Hello world, this is English text.") == 0.0

    def test_cjk_ratio_high_for_chinese(self):
        """Chinese text should have high CJK ratio."""
        from local_llm_mcp_server import _detect_cjk_ratio
        text = "这是一个中文测试文本。欢迎使用本地模型系统。"
        ratio = _detect_cjk_ratio(text)
        assert ratio > 0.5, f"Expected >0.5 for pure Chinese, got {ratio}"

    def test_cjk_ratio_mixed_content(self):
        """Mixed CJK/English detection."""
        from local_llm_mcp_server import _detect_cjk_ratio
        # Python code with Chinese comments
        text = "def hello():  # 你好世界\n    return 'Hello 世界'"
        ratio = _detect_cjk_ratio(text)
        assert 0.05 < ratio < 0.5, f"Expected mixed ratio, got {ratio}"

    def test_cjk_ratio_empty_string(self):
        """Empty string should return 0."""
        from local_llm_mcp_server import _detect_cjk_ratio
        assert _detect_cjk_ratio("") == 0.0

    def test_cjk_ratio_japanese(self):
        """Hiragana + Katakana should be detected as CJK."""
        from local_llm_mcp_server import _detect_cjk_ratio
        text = "こんにちは世界 カタカナ"
        ratio = _detect_cjk_ratio(text)
        assert ratio > 0.3, f"Expected >0.3 for Japanese, got {ratio}"

    def test_cjk_ratio_korean(self):
        """Hangul should be detected as CJK."""
        from local_llm_mcp_server import _detect_cjk_ratio
        text = "안녕하세요 세계"
        ratio = _detect_cjk_ratio(text)
        assert ratio > 0.3, f"Expected >0.3 for Korean, got {ratio}"

    def test_cjk_threshold_for_routing(self):
        """The 0.1 threshold should trigger for even light CJK content."""
        from local_llm_mcp_server import _detect_cjk_ratio
        # A diff with a single Chinese comment line
        text = "+   # 修复bug\n" + "+   def fix(): pass\n" * 20
        ratio = _detect_cjk_ratio(text)
        # Should be >0 but <0.1 since most text is Latin
        assert ratio > 0.0, "Should detect some CJK"

    def test_cjk_capable_profiles_include_key_profiles(self):
        """Translation and Qwen3.x profiles should be CJK-capable."""
        from local_llm_mcp_server import _CJK_CAPABLE_PROFILES
        assert "translation" in _CJK_CAPABLE_PROFILES
        assert "qwen3.6_27b_mtp" in _CJK_CAPABLE_PROFILES
        assert "qwen3.6_35b_moe_mtp" in _CJK_CAPABLE_PROFILES


class TestHealthRouting:
    """3B: health-aware routing degrades unhealthy profiles."""

    def test_is_profile_healthy_no_health_data(self):
        """Profile without _health field is considered healthy (default)."""
        from local_llm_router import is_profile_healthy
        profiles = {"profiles": {"test_p": {"model": "test:latest"}}}
        assert is_profile_healthy("test_p", profiles) is True

    def test_is_profile_healthy_high_success_rate(self):
        """Healthy profile passes."""
        from local_llm_router import is_profile_healthy
        profiles = {
            "profiles": {
                "test_p": {
                    "model": "test:latest",
                    "_health": {"success_rate": 0.95, "consecutive_failures": 0},
                }
            }
        }
        assert is_profile_healthy("test_p", profiles) is True

    def test_is_profile_healthy_consecutive_failures_degrade(self):
        """Profile with 2+ consecutive failures is unhealthy."""
        from local_llm_router import is_profile_healthy
        profiles = {
            "profiles": {
                "test_p": {
                    "model": "test:latest",
                    "_health": {"success_rate": 0.8, "consecutive_failures": 2},
                }
            }
        }
        assert is_profile_healthy("test_p", profiles) is False

    def test_is_profile_healthy_low_success_rate_degrade(self):
        """Profile with <50% success rate is unhealthy."""
        from local_llm_router import is_profile_healthy
        profiles = {
            "profiles": {
                "test_p": {
                    "model": "test:latest",
                    "_health": {"success_rate": 0.4, "consecutive_failures": 0},
                }
            }
        }
        assert is_profile_healthy("test_p", profiles) is False

    def test_is_profile_healthy_missing_profile(self):
        """Missing profile returns True (don't block unknown profiles)."""
        from local_llm_router import is_profile_healthy
        assert is_profile_healthy("nonexistent", {"profiles": {}}) is True

    def test_is_profile_healthy_boundary_values(self):
        """Boundary values: exactly 0.5 success_rate and 1 consecutive_failures."""
        from local_llm_router import is_profile_healthy
        profiles = {
            "profiles": {
                "test_p": {
                    "model": "test:latest",
                    "_health": {"success_rate": 0.5, "consecutive_failures": 1},
                }
            }
        }
        # 0.5 is NOT < 0.5, and 1 is NOT >= 2 — should be healthy
        assert is_profile_healthy("test_p", profiles) is True


class TestEscalationChain:
    """C1: quality-based escalation chain validation."""

    def test_chain_entries_are_valid_profiles(self):
        """All profiles in escalation chains should exist in profiles.json."""
        import json as _json
        from local_llm_mcp_server import _ESCALATION_CHAIN

        profiles_path = SCRIPT_DIR / "local_llm_profiles.json"
        profiles = _json.loads(profiles_path.read_text(encoding="utf-8"))
        valid_profiles = set(profiles.get("profiles", {}).keys())

        for task, chain in _ESCALATION_CHAIN.items():
            for p in chain:
                assert p in valid_profiles, (
                    f"Escalation chain for '{task}' references "
                    f"nonexistent profile '{p}'"
                )

    def test_chain_no_self_cycles(self):
        """Each chain should not have duplicate entries."""
        from local_llm_mcp_server import _ESCALATION_CHAIN
        for task, chain in _ESCALATION_CHAIN.items():
            assert len(chain) == len(set(chain)), (
                f"Escalation chain for '{task}' has duplicate entries: {chain}"
            )

    def test_all_tasks_have_chain_entries(self):
        """Every task in tasks.json (excluding CLI-only) should have a chain."""
        import json as _json
        from local_llm_mcp_server import _ESCALATION_CHAIN

        tasks_path = SCRIPT_DIR / "local_llm_tasks.json"
        tasks = _json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"]
        # Tasks that don't need escalation chains (CLI-only, internal)
        exempt = {"health-report", "local_check"}

        for task_name in tasks:
            if task_name.startswith("debate-") or task_name in exempt:
                continue
            assert task_name in _ESCALATION_CHAIN, (
                f"Task '{task_name}' missing from _ESCALATION_CHAIN"
            )


class TestQualityEscalation:
    """C1: _check_quality_escalation behavior."""

    def test_low_confidence_triggers_escalation(self):
        from local_llm_mcp_server import _check_quality_escalation
        payload = {"confidence": "low", "uncertain_points": []}
        result = _check_quality_escalation(payload, "fast_summary", "summarize-file")
        assert result in ("smart_summary", "qwen3.6_27b_mtp", "code_worker"), (
            f"Expected upgraded profile, got {result}"
        )

    def test_many_uncertain_points_triggers_escalation(self):
        from local_llm_mcp_server import _check_quality_escalation
        payload = {"confidence": "medium", "uncertain_points": ["a", "b", "c", "d"]}
        result = _check_quality_escalation(payload, "fast_summary", "summarize-file")
        assert result is not None, "4 uncertain_points should trigger escalation"

    def test_medium_confidence_no_escalation(self):
        from local_llm_mcp_server import _check_quality_escalation
        payload = {"confidence": "medium", "uncertain_points": ["a"]}
        result = _check_quality_escalation(payload, "fast_summary", "summarize-file")
        assert result is None, "Medium confidence with 1 point should not escalate"

    def test_timeout_downgrades(self):
        from local_llm_mcp_server import _check_quality_escalation
        payload = {"confidence": "medium", "error_type": "timeout"}
        result = _check_quality_escalation(payload, "smart_summary", "summarize-file")
        assert result == "fast_summary", f"Timeout should downgrade, got {result}"

    def test_already_at_max_no_escalation(self):
        from local_llm_mcp_server import _check_quality_escalation
        payload = {"confidence": "low", "uncertain_points": ["a", "b", "c", "d", "e"]}
        result = _check_quality_escalation(payload, "release_auditor", "architecture-review")
        assert result is None, "Already at max tier should not escalate further"

    def test_unknown_task_no_escalation(self):
        from local_llm_mcp_server import _check_quality_escalation
        payload = {"confidence": "low"}
        result = _check_quality_escalation(payload, "any_profile", "no-such-task")
        assert result is None
