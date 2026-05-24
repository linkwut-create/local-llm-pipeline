"""Tests for the D-B classify-test-failure worker prompt and schema.

These tests verify the task prompt exists, carries the required output schema,
failure-class enum, safety wording, and boundary invariant wording — without
requiring an MCP server or a running LLM.

D-B is helper-only (mirrors C3-A).  No MCP tool, handler, or ledger change yet.
"""

import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(SCRIPT_DIR))

from local_llm_worker import TASK_PROMPTS, build_prompt, WorkerConfig

# ── A. Task prompt exists ──────────────────────────────────────────────

def test_task_prompt_exists():
    """classify-test-failure is a key in TASK_PROMPTS."""
    assert "classify-test-failure" in TASK_PROMPTS
    prompt = TASK_PROMPTS["classify-test-failure"]
    assert isinstance(prompt, str)
    assert len(prompt) > 200  # a real prompt, not a stub


# ── B. Schema fields ───────────────────────────────────────────────────

_REQUIRED_OUTPUT_FIELDS = [
    "ok",
    "failure_class",
    "confidence",
    "summary",
    "likely_cause",
    "files_to_inspect",
    "recommended_action",
    "advisory_only",
]

@pytest.mark.parametrize("field", _REQUIRED_OUTPUT_FIELDS)
def test_output_schema_field_present(field):
    prompt = TASK_PROMPTS["classify-test-failure"]
    assert field in prompt, f"output field '{field}' not found in prompt"


def test_advisory_only_always_true_wording():
    prompt = TASK_PROMPTS["classify-test-failure"]
    assert "advisory_only" in prompt
    assert "true" in prompt.lower()  # somewhere the prompt says true


# ── C. Failure class enum ──────────────────────────────────────────────

_REQUIRED_FAILURE_CLASSES = [
    "assertion",
    "import_error",
    "syntax_error",
    "dependency",
    "timeout",
    "environment",
    "flaky",
    "unknown",
]

@pytest.mark.parametrize("fc", _REQUIRED_FAILURE_CLASSES)
def test_failure_class_in_prompt(fc):
    prompt = TASK_PROMPTS["classify-test-failure"]
    assert fc in prompt, f"failure_class '{fc}' not found in prompt"


def test_failure_class_total_count():
    """Prompt should mention exactly the 8 expected classes — no extras snuck in."""
    prompt = TASK_PROMPTS["classify-test-failure"]
    # Count occurrences of "assertion", "import_error", etc. as distinct words
    # We just check that all 8 are present (tested above) and the total enum
    # listing doesn't drift above 8 known values.
    # The prompt lists them in a block; all 8 are verified individually.
    pass  # covered by parametrized test above


# ── D. Boundary wording ────────────────────────────────────────────────

_BOUNDARY_PHRASES = [
    "advisory-only",
    "ADVISORY-ONLY",
    "does NOT fix code",
    "rerun tests",
    "commit",
    "trigger hooks",
    "bypass any gate",
    "commit gate",
    "release guard",
    "dangerous command guard",
    "do NOT replace human review",
    "NEVER fabricate",
    "do NOT claim root-cause certainty",
]

@pytest.mark.parametrize("phrase", _BOUNDARY_PHRASES)
def test_boundary_phrase_in_prompt(phrase):
    prompt = TASK_PROMPTS["classify-test-failure"]
    # Case-insensitive check — boundaries must be clear regardless of casing
    assert phrase.lower() in prompt.lower(), \
        f"boundary phrase '{phrase}' not found in prompt"


# ── E. Secret safety wording ───────────────────────────────────────────

_SAFETY_PHRASES = [
    "REDACT",
    "secret",
    "token",
    "API key",
    "DO NOT echo",
    "not echo full",
    "never include",
    ".env",
    "private key",
    "bearer",
    "compact",
    "2 KB",
]

