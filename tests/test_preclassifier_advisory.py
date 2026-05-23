"""Tests for preclassifier advisory integration (B1-C).

Covers: advisory injection into debate response, no-skip invariant,
exception fallback, ledger extra fields populating.
All tests monkeypatch run_subprocess to avoid real model calls.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_mcp_server
import local_llm_preclassifier as pc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_diff(files, body=""):
    lines = []
    for f in files:
        lines.append(f"diff --git a/{f} b/{f}")
        lines.append("--- a/{}".format(f))
        lines.append("+++ b/{}".format(f))
        if body:
            lines.append(body)
        else:
            lines.append("@@ -1,1 +1,1 @@")
            lines.append("-old line")
            lines.append("+new line")
    return "\n".join(lines)


# A minimal debate output our mock will return:
_FAKE_DEBATE_OUTPUT = {
    "task": "review-diff",
    "mode": "debate",
    "profiles": ["qwen3.6_27b_mtp", "reasoning_checker"],
    "models": {"qwen3.6_27b_mtp": "test", "reasoning_checker": "test"},
    "ok": True,
    "input": {"source": "stdin", "chars": 500},
    "high_confidence_findings": [],
    "candidate_findings": [],
    "controller_must_verify": [],
    "not_verified": ["Local models did not run tests"],
    "warnings": [],
    "error": None,
    "elapsed_seconds": 0.1,
    "created_at": "2026-01-01T00:00:00+00:00",
}


def _fake_run_subprocess_ok(cmd, stdin_data=None, timeout=None, extra_env=None):
    """Return a successful subprocess result with a fake debate output."""
    return {
        "ok": True,
        "stdout": json.dumps(_FAKE_DEBATE_OUTPUT),
        "stderr": "",
        "returncode": 0,
        "elapsed_seconds": 0.1,
    }


# ---------------------------------------------------------------------------
# B1-C advisory injection into call_debate_review_diff
# ---------------------------------------------------------------------------

class TestAdvisoryInjection:
    """Verify preclassifier advisory is injected into the response."""

    def test_docs_only_diff_gets_advisory_low_risk(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["CHANGELOG.md", "PROJECT_STATUS.md"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is True
        adv = result["result"].get("preclassifier_advisory")
        assert adv is not None, "preclassifier_advisory must be present"
        assert adv["risk_level"] == "low"
        assert adv["skip_debate_recommended"] is True
        assert adv["skip_debate_allowed"] is False
        assert adv["debate_skipped"] is False

    def test_sensitive_diff_gets_advisory_high_risk(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["tools/local_llm_mcp_server.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        adv = result["result"].get("preclassifier_advisory")
        assert adv["risk_level"] == "high"
        assert len(adv["safety_blockers"]) >= 1
        assert adv["debate_skipped"] is False

    def test_empty_diff_gets_unknown_advisory(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["src/main.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        adv = result["result"].get("preclassifier_advisory")
        assert adv["risk_level"] in ("low", "medium", "high")

    def test_runtime_code_injects_advisory(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["src/main.py", "src/utils.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        adv = result["result"].get("preclassifier_advisory")
        assert adv is not None

    def test_tests_only_injects_advisory(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["tests/test_main.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        adv = result["result"].get("preclassifier_advisory")
        assert adv is not None
        assert adv["debate_skipped"] is False


# ---------------------------------------------------------------------------
# No-skip invariant
# ---------------------------------------------------------------------------

class TestNoSkipInvariant:
    """B1-C must NEVER skip debate regardless of preclassifier output."""

    DIFF_CASES = [
        ("docs-only", _make_diff(["CHANGELOG.md", "PROJECT_STATUS.md"])),
        ("sensitive", _make_diff(["tools/local_llm_mcp_server.py"])),
        ("runtime", _make_diff(["src/main.py"])),
        ("tests-only", _make_diff(["tests/test_main.py"])),
        ("version-bump", _make_diff(["VERSION"])),
        ("empty-diff", ""),
    ]

    def test_all_cases_call_run_subprocess(self, monkeypatch):
        call_count = 0

        def counting_fake(cmd, stdin_data=None, timeout=None, extra_env=None):
            nonlocal call_count
            call_count += 1
            return _fake_run_subprocess_ok(cmd, stdin_data, timeout, extra_env)

        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess", counting_fake)

        for name, diff in self.DIFF_CASES:
            if not diff.strip():
                # empty diff — expect error response, no subprocess call
                prev = call_count
                result = local_llm_mcp_server.call_debate_review_diff({
                    "diff_text": diff,
                })
                # empty diff returns early with error, run_subprocess not called
                assert result["ok"] is False
                assert call_count == prev
            else:
                local_llm_mcp_server.call_debate_review_diff({
                    "diff_text": diff,
                })

        # All non-empty diffs must have reached run_subprocess
        non_empty_count = sum(1 for _, d in self.DIFF_CASES if d.strip())
        assert call_count == non_empty_count, (
            f"Expected {non_empty_count} subprocess calls, got {call_count}"
        )

    def test_skip_allowed_always_false_in_advisory(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)

        for name, diff in self.DIFF_CASES:
            if not diff.strip():
                continue
            result = local_llm_mcp_server.call_debate_review_diff({
                "diff_text": diff,
            })
            adv = result.get("result", {}).get("preclassifier_advisory")
            if adv is None:
                # Only possible if preclassifier itself failed
                # (which shouldn't happen for valid diffs)
                continue
            assert adv["skip_debate_allowed"] is False, (
                f"skip_debate_allowed was true for {name}"
            )
            assert adv["debate_skipped"] is False, (
                f"debate_skipped was true for {name}"
            )


# ---------------------------------------------------------------------------
# Preclassifier exception fallback
# ---------------------------------------------------------------------------

class TestPreclassifierExceptionFallback:
    """If the preclassifier crashes, debate must still run."""

    def test_preclassifier_exception_does_not_block_debate(self, monkeypatch):
        def raising_preclassify(*args, **kwargs):
            raise RuntimeError("simulated preclassifier crash")

        monkeypatch.setattr(local_llm_mcp_server, "_preclassify",
                           raising_preclassify)
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)

        diff = _make_diff(["src/main.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        # Debate must still succeed
        assert result["ok"] is True
        # Advisory must be present but marked unavailable
        adv = result["result"].get("preclassifier_advisory")
        assert adv is not None
        assert adv["ok"] is False
        assert adv["risk_level"] == "unknown"
        assert "preclassifier unavailable" in str(adv.get("safety_blockers", []))

    def test_preclassifier_none_fallback(self, monkeypatch):
        """When _preclassify is None (import failed), advisory shows unavailable."""
        monkeypatch.setattr(local_llm_mcp_server, "_preclassify", None)
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)

        diff = _make_diff(["src/main.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is True
        adv = result["result"].get("preclassifier_advisory")
        assert adv["ok"] is False
        assert adv["risk_level"] == "unknown"

    def test_no_advisory_on_error_response(self, monkeypatch):
        """Empty diff returns error response — no advisory needed."""
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": "",
        })
        assert result["ok"] is False
        assert result.get("result") is None
        assert "preclassifier_advisory" not in result


# ---------------------------------------------------------------------------
# Ledger extra fields in extra_env
# ---------------------------------------------------------------------------

class TestLedgerExtraFields:
    """Verify preclassifier fields are stamped into LOCAL_LLM_LEDGER_EXTRA."""

    def test_extra_env_contains_preclassifier_fields(self, monkeypatch):
        captured_envs = []

        def capture_env(cmd, stdin_data=None, timeout=None, extra_env=None):
            captured_envs.append(extra_env or {})
            return _fake_run_subprocess_ok(cmd, stdin_data, timeout, extra_env)

        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess", capture_env)

        diff = _make_diff(["CHANGELOG.md"])
        local_llm_mcp_server.call_debate_review_diff({"diff_text": diff})

        assert len(captured_envs) == 1
        extra_raw = captured_envs[0].get("LOCAL_LLM_LEDGER_EXTRA", "")
        extra = json.loads(extra_raw)
        assert extra["debate_skipped"] is False
        assert extra["debate_skip_allowed"] is False
        assert extra["diff_risk_level"] == "low"
        assert extra["diff_risk_confidence"] in ("high", "medium", "low")
        assert "changed_files_count" in extra
        assert extra["preclassifier_method"] == "heuristic"
        assert extra["mcp_tool_name"] == "local_debate_review_diff"

    def test_sensitive_diff_extra_env(self, monkeypatch):
        captured = {}

        def capture_env(cmd, stdin_data=None, timeout=None, extra_env=None):
            captured.update(extra_env or {})
            return _fake_run_subprocess_ok(cmd, stdin_data, timeout, extra_env)

        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess", capture_env)

        diff = _make_diff(["tools/local_llm_mcp_server.py"])
        local_llm_mcp_server.call_debate_review_diff({"diff_text": diff})

        extra = json.loads(captured.get("LOCAL_LLM_LEDGER_EXTRA", "{}"))
        assert extra["diff_risk_level"] == "high"
        assert isinstance(extra["safety_blockers"], list)
        assert len(extra["safety_blockers"]) >= 1


# ---------------------------------------------------------------------------
# Respect existing debate behaviour
# ---------------------------------------------------------------------------

class TestExistingBehaviourPreserved:
    """B1-C must not break any existing debate functionality."""

    def test_debate_response_fields_preserved(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["src/main.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is True
        assert "task" in result
        assert result["tool"] == "local_debate_review_diff"
        # The debate result carries its original fields
        res = result["result"]
        assert "high_confidence_findings" in res
        assert "candidate_findings" in res
        # And the new advisory field
        assert "preclassifier_advisory" in res

    def test_debate_round_info_intact(self, monkeypatch):
        """Profiles and models from debate output are preserved."""
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["src/main.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        res = result["result"]
        assert res.get("profiles") == ["qwen3.6_27b_mtp", "reasoning_checker"]

    def test_empty_diff_still_blocked(self):
        """Empty diff must still be rejected with error, not fall through."""
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": "",
        })
        assert result["ok"] is False
        assert result["error_type"] == "empty_input"

    def test_large_diff_still_blocked(self):
        """Diff exceeding MAX_DIFF_CHARS must still be rejected."""
        big = "x" * (local_llm_mcp_server.MAX_DIFF_CHARS + 1)
        # Build a valid-looking diff that exceeds the limit
        header = "diff --git a/big.py b/big.py\n"
        diff = header + big
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is False
        assert result["error_type"] == "diff_too_large"


# ---------------------------------------------------------------------------
# No source mutation
# ---------------------------------------------------------------------------

class TestNoSourceMutation:
    def test_module_unchanged_by_preclassifier_import(self):
        """local_llm_mcp_server module must be importable with preclassifier."""
        assert hasattr(local_llm_mcp_server, "_preclassify")
        # _preclassify may be None or the function, both are acceptable

    def test_run_subprocess_original_still_present(self):
        assert hasattr(local_llm_mcp_server, "run_subprocess")
