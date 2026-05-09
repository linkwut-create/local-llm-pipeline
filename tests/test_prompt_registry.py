"""Test local_llm_prompt_registry.py — prompt loading, validation, and safety."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from local_llm_prompt_registry import (
    load_prompt, list_prompts, compute_prompt_hash, validate_registry,
    Prompt,
)


def test_registry_loads():
    prompts = list_prompts()
    assert len(prompts) >= 18


def test_load_prompt_summarize_file():
    p = load_prompt("summarize-file")
    assert p is not None
    assert p.prompt_id == "summarize-file"
    assert p.version == "v1"
    assert len(p.hash) == 16
    assert "File purpose" in p.text


def test_load_prompt_review_diff():
    p = load_prompt("review-diff")
    assert p is not None
    assert "Candidate bugs" in p.text
    assert "Do NOT approve" in p.text


def test_load_prompt_draft_fix():
    p = load_prompt("draft-fix")
    assert p is not None
    assert "do not modify source files" in p.text.lower()


def test_load_prompt_draft_feature():
    p = load_prompt("draft-feature")
    assert "do not modify source files" in p.text.lower()


def test_load_prompt_draft_refactor():
    p = load_prompt("draft-refactor")
    assert "do not modify source files" in p.text.lower()


def test_load_prompt_suggest_improvements():
    p = load_prompt("suggest-improvements")
    assert "do not modify source files" in p.text.lower()


def test_load_prompt_missing():
    p = load_prompt("nonexistent-task-xyz")
    assert p is None


def test_prompt_hash_changes_with_content():
    text1 = "summarize this file"
    text2 = "summarize this file thoroughly"
    assert compute_prompt_hash(text1) != compute_prompt_hash(text2)


def test_validate_registry_passes():
    errors = validate_registry()
    assert len(errors) == 0, f"registry errors: {errors}"


def test_prompt_is_dataclass():
    p = Prompt("id", "v1", "abc123", "some text")
    assert p.prompt_id == "id"
    assert p.hash == "abc123"
    assert p.text == "some text"


def test_all_draft_prompts_have_safety_directive():
    for task in ["draft-fix", "draft-feature", "draft-refactor", "suggest-improvements"]:
        p = load_prompt(task)
        assert p is not None, f"prompt missing: {task}"
        assert "do not modify source files" in p.text.lower(), (
            f"{task} missing safety directive"
        )


def test_all_review_prompts_no_approve():
    for task in ["review-diff", "deep-code-review"]:
        p = load_prompt(task)
        assert "do not approve" in p.text.lower() or "do not approve" in p.text.lower()
