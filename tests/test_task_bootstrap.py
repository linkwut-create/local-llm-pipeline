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
        # Slot allocation: entrypoint_slots=1, source_slots=1
        assert reasons[0] == "entrypoint"
        assert reasons[1] in ("entrypoint", "largest_source")

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

    def test_handles_non_git_directory(self, tmp_path, monkeypatch):
        # Simulate being outside a git repo by making git rev-parse fail
        import subprocess as _sp
        def _mock_check_output(cmd, **kwargs):
            if isinstance(cmd, list) and cmd[0] == "git" and "rev-parse" in cmd:
                raise _sp.CalledProcessError(128, cmd)
            return _sp.check_output(cmd, **kwargs)
        monkeypatch.setattr(_sp, "check_output", _mock_check_output)
        info = TB._get_git_info(tmp_path)
        assert info["head"] == ""
        assert info["describe"] == ""


# ---------------------------------------------------------------------------
# Fix 1: Vendor path detection
# ---------------------------------------------------------------------------

class TestVendorPathDetection:
    def test_flags_local_llm_tools(self):
        assert TB._looks_like_vendor_embedded("tools/local_llm_worker.py")
        assert TB._looks_like_vendor_embedded("tools/local_llm_mcp_server.py")
        assert TB._looks_like_vendor_embedded("tools/claude_hooks/mcp_gate.py")

    def test_flags_models_dir(self):
        assert TB._looks_like_vendor_embedded("models/faster-whisper/README.md")

    def test_flags_node_modules(self):
        assert TB._looks_like_vendor_embedded("node_modules/react/index.js")

    def test_flags_data_dir(self):
        assert TB._looks_like_vendor_embedded("data/jobs/sub_001.json")

    def test_does_not_flag_app_source(self):
        assert not TB._looks_like_vendor_embedded("app.py")
        assert not TB._looks_like_vendor_embedded("services/tm_service.py")
        assert not TB._looks_like_vendor_embedded("scripts/verify_env.py")

    def test_case_insensitive(self):
        assert TB._looks_like_vendor_embedded("Tools/Local_LLM_Worker.py")


# ---------------------------------------------------------------------------
# Fix 3: Instruction file depth filtering
# ---------------------------------------------------------------------------

class TestInstructionFileDepthFiltering:
    def test_root_readme_included(self):
        files = [_make_file("README.md", role="readme", size=2000)]
        result = TB._select_instruction_files(files)
        assert len(result) == 1

    def test_models_readme_excluded(self):
        files = [_make_file("models/faster-whisper/README.md", role="readme", size=1000)]
        result = TB._select_instruction_files(files)
        assert len(result) == 0

    def test_tools_readme_excluded(self):
        files = [_make_file("tools/README.md", role="readme", size=1000)]
        result = TB._select_instruction_files(files)
        assert len(result) == 0

    def test_data_readme_excluded(self):
        files = [_make_file("data/README.md", role="readme", size=1000)]
        result = TB._select_instruction_files(files)
        assert len(result) == 0

    def test_claude_md_included(self):
        files = [_make_file("CLAUDE.md", role="claude_instructions", size=5000)]
        result = TB._select_instruction_files(files)
        assert len(result) == 1

    def test_agents_md_included(self):
        files = [_make_file("AGENTS.md", role="claude_instructions", size=3000)]
        result = TB._select_instruction_files(files)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Fix 4: Task keyword expansion with synonyms
# ---------------------------------------------------------------------------

class TestTaskKeywordExpansion:
    def test_translation_expands_to_tm(self):
        kw = TB._task_keywords("translation memory architecture")
        assert "tm" in kw

    def test_subtitle_expands_to_srt(self):
        kw = TB._task_keywords("fix subtitle generation")
        assert "srt" in kw

    def test_realtime_expands_to_live(self):
        kw = TB._task_keywords("realtime streaming issue")
        assert "live" in kw or "streaming" in kw

    def test_ocr_expands_to_paddleocr(self):
        kw = TB._task_keywords("ocr image recognition")
        assert any(s in kw for s in ("paddleocr", "paddle", "image"))

    def test_glossary_expands_to_terms(self):
        kw = TB._task_keywords("glossary management")
        assert "terminology" in kw or "terms" in kw


# ---------------------------------------------------------------------------
# Fix 1+4: File selection with vendor filtering + task boost
# ---------------------------------------------------------------------------