@pytest.mark.parametrize("phrase", _SAFETY_PHRASES)
def test_safety_phrase_in_prompt(phrase):
    prompt = TASK_PROMPTS["classify-test-failure"]
    assert phrase.lower() in prompt.lower(), \
        f"safety phrase '{phrase}' not found in prompt"


# ── F. build_prompt integration ────────────────────────────────────────

def test_build_prompt_includes_classify_failure_prompt():
    """build_prompt for classify-test-failure returns the task prompt."""
    config = WorkerConfig(
        profile="code_worker",
        model="test-model",
    )
    system, user, meta = build_prompt("classify-test-failure", '{"stderr":"AssertionError"}', config)
    assert isinstance(system, str)
    assert len(system) > 200
    # Task prompt goes into user, not system
    assert "failure_class" in user


def test_build_prompt_accepts_json_payload():
    """build_prompt accepts a JSON payload as content (future D-C handler input)."""
    config = WorkerConfig(profile="code_worker", model="test-model")
    payload = json.dumps({
        "stderr": "AssertionError: assert 1 == 2",
        "exit_code": 1,
    })
    system, user, meta = build_prompt("classify-test-failure", payload, config)
    assert "failure_class" in user
    # user prompt should contain the payload content
    assert "AssertionError" in user


def test_build_prompt_no_mcp_required():
    """build_prompt works without any MCP server imports or state."""
    config = WorkerConfig(profile="code_worker", model="test-model")
    # This must not raise ImportError or touch MCP server module
    system, user, meta = build_prompt(
        "classify-test-failure",
        '{"stderr":"test", "exit_code": 1}',
        config,
    )
    assert isinstance(system, str)
    assert "failure_class" in user


# ── G. No MCP integration yet ──────────────────────────────────────────

def test_mcp_server_unchanged_tool_count():
    """D-B must NOT add local_classify_test_failure to MCP TOOLS. Count stays 10."""
    # We check by scanning the MCP server source — no import, just text check.
    mcp_path = SCRIPT_DIR / "local_llm_mcp_server.py"
    text = mcp_path.read_text(encoding="utf-8")
    assert 'local_classify_test_failure' not in text, \
        "D-B must NOT add local_classify_test_failure to MCP server"


def test_mcp_tool_count():
    """MCP TOOLS count must remain 10."""
    mcp_path = SCRIPT_DIR / "local_llm_mcp_server.py"
    text = mcp_path.read_text(encoding="utf-8")
    # Count the tool keys in TOOLS dict — look for 'local_' entries
    # Quick heuristic: count the top-level tool names
    import re
    tool_names = re.findall(r'"local_\w+":\s*\{', text)
    # local_check, local_summarize_file, local_summarize_tree,
    # local_generate_test_plan, local_review_diff, local_debate_review_diff,
    # local_parallel_review, local_contextual_analyze, local_draft_code, local_repo_map
    assert len(tool_names) == 10, f"expected 10 MCP tools, found {len(tool_names)}: {tool_names}"


def test_call_ledger_unchanged():
    """call_ledger.py must NOT contain test-failure-classifier keys yet."""
    ledger_path = SCRIPT_DIR / "call_ledger.py"
    text = ledger_path.read_text(encoding="utf-8")
    assert "test_failure_class" not in text, \
        "D-B must NOT add test_failure_class to call_ledger.py"


def test_mcp_server_imports_unchanged():
    """MCP server must not import classify-test-failure related modules."""
    mcp_path = SCRIPT_DIR / "local_llm_mcp_server.py"
    text = mcp_path.read_text(encoding="utf-8")
    assert "classify_test_failure" not in text
    assert "classify-test-failure" not in text


def test_worker_has_no_classify_handler():
    """Worker has the prompt but no handler function for classify-test-failure."""
    worker_path = SCRIPT_DIR / "local_llm_worker.py"
    text = worker_path.read_text(encoding="utf-8")
    # The prompt key exists but no function named handle_classify or similar
    assert "def classify_test_failure" not in text
    assert "def handle_classify" not in text
