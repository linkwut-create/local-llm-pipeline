"""Tests for tools/task_bootstrap.py — read-only task context bootstrapper."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(SCRIPT_DIR))

import task_bootstrap as TB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_file(path: str, role: str = "source", size: int = 1000,
               entrypoint: bool = False, subsystem: str = "source",
               risk_tags: list | None = None) -> dict:
    return {
        "path": path,
        "role": role,
        "subsystem": subsystem,
        "risk_tags": risk_tags or [],
        "entrypoint": entrypoint,
        "size": size,
        "mtime_ns": 0,
    }


@pytest.fixture
def sample_files():
    return [
        _make_file("CLAUDE.md", role="claude_instructions", size=5000),
        _make_file("AGENTS.md", role="claude_instructions", size=3000),
        _make_file("README.md", role="readme", size=2000),
        _make_file("app.py", role="source", size=50000, entrypoint=True),
        _make_file("services/tm.py", role="source", size=30000, entrypoint=True),
        _make_file("services/subtitle.py", role="source", size=15000),
        _make_file("tools/worker.py", role="worker", size=8000),
        _make_file("tests/test_app.py", role="test", size=5000, entrypoint=True),
        _make_file("tests/test_tm.py", role="test", size=4000),
        _make_file("data/config.json", role="config", size=500),
        _make_file("RELEASE_NOTES.md", role="unknown", size=6000),
    ]


@pytest.fixture
def sample_repo_map(sample_files):
    return {
        "ok": True,
        "summary": {
            "total_files": 11,
            "source_files": 3,
            "test_files": 2,
            "docs_files": 3,
            "config_files": 1,
        },
        "files": sample_files,
        "subsystems": {
            "source": {"key_files": ["app.py", "services/tm.py"], "file_count": 4},
            "docs": {"key_files": [], "file_count": 3},
            "tests": {"key_files": [], "file_count": 2},
            "config": {"key_files": [], "file_count": 1},
        },
        "skipped_files": [],
        "test_mapping": {},
        "risk_tags_legend": {},
    }


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir(exist_ok=True)
        (root / "CLAUDE.md").write_text("# test project")
        (root / "README.md").write_text("# readme")
        (root / "app.py").write_text("x" * 1000)
        yield root


# ---------------------------------------------------------------------------
# Instruction file selection
# ---------------------------------------------------------------------------

class TestInstructionFileSelection:
    def test_selects_claude_and_agents_first(self, sample_files):
        result = TB._select_instruction_files(sample_files)
        paths = [r["path"] for r in result]
        assert paths[0] in ("AGENTS.md", "CLAUDE.md")
        assert paths[1] in ("AGENTS.md", "CLAUDE.md")
        assert paths[0] != paths[1]

    def test_selects_readme(self, sample_files):
        result = TB._select_instruction_files(sample_files)
        paths = [r["path"] for r in result]
        assert "README.md" in paths

    def test_returns_empty_when_no_instruction_files(self):
        files = [_make_file("src/main.py", role="source")]
        result = TB._select_instruction_files(files)
        assert result == []

    def test_no_duplicates(self):
        files = [
            _make_file("CLAUDE.md", role="claude_instructions"),
            _make_file("CLAUDE.md", role="claude_instructions"),
        ]
        result = TB._select_instruction_files(files)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Summary candidate selection
# ---------------------------------------------------------------------------

class TestSummaryCandidateSelection:
    def test_prioritizes_entrypoints(self, sample_files):
        selected = TB._select_summary_candidates(sample_files, "", 2)
        reasons = [s["selection_reason"] for s in selected]
        assert reasons[0] == "entrypoint"
        assert reasons[1] == "entrypoint"

    def test_respects_max_summaries(self, sample_files):
        selected = TB._select_summary_candidates(sample_files, "", 1)
        assert len(selected) == 1

    def test_excludes_tests_by_default(self, sample_files):
        selected = TB._select_summary_candidates(sample_files, "", 10)
        paths = [s["path"] for s in selected]
        assert "tests/test_app.py" not in paths
        assert "tests/test_tm.py" not in paths

    def test_includes_tests_when_task_mentions_tests(self, sample_files):
        selected = TB._select_summary_candidates(
            sample_files, "fix the test failures", 10,
        )
        paths = [s["path"] for s in selected]
        assert "tests/test_app.py" in paths

    def test_zero_max_summaries_returns_empty(self, sample_files):
        selected = TB._select_summary_candidates(sample_files, "", 0)
        assert selected == []

    def test_task_keyword_boosts_matches(self, sample_files):
        selected = TB._select_summary_candidates(
            sample_files, "improve subtitle processing", 5,
        )
        paths = [s["path"] for s in selected]
        assert "services/subtitle.py" in paths

    def test_no_duplicates_across_priorities(self, sample_files):
        selected = TB._select_summary_candidates(sample_files, "", 10)
        paths = [s["path"] for s in selected]
        assert len(paths) == len(set(paths))


# ---------------------------------------------------------------------------
# Task keyword extraction
# ---------------------------------------------------------------------------

class TestTaskKeywords:
    def test_extracts_words(self):
        kw = TB._task_keywords("fix translation memory bug")
        assert "translation" in kw
        assert "memory" in kw
        assert "fix" in kw

    def test_filters_stop_words(self):
        kw = TB._task_keywords("the and for with that this")
        assert kw == set()

    def test_empty_task_returns_empty(self):
        assert TB._task_keywords("") == set()
        assert TB._task_keywords(None) == set()

    def test_min_length_filter(self):
        kw = TB._task_keywords("a bb ccc")
        assert "ccc" in kw
        assert "a" not in kw
        assert "bb" not in kw


class TestTaskMentionsTests:
    def test_detects_test_keywords(self):
        assert TB._task_mentions_tests("fix the failing tests")
        assert TB._task_mentions_tests("add pytest coverage")
        assert TB._task_mentions_tests("testing the new endpoint")

    def test_no_false_positives(self):
        assert not TB._task_mentions_tests("")
        assert not TB._task_mentions_tests("add translation feature")
        assert not TB._task_mentions_tests(None)


# ---------------------------------------------------------------------------
# Risk hints
# ---------------------------------------------------------------------------

class TestRiskHints:
    def test_detects_security_tags(self, sample_repo_map):
        files = sample_repo_map["files"]
        files.append(_make_file("secrets.py", risk_tags=["security"]))
        hints = TB._build_risk_hints(sample_repo_map)
        assert any("security" in h for h in hints)

    def test_detects_large_entrypoints(self):
        rm = {
            "files": [
                _make_file("app.py", size=80000, entrypoint=True),
            ],
        }
        hints = TB._build_risk_hints(rm)
        assert any("large entrypoint" in h for h in hints)

    def test_no_hints_for_normal_project(self, sample_repo_map):
        hints = TB._build_risk_hints(sample_repo_map)
        # No security tags, no huge entrypoints in sample
        assert not any("security" in h for h in hints)


# ---------------------------------------------------------------------------
# What NOT to read
# ---------------------------------------------------------------------------

class TestWhatNotToRead:
    def test_defers_tests_when_test_count_high(self):
        rm = {
            "summary": {"test_files": 25, "config_files": 10},
            "files": [_make_file(f"test/test_{i}.py", role="test") for i in range(25)],
        }
        items = TB._build_what_not_to_read(rm, [], [])
        assert any("test" in i.lower() for i in items)

    def test_defers_many_config_files(self):
        rm = {
            "summary": {"test_files": 2, "config_files": 200},
            "files": [_make_file(f"cfg/{i}.json", role="config") for i in range(200)],
        }
        items = TB._build_what_not_to_read(rm, [], [])
        assert any("config" in i for i in items)

    def test_includes_release_notes_hint(self):
        rm = {
            "summary": {"test_files": 0, "config_files": 0},
            "files": [
                _make_file("RELEASE_NOTES_v1.md", role="unknown", size=5000),
                _make_file("RELEASE_NOTES_v2.md", role="unknown", size=5000),
                _make_file("CHANGELOG.md", role="unknown", size=5000),
            ],
        }
        items = TB._build_what_not_to_read(rm, [], [])
        assert any("release note" in i for i in items)


# ---------------------------------------------------------------------------
# Suggested next calls
# ---------------------------------------------------------------------------

class TestSuggestedCalls:
    def test_includes_summarize_for_selected(self):
        selected = [
            {"path": "app.py", "role": "source", "size": 5000,
             "selection_reason": "entrypoint"},
        ]
        calls = TB._build_suggested_calls(selected, "/tmp/proj")
        assert any("summarize-file" in c and "app.py" in c for c in calls)

    def test_includes_test_plan_for_source_files(self):
        selected = [
            {"path": "app.py", "role": "source", "size": 5000,
             "selection_reason": "entrypoint"},
        ]
        calls = TB._build_suggested_calls(selected, "/tmp/proj")
        assert any("generate-test-plan" in c for c in calls)

    def test_includes_review_diff_suggestion(self):
        calls = TB._build_suggested_calls([], "/tmp/proj")
        assert any("review-diff" in c for c in calls)


# ---------------------------------------------------------------------------
# Context budget
# ---------------------------------------------------------------------------

class TestContextBudget:
    def test_includes_all_fields(self):
        rm = {"files": [_make_file("a.py", size=4000)]}
        budget = TB._build_context_budget(rm, [], 6000)
        assert "budget_limit" in budget
        assert "estimated_tokens" in budget
        assert "repo_map_tokens" in budget
        assert "summaries_tokens" in budget
        assert budget["budget_limit"] == 6000


# ---------------------------------------------------------------------------
# CLI exit codes (mocked)
# ---------------------------------------------------------------------------

class TestCLIExitCodes:
    def test_missing_project_exit_2(self):
        with patch("sys.argv", ["task_bootstrap.py", "--project", "/nonexistent/xyz"]):
            rc = TB.main()
            assert rc == 2

    def test_project_not_a_directory_exit_2(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("not a dir")
        with patch("sys.argv", ["task_bootstrap.py", "--project", str(f)]):
            rc = TB.main()
            assert rc == 2

    def test_repo_map_failure_exit_1(self, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        with patch("sys.argv", ["task_bootstrap.py", "--project", str(tmp_path)]):
            with patch("task_bootstrap.build_repo_map",
                       return_value={"ok": False, "error": "mock failure"}):
                rc = TB.main()
                assert rc == 1

    def test_no_summaries_exit_0(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        with patch("sys.argv", [
            "task_bootstrap.py", "--project", str(tmp_path), "--no-summaries",
        ]):
            with patch("task_bootstrap.build_repo_map",
                       return_value=sample_repo_map):
                rc = TB.main()
                assert rc == 0

    def test_dry_run_exit_0(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        with patch("sys.argv", [
            "task_bootstrap.py", "--project", str(tmp_path), "--dry-run",
        ]):
            with patch("task_bootstrap.build_repo_map",
                       return_value=sample_repo_map):
                rc = TB.main()
                assert rc == 0

    def test_success_exit_0(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        with patch("sys.argv", [
            "task_bootstrap.py", "--project", str(tmp_path), "--no-summaries",
        ]):
            with patch("task_bootstrap.build_repo_map",
                       return_value=sample_repo_map):
                rc = TB.main()
                assert rc == 0


# ---------------------------------------------------------------------------
# Advisory boundary
# ---------------------------------------------------------------------------

class TestAdvisoryBoundary:
    def test_json_includes_advisory_only(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        out_dir = tmp_path / ".local_llm_out"
        out_dir.mkdir(exist_ok=True)
        with patch("sys.argv", [
            "task_bootstrap.py", "--project", str(tmp_path),
            "--no-summaries", "--out-dir", str(out_dir),
        ]):
            with patch("task_bootstrap.build_repo_map",
                       return_value=sample_repo_map):
                TB.main()
        json_files = list(out_dir.glob("*_bootstrap.json"))
        assert len(json_files) >= 1
        doc = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert doc.get("advisory_only") is True

    def test_no_writes_to_target_project(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        # Use an out-dir OUTSIDE the project to verify project is untouched
        out_dir = Path(tempfile.mkdtemp())
        try:
            before_project = set(
                p.relative_to(tmp_path) for p in tmp_path.rglob("*")
                if ".local_llm_out" not in str(p)
            )
            with patch("sys.argv", [
                "task_bootstrap.py", "--project", str(tmp_path),
                "--no-summaries", "--out-dir", str(out_dir),
            ]):
                with patch("task_bootstrap.build_repo_map",
                           return_value=sample_repo_map):
                    TB.main()
            after_project = set(
                p.relative_to(tmp_path) for p in tmp_path.rglob("*")
                if ".local_llm_out" not in str(p)
            )
            # Project files should be unchanged (no new files)
            assert after_project == before_project
            # Output files should be in out_dir
            assert len(list(out_dir.glob("*_bootstrap.md"))) >= 1
        finally:
            import shutil
            shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_markdown_contains_required_sections(self, sample_repo_map, sample_files):
        inst = TB._select_instruction_files(sample_files)
        selected = TB._select_summary_candidates(sample_files, "", 2)
        md = TB._build_markdown(
            "/tmp/proj", "test task",
            {"head": "abc123", "describe": "v1.0", "dirty": False},
            sample_repo_map, inst, selected,
            ["hint 1"], ["call 1"],
            {"budget_limit": 6000, "estimated_tokens": 3000,
             "repo_map_tokens": 2500, "summaries_tokens": 500},
            ["skip this"], [], dry_run=False,
        )
        assert "Task Bootstrap" in md
        assert "Repo Map Summary" in md
        assert "Read First" in md
        assert "Risk Hints" in md
        assert "Context Budget" in md
        assert "Suggested Next Calls" in md
        assert "What NOT to Read" in md
        assert "Advisory only" in md

    def test_dry_run_disclaimer_in_output(self, sample_repo_map, sample_files):
        inst = TB._select_instruction_files(sample_files)
        selected = TB._select_summary_candidates(sample_files, "", 1)
        budget = {"budget_limit": 6000, "estimated_tokens": 2500,
                  "repo_map_tokens": 2500, "summaries_tokens": 0}
        md = TB._build_markdown(
            "/tmp/proj", "", {"head": "abc", "describe": "", "dirty": False},
            sample_repo_map, inst, selected, [], [], budget,
            [], [], dry_run=True,
        )
        assert "dry-run" in md.lower()


# ---------------------------------------------------------------------------
# Output file writing
# ---------------------------------------------------------------------------

class TestOutputFileWriting:
    def test_writes_md_and_json(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        out_dir = tmp_path / ".local_llm_out"
        out_dir.mkdir(exist_ok=True)
        with patch("sys.argv", [
            "task_bootstrap.py", "--project", str(tmp_path),
            "--no-summaries", "--out-dir", str(out_dir),
        ]):
            with patch("task_bootstrap.build_repo_map",
                       return_value=sample_repo_map):
                TB.main()
        md_files = list(out_dir.glob("*_bootstrap.md"))
        json_files = list(out_dir.glob("*_bootstrap.json"))
        assert len(md_files) >= 1
        assert len(json_files) >= 1


# ---------------------------------------------------------------------------
# Budget-too-low behavior
# ---------------------------------------------------------------------------

class TestBudgetBehavior:
    def test_budget_passed_through_to_output(self, sample_repo_map, sample_files):
        inst = TB._select_instruction_files(sample_files)
        selected = []
        budget = TB._build_context_budget(sample_repo_map, [], 1000)
        assert budget["budget_limit"] == 1000


# ---------------------------------------------------------------------------
# Git info
# ---------------------------------------------------------------------------

class TestGitInfo:
    def test_returns_dict_with_keys(self, temp_project):
        info = TB._get_git_info(temp_project)
        assert "head" in info
        assert "describe" in info
        assert "dirty" in info

    def test_handles_non_git_directory(self, tmp_path):
        info = TB._get_git_info(tmp_path)
        assert info["head"] == ""
        assert info["describe"] == ""