class TestFileSelectionRefined:
    @pytest.fixture
    def translator_files(self):
        """Simulates local-translator-agent file structure."""
        return [
            _make_file("CLAUDE.md", role="claude_instructions", size=14000),
            _make_file("app.py", role="source", size=109000),
            _make_file("services/tm_service.py", role="source", size=70000),
            _make_file("services/subtitle_service.py", role="source", size=11000),
            _make_file("services/realtime_service.py", role="source", size=26000),
            _make_file("prompts.py", role="source", size=15000),
            _make_file("tools/local_llm_worker.py", role="worker", size=42000,
                       entrypoint=True),
            _make_file("tools/local_llm_mcp_server.py", role="mcp_server", size=36000,
                       entrypoint=True),
            _make_file("tools/local_llm_debate.py", role="debate", size=18000,
                       entrypoint=True),
            _make_file("tools/run_checks.py", role="source", size=8000,
                       entrypoint=True),
            _make_file("scripts/smoke_tm_ollama.py", role="source", size=15000,
                       entrypoint=True),
            _make_file("tests/test_tm.py", role="test", size=5000, entrypoint=True),
        ]

    def test_app_py_selected_as_largest_source(self, translator_files):
        selected = TB._select_summary_candidates(translator_files, "", 3)
        paths = [s["path"] for s in selected]
        assert "app.py" in paths

    def test_vendor_entrypoints_not_selected(self, translator_files):
        selected = TB._select_summary_candidates(translator_files, "", 3)
        paths = [s["path"] for s in selected]
        assert "tools/local_llm_worker.py" not in paths
        assert "tools/local_llm_mcp_server.py" not in paths

    def test_task_keyword_boosts_tm_service(self, translator_files):
        selected = TB._select_summary_candidates(
            translator_files, "translation memory architecture", 5,
        )
        paths = [s["path"] for s in selected]
        assert "services/tm_service.py" in paths

    def test_task_keyword_boosts_subtitle_service(self, translator_files):
        selected = TB._select_summary_candidates(
            translator_files, "fix subtitle generation bug", 5,
        )
        paths = [s["path"] for s in selected]
        assert "services/subtitle_service.py" in paths

    def test_non_vendor_run_checks_still_entrypoint(self, translator_files):
        selected = TB._select_summary_candidates(translator_files, "", 5)
        paths = [s["path"] for s in selected]
        assert "tools/run_checks.py" in paths

    def test_tests_excluded_by_default(self, translator_files):
        selected = TB._select_summary_candidates(translator_files, "", 10)
        paths = [s["path"] for s in selected]
        assert "tests/test_tm.py" not in paths


# ---------------------------------------------------------------------------
# Fix 2: Summary extraction (mocked router)
# ---------------------------------------------------------------------------

class TestSummaryExtraction:
    def test_reads_markdown_file_via_absolute_path(self, tmp_path):
        """_run_summary reads markdown file via absolute path in stderr."""
        out_dir = tmp_path / ".local_llm_out"
        out_dir.mkdir(exist_ok=True)
        md_file = out_dir / "test_summary.md"
        md_content = "# Summary\n\nThis is the actual summary from file."
        md_file.write_text(md_content, encoding="utf-8")

        src = tmp_path / "src.py"
        src.parent.mkdir(exist_ok=True)
        src.write_text("def foo(): pass", encoding="utf-8")

        # Call with the actual subprocess.run mocked to return a path
        # that point to a real file.
        with patch("task_bootstrap.subprocess.run") as mock_run:
            MockResult = type("MockResult", (), {})
            r = MockResult()
            r.returncode = 0
            r.stdout = ""
            r.stderr = f"OK: done\nMD: {str(md_file)}\n"
            mock_run.return_value = r
            result = TB._run_summary(str(src))

        assert result["ok"] is True, f"Expected ok=True, got {result}"
        assert "actual summary" in result["summary"], \
            f"Summary should contain file content, got: {result['summary'][:200]}"

        assert result["ok"] is True
        assert "actual summary" in result["summary"]

    def test_missing_summary_file_returns_failed(self, tmp_path):
        file_to_summarize = tmp_path / "src.py"
        file_to_summarize.parent.mkdir(exist_ok=True)
        file_to_summarize.write_text("def foo(): pass", encoding="utf-8")

        with patch("task_bootstrap.subprocess.run") as mock_run:
            mock_result = type("Result", (), {
                "returncode": 0,
                "stdout": "",
                "stderr": "OK: done\\nMD: /nonexistent/path.md\\n",
            })()
            mock_run.return_value = mock_result
            result = TB._run_summary(str(file_to_summarize))

        assert result["ok"] is False
        assert "not readable" in result.get("error", "")

    def test_router_stderr_not_stored_as_summary(self, tmp_path):
        file_to_summarize = tmp_path / "src.py"
        file_to_summarize.parent.mkdir(exist_ok=True)
        file_to_summarize.write_text("def foo(): pass", encoding="utf-8")

        with patch("task_bootstrap.subprocess.run") as mock_run:
            mock_result = type("Result", (), {
                "returncode": 0,
                "stdout": "",
                "stderr": "Router: task=summarize-file\\nOK: summarize-file completed\\n",
            })()
            mock_run.return_value = mock_result
            result = TB._run_summary(str(file_to_summarize))

        # No MD line, so no output_path, summary should be empty → fails
        assert result["ok"] is False
        assert "Router:" not in result.get("summary", "")


