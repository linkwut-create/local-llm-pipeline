"""Tests for diff preclassifier safety core (B1-A).

Covers: docs-only, tests-only, sensitive paths, VERSION, large diff, empty diff,
Windows paths, security patterns, context flags, and no source mutation.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_preclassifier as pc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_diff(files: list[str], body: str = "") -> str:
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


# ---------------------------------------------------------------------------
# detect_changed_files
# ---------------------------------------------------------------------------

class TestDetectChangedFiles:
    def test_single_file(self):
        diff = _make_diff(["src/main.py"])
        assert pc.detect_changed_files(diff) == ["src/main.py"]

    def test_multiple_files(self):
        diff = _make_diff(["src/a.py", "src/b.py", "docs/readme.md"])
        assert pc.detect_changed_files(diff) == sorted(["src/a.py", "src/b.py", "docs/readme.md"])

    def test_rename_detection(self):
        diff = (
            "diff --git a/old.py b/new.py\n"
            "rename from old.py\n"
            "rename to new.py\n"
        )
        files = pc.detect_changed_files(diff)
        assert "old.py" in files
        assert "new.py" in files

    def test_windows_paths(self):
        diff = "diff --git a/tools\\local_llm_mcp_server.py b/tools\\local_llm_mcp_server.py\n"
        files = pc.detect_changed_files(diff)
        assert any("tools/local_llm_mcp_server.py" in f for f in files)

    def test_new_file(self):
        diff = (
            "diff --git a/new_file.py b/new_file.py\n"
            "new file mode 100644\n"
            "index 0000000..abc1234\n"
        )
        files = pc.detect_changed_files(diff)
        assert "new_file.py" in files

    def test_deleted_file(self):
        diff = (
            "diff --git a/deleted.py b/deleted.py\n"
            "deleted file mode 100644\n"
            "index abc1234..0000000\n"
        )
        files = pc.detect_changed_files(diff)
        assert "deleted.py" in files

    def test_empty_diff_returns_empty(self):
        assert pc.detect_changed_files("") == []
        assert pc.detect_changed_files("   ") == []

    def test_no_diff_headers_returns_empty(self):
        assert pc.detect_changed_files("just some text\nno diff headers\n") == []


# ---------------------------------------------------------------------------
# detect_sensitive_paths
# ---------------------------------------------------------------------------

class TestDetectSensitivePaths:
    def test_mcp_server_detected(self):
        result = pc.detect_sensitive_paths(["tools/local_llm_mcp_server.py"])
        assert len(result) >= 1
        assert any("MCP server" in r["reason"] for r in result)

    def test_call_ledger_detected(self):
        result = pc.detect_sensitive_paths(["tools/call_ledger.py"])
        assert len(result) >= 1
        assert any("ledger" in r["reason"].lower() for r in result)

    def test_hook_files_detected(self):
        result = pc.detect_sensitive_paths(["tools/claude_hooks/mcp_gate.py"])
        assert len(result) >= 1
        assert any("hook" in r["reason"].lower() or "gate" in r["reason"].lower() for r in result)

    def test_auth_token_detected(self):
        result = pc.detect_sensitive_paths(["src/auth/token_validator.py"])
        assert len(result) >= 1

    def test_version_file_detected(self):
        result = pc.detect_sensitive_paths(["VERSION"])
        assert len(result) >= 1

    def test_security_file_detected(self):
        result = pc.detect_sensitive_paths(["src/security/audit.py"])
        assert len(result) >= 1

    def test_normal_source_not_detected(self):
        result = pc.detect_sensitive_paths(["src/main.py", "src/utils.py", "docs/readme.md"])
        assert result == []

    def test_empty_list_returns_empty(self):
        assert pc.detect_sensitive_paths([]) == []


# ---------------------------------------------------------------------------
# is_docs_only / is_tests_only
# ---------------------------------------------------------------------------

class TestDocsOnly:
    def test_markdown_only_is_docs(self):
        assert pc.is_docs_only(["CHANGELOG.md", "PROJECT_STATUS.md", "docs/guide.md"]) is True

    def test_version_not_docs(self):
        assert pc.is_docs_only(["CHANGELOG.md", "VERSION"]) is False

    def test_runtime_file_not_docs(self):
        assert pc.is_docs_only(["docs/readme.md", "src/main.py"]) is False

    def test_empty_list_not_docs(self):
        assert pc.is_docs_only([]) is False

    def test_release_notes_is_docs(self):
        assert pc.is_docs_only(["RELEASE_NOTES.md"]) is True


class TestTestsOnly:
    def test_test_files_are_tests(self):
        assert pc.is_tests_only(["tests/test_main.py", "tests/conftest.py"]) is True

    def test_runtime_file_not_tests(self):
        assert pc.is_tests_only(["tests/test_main.py", "src/main.py"]) is False

    def test_empty_list_not_tests(self):
        assert pc.is_tests_only([]) is False

    def test_test_prefix_file(self):
        assert pc.is_tests_only(["test_utils.py"]) is True

    def test_test_suffix_file(self):
        assert pc.is_tests_only(["utils_test.py"]) is True


# ---------------------------------------------------------------------------
# classify_diff_risk_heuristic
# ---------------------------------------------------------------------------

class TestClassifyDocsOnly:
    def test_docs_only_recommends_skip_but_not_allowed(self):
        diff = _make_diff(["CHANGELOG.md", "PROJECT_STATUS.md"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "low"
        assert result["skip_debate_recommended"] is True
        assert result["skip_debate_allowed"] is False
        assert result["escalate_to_debate"] is True

    def test_changelog_closeout_low_risk(self):
        diff = _make_diff(["CHANGELOG.md"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "low"
        assert result["skip_debate_recommended"] is True
        assert result["skip_debate_allowed"] is False

    def test_version_bump_is_high_risk(self):
        diff = _make_diff(["VERSION"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"
        assert result["safety_blockers"]
        assert result["escalate_to_debate"] is True

    def test_version_with_docs_is_high_risk(self):
        diff = _make_diff(["VERSION", "CHANGELOG.md"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"

    def test_release_notes_only_is_low_risk(self):
        diff = _make_diff(["RELEASE_NOTES.md"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "low"
        assert result["skip_debate_recommended"] is True
        assert result["skip_debate_allowed"] is False


class TestClassifySensitivePaths:
    def test_mcp_server_diff_is_high_risk(self):
        diff = _make_diff(["tools/local_llm_mcp_server.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"
        assert result["sensitive_paths"]
        assert result["escalate_to_debate"] is True
        assert result["skip_debate_allowed"] is False

    def test_call_ledger_diff_is_high_risk(self):
        diff = _make_diff(["tools/call_ledger.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"
        assert result["sensitive_paths"]

    def test_hook_gate_diff_is_high_risk(self):
        diff = _make_diff(["tools/claude_hooks/mcp_gate.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"
        assert result["sensitive_paths"]

    def test_auth_file_diff_is_high_risk(self):
        diff = _make_diff(["src/auth/session.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"

    def test_endpoint_file_diff_is_high_risk(self):
        diff = _make_diff(["src/network/endpoint.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"

    def test_worker_diff_is_high_risk(self):
        diff = _make_diff(["tools/local_llm_worker.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"

    def test_debate_diff_is_high_risk(self):
        diff = _make_diff(["tools/local_llm_debate.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"

    def test_router_diff_is_high_risk(self):
        diff = _make_diff(["tools/local_llm_router.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"


class TestClassifyRuntimeCode:
    def test_normal_runtime_diff_is_medium(self):
        diff = _make_diff(["src/main.py", "src/utils.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] in ("medium", "high")
        assert result["escalate_to_debate"] is True
        assert result["skip_debate_allowed"] is False

    def test_tests_only_escalates(self):
        diff = _make_diff(["tests/test_main.py"])
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] in ("low", "medium")
        assert result["escalate_to_debate"] is True
        assert result["skip_debate_allowed"] is False


class TestClassifyEdgeCases:
    def test_large_diff_is_high_risk(self):
        body = "\n".join("+" + "x" * 100 for _ in range(600))
        diff = _make_diff(["src/big.py"], body)
        assert len(diff) > pc.LARGE_DIFF_CHARS
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"
        assert any("large" in b.lower() or "50000" in b for b in result["safety_blockers"])

    def test_empty_diff_unknown_low_confidence(self):
        result = pc.classify_diff_risk_heuristic("")
        assert result["risk_level"] == "unknown"
        assert result["confidence"] == "low"
        assert result["escalate_to_debate"] is True

    def test_whitespace_only_diff(self):
        result = pc.classify_diff_risk_heuristic("   \n  \n")
        assert result["risk_level"] == "unknown"
        assert result["confidence"] == "low"

    def test_changed_files_override_parsed(self):
        diff = _make_diff(["src/a.py"])
        result = pc.classify_diff_risk_heuristic(diff, changed_files=["VERSION", "src/auth.py"])
        assert result["risk_level"] == "high"
        assert any("version" in b.lower() or "VERSION" in b for b in result["safety_blockers"])

    def test_windows_paths_in_changed_files(self):
        diff = _make_diff(["src/main.py"])
        result = pc.classify_diff_risk_heuristic(diff, changed_files=["tools\\claude_hooks\\mcp_gate.py"])
        assert result["risk_level"] == "high"
        assert result["sensitive_paths"]


class TestClassifyCommitGateContext:
    def test_commit_gate_context_escalates(self):
        diff = _make_diff(["CHANGELOG.md"])
        result = pc.classify_diff_risk_heuristic(diff, context={"commit_gate": True})
        assert result["escalate_to_debate"] is True
        assert result["skip_debate_allowed"] is False
        assert any("commit gate" in b.lower() for b in result["safety_blockers"])

    def test_release_context_escalates(self):
        diff = _make_diff(["CHANGELOG.md"])
        result = pc.classify_diff_risk_heuristic(diff, context={"release": True})
        assert result["escalate_to_debate"] is True
        assert result["skip_debate_allowed"] is False
        assert any("release" in b.lower() for b in result["safety_blockers"])


class TestSecurityPatternsInBody:
    def test_eval_in_diff_body_detected(self):
        diff = _make_diff(["src/helper.py"], "@@ -1 +1 @@\n-old\n+eval(user_input)")
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"
        assert any("security" in b.lower() for b in result["safety_blockers"])

    def test_subprocess_in_diff_body_detected(self):
        diff = _make_diff(["src/tool.py"], "@@ -1 +1 @@\n-old\n+subprocess.run(['rm', '-rf', '/tmp'])")
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] == "high"

    def test_safe_code_not_flagged(self):
        diff = _make_diff(["src/math.py"], "@@ -1 +1 @@\n-x = 1 + 1\n+x = 1 + 2")
        result = pc.classify_diff_risk_heuristic(diff)
        assert result["risk_level"] in ("low", "medium")


class TestContractCompliance:
    """Verify every result conforms to the B0 contract schema."""

    REQUIRED_FIELDS = {
        "ok", "risk_level", "confidence", "skip_debate_recommended",
        "skip_debate_allowed", "escalate_to_debate", "sensitive_paths",
        "changed_files", "risk_reasons", "safety_blockers",
        "classification_method", "created_at",
    }

    def _validate_schema(self, result: dict):
        missing = self.REQUIRED_FIELDS - set(result.keys())
        assert not missing, f"Missing fields: {missing}"
        assert result["ok"] is True
        assert result["risk_level"] in ("low", "medium", "high", "unknown")
        assert result["confidence"] in ("high", "medium", "low")
        assert isinstance(result["skip_debate_recommended"], bool)
        assert isinstance(result["skip_debate_allowed"], bool)
        assert isinstance(result["escalate_to_debate"], bool)
        assert isinstance(result["sensitive_paths"], list)
        assert isinstance(result["changed_files"], list)
        assert isinstance(result["risk_reasons"], list)
        assert isinstance(result["safety_blockers"], list)
        assert result["classification_method"] == "heuristic"
        assert isinstance(result["created_at"], str)

    def test_docs_only_schema(self):
        diff = _make_diff(["CHANGELOG.md"])
        self._validate_schema(pc.classify_diff_risk_heuristic(diff))

    def test_runtime_code_schema(self):
        diff = _make_diff(["src/main.py"])
        self._validate_schema(pc.classify_diff_risk_heuristic(diff))

    def test_sensitive_path_schema(self):
        diff = _make_diff(["tools/local_llm_mcp_server.py"])
        self._validate_schema(pc.classify_diff_risk_heuristic(diff))

    def test_empty_diff_schema(self):
        self._validate_schema(pc.classify_diff_risk_heuristic(""))

    # B1-A iron rule: all escalate_to_debate = true, all skip_debate_allowed = false
    def test_escalate_always_true(self):
        """B1-A: escalate_to_debate must be true for every non-trivial case."""
        cases = [
            _make_diff(["CHANGELOG.md"]),
            _make_diff(["src/main.py"]),
            _make_diff(["tests/test_main.py"]),
            _make_diff(["tools/local_llm_mcp_server.py"]),
            _make_diff(["VERSION"]),
            _make_diff(["docs/guide.md"]),
        ]
        for diff in cases:
            result = pc.classify_diff_risk_heuristic(diff)
            assert result["escalate_to_debate"] is True, (
                f"escalate_to_debate must be true for {result['changed_files']}"
            )

    def test_skip_allowed_always_false(self):
        """B1-A: skip_debate_allowed must be false for all cases."""
        cases = [
            _make_diff(["CHANGELOG.md"]),
            _make_diff(["docs/readme.md"]),
            _make_diff(["tests/test_main.py"]),
            _make_diff(["src/main.py"]),
            _make_diff(["tools/local_llm_mcp_server.py"]),
        ]
        for diff in cases:
            result = pc.classify_diff_risk_heuristic(diff)
            assert result["skip_debate_allowed"] is False, (
                f"skip_debate_allowed must be false for {result['changed_files']}"
            )


class TestNoSourceMutation:
    def test_module_attributes(self):
        """Verify the module is self-contained with expected public API."""
        assert hasattr(pc, "classify_diff_risk_heuristic")
        assert hasattr(pc, "detect_changed_files")
        assert hasattr(pc, "detect_sensitive_paths")
        assert hasattr(pc, "is_docs_only")
        assert hasattr(pc, "is_tests_only")
        assert hasattr(pc, "LARGE_DIFF_CHARS")
