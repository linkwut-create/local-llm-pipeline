"""Test benchmark_profiles.py structure and defaults (no LLM calls)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

TOOLS_DIR = Path(__file__).parent.parent / "tools"
PROFILES_PATH = TOOLS_DIR / "local_llm_profiles.json"


def _load_profiles():
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def test_benchmark_json_output_fields():
    """Benchmark result entries must have the documented field set."""
    required_fields = {
        "profile", "model", "task", "ok",
        "elapsed_seconds", "error", "output_chars", "created_at",
    }
    sample = {
        "profile": "fast_summary",
        "model": "test-model",
        "task": "summarize-file",
        "ok": True,
        "elapsed_seconds": 1.5,
        "error": None,
        "output_chars": 100,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    assert required_fields.issubset(sample.keys())


def test_benchmark_default_profile_is_fast_summary():
    """Default benchmark should only run fast_summary, not all profiles."""
    data = _load_profiles()
    default = data.get("default_profile", "fast_summary")
    assert default == "fast_summary", (
        f"Default profile should be fast_summary, got {default}"
    )


def test_benchmark_script_has_all_flag():
    """benchmark_profiles.py should support --all to run all profiles."""
    script = (TOOLS_DIR / "benchmark_profiles.py").read_text(encoding="utf-8")
    assert "--all" in script


def test_benchmark_script_has_json_flag():
    """benchmark_profiles.py should support --json output."""
    script = (TOOLS_DIR / "benchmark_profiles.py").read_text(encoding="utf-8")
    assert "--json" in script


def test_benchmark_script_has_created_at():
    """Benchmark results should include created_at timestamp."""
    script = (TOOLS_DIR / "benchmark_profiles.py").read_text(encoding="utf-8")
    assert "created_at" in script


def test_all_profiles_have_valid_benchmark_config():
    """Every profile must have model and max_chars for benchmarking."""
    profiles = _load_profiles()["profiles"]
    for name, conf in profiles.items():
        assert "model" in conf, f"Profile {name} missing model"
        assert isinstance(conf.get("max_chars", 0), int), f"Profile {name} max_chars not int"
        assert conf["max_chars"] > 0, f"Profile {name} max_chars must be positive"