# ---------------------------------------------------------------------------
# Regression: boundaries unchanged
# ---------------------------------------------------------------------------

class TestRegressionBoundaries:
    def test_dry_run_no_router_call(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        with patch("sys.argv", [
            "task_bootstrap.py", "--project", str(tmp_path), "--dry-run",
        ]):
            with patch("task_bootstrap.build_repo_map",
                       return_value=sample_repo_map):
                with patch("task_bootstrap._run_summary") as mock_run:
                    TB.main()
                    mock_run.assert_not_called()

    def test_no_summaries_no_router_call(self, sample_repo_map, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)
        with patch("sys.argv", [
            "task_bootstrap.py", "--project", str(tmp_path), "--no-summaries",
        ]):
            with patch("task_bootstrap.build_repo_map",
                       return_value=sample_repo_map):
                with patch("task_bootstrap._run_summary") as mock_run:
                    TB.main()
                    mock_run.assert_not_called()

    def test_json_output_includes_advisory_only(self, sample_repo_map, tmp_path):
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
        doc = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert doc.get("advisory_only") is True

    def test_instruction_files_not_counted_against_max_summaries(self, tmp_path):
        """When max_summaries=1, instruction files should not take a slot."""
        files = [
            _make_file("CLAUDE.md", role="claude_instructions", size=5000),
            _make_file("README.md", role="readme", size=2000),
            _make_file("app.py", role="source", size=50000, entrypoint=False),
            _make_file("services/tm.py", role="source", size=30000),
        ]
        inst = TB._select_instruction_files(files)
        selected = TB._select_summary_candidates(files, "", 1)
        assert len(inst) == 2
        assert len(selected) == 1


# ---------------------------------------------------------------------------
# F-J: Slot allocation
# ---------------------------------------------------------------------------

class TestSlotAllocation:
    @pytest.fixture
    def many_entrypoints(self):
        return [
            _make_file("scripts/smoke.py", role="source", size=15000,
                       entrypoint=True),
            _make_file("scripts/rebuild.py", role="source", size=10000,
                       entrypoint=True),
            _make_file("tools/bench.py", role="source", size=13000,
                       entrypoint=True),
            _make_file("tools/validate.py", role="source", size=8000,
                       entrypoint=True),
            _make_file("tools/run_checks.py", role="source", size=8000,
                       entrypoint=True),
            _make_file("app.py", role="source", size=100000, entrypoint=False),
            _make_file("services/tm.py", role="source", size=70000,
                       entrypoint=False),
        ]

    def test_entrypoints_do_not_fill_all_slots(self, many_entrypoints):
        selected = TB._select_summary_candidates(many_entrypoints, "", 5)
        reasons = [s["selection_reason"] for s in selected]
        assert "entrypoint" in reasons
        assert "largest_source" in reasons

    def test_app_py_selected_as_largest_source(self, many_entrypoints):
        selected = TB._select_summary_candidates(many_entrypoints, "", 5)
        paths = [s["path"] for s in selected]
        assert "app.py" in paths

    def test_scripts_do_not_monopolize(self, many_entrypoints):
        selected = TB._select_summary_candidates(many_entrypoints, "", 5)
        paths = [s["path"] for s in selected]
        script_count = sum(1 for p in paths if p.startswith("scripts/"))
        assert script_count < len(paths)

    def test_task_keyword_gets_slot(self, many_entrypoints):
        selected = TB._select_summary_candidates(
            many_entrypoints, "translation memory", 5,
        )
        paths = [s["path"] for s in selected]
        assert "services/tm.py" in paths


# ---------------------------------------------------------------------------
# F-J: Application core boost
# ---------------------------------------------------------------------------

class TestApplicationCoreBoost:
    def test_app_py_boosted_in_largest_source(self):
        files = [
            _make_file("scripts/util.py", role="source", size=20000,
                       entrypoint=False),
            _make_file("app.py", role="source", size=10000, entrypoint=False),
            _make_file("tools/helper.py", role="source", size=30000,
                       entrypoint=False),
        ]
        selected = TB._select_summary_candidates(files, "", 2)
        paths = [s["path"] for s in selected]
        # app.py should be first due to application core boost despite smaller size
        assert paths[0] == "app.py"

    def test_services_path_boosted_in_task_match(self):
        files = [
            _make_file("scripts/tm_helper.py", role="source", size=5000,
                       entrypoint=False),
            _make_file("services/tm_service.py", role="source", size=30000,
                       entrypoint=False),
        ]
        selected = TB._select_summary_candidates(
            files, "translation memory", 3,
        )
        paths = [s["path"] for s in selected]
        assert "services/tm_service.py" in paths


# ---------------------------------------------------------------------------
# F-J: JSON path summary extraction
# ---------------------------------------------------------------------------

class TestJSONPathSummary:
    def test_json_path_derives_md_path(self, tmp_path):
        out_dir = tmp_path / ".local_llm_out"
        out_dir.mkdir(exist_ok=True)
        md_file = out_dir / "test_summary.md"
        md_content = "# Summary\n\nCache-hit summary content."
        md_file.write_text(md_content, encoding="utf-8")

        json_file = out_dir / "test_summary.json"
        json_file.write_text("{}", encoding="utf-8")

        src = tmp_path / "src.py"
        src.parent.mkdir(exist_ok=True)
        src.write_text("def foo(): pass", encoding="utf-8")

        with patch("task_bootstrap.subprocess.run") as mock_run:
            MockResult = type("MockResult", (), {})
            r = MockResult()
            r.returncode = 0
            r.stdout = ""
            r.stderr = f"OK (cache hit): done\nJSON: {json_file}\n"
            mock_run.return_value = r
            result = TB._run_summary(str(src))

        assert result["ok"] is True, f"Expected ok=True, got {result}"
        assert "Cache-hit" in result["summary"], \
            f"Expected cache-hit content, got: {result['summary'][:200]}"

    def test_json_without_corresponding_md_fails(self, tmp_path):
        src = tmp_path / "src.py"
        src.parent.mkdir(exist_ok=True)
        src.write_text("def foo(): pass", encoding="utf-8")

        with patch("task_bootstrap.subprocess.run") as mock_run:
            MockResult = type("MockResult", (), {})
            r = MockResult()
            r.returncode = 0
            r.stdout = ""
            r.stderr = "OK (cache hit): done\nJSON: /tmp/nonexistent.json\n"
            mock_run.return_value = r
            result = TB._run_summary(str(src))

        assert result["ok"] is False
        assert "not readable" in result.get("error", "")

    def test_parses_paths_from_stdout(self, tmp_path):
        """MD path on stdout should be parsed (not just stderr)."""
        out_dir = tmp_path / ".local_llm_out"
        out_dir.mkdir(exist_ok=True)
        md_file = out_dir / "test.md"
        md_file.write_text("# Summary from stdout", encoding="utf-8")

        src = tmp_path / "src.py"
        src.parent.mkdir(exist_ok=True)
        src.write_text("def foo(): pass", encoding="utf-8")

        with patch("task_bootstrap.subprocess.run") as mock_run:
            MockResult = type("MockResult", (), {})
            r = MockResult()
            r.returncode = 0
            r.stdout = f"JSON: {out_dir / 'test.json'}\nMD: {md_file}\n"
            r.stderr = "Router: task=summarize-file\nOK: done\n"
            mock_run.return_value = r
            result = TB._run_summary(str(src))

        assert result["ok"] is True
        assert "Summary from stdout" in result["summary"]

    def test_json_path_from_stdout_derives_md(self, tmp_path):
        """JSON-only on stdout (cache hit) still derives and reads MD."""
        out_dir = tmp_path / ".local_llm_out"
        out_dir.mkdir(exist_ok=True)
        md_file = out_dir / "cached_summary.md"
        md_file.write_text("# Cached content works", encoding="utf-8")

        src = tmp_path / "src.py"
        src.parent.mkdir(exist_ok=True)
        src.write_text("def foo(): pass", encoding="utf-8")

        with patch("task_bootstrap.subprocess.run") as mock_run:
            MockResult = type("MockResult", (), {})
            r = MockResult()
            r.returncode = 0
            r.stdout = f"JSON: {out_dir / 'cached_summary.json'}\n"
            r.stderr = "Router: ...\nOK (cache hit): done\n"
            mock_run.return_value = r
            result = TB._run_summary(str(src))

        assert result["ok"] is True
        assert "Cached content" in result["summary"]

    def test_md_preferred_over_json_when_both_present(self, tmp_path):
        out_dir = tmp_path / ".local_llm_out"
        out_dir.mkdir(exist_ok=True)
        md_file = out_dir / "real.md"
        md_file.write_text("# MD content", encoding="utf-8")
        json_file = out_dir / "derived.json"
        json_file.write_text("{}", encoding="utf-8")

        src = tmp_path / "src.py"
        src.parent.mkdir(exist_ok=True)
        src.write_text("def foo(): pass", encoding="utf-8")

        with patch("task_bootstrap.subprocess.run") as mock_run:
            MockResult = type("MockResult", (), {})
            r = MockResult()
            r.returncode = 0
            r.stdout = ""
            r.stderr = f"OK: done\nMD: {md_file}\nJSON: {json_file}\n"
            mock_run.return_value = r
            result = TB._run_summary(str(src))

        assert result["ok"] is True
        assert "MD content" in result["summary"]
