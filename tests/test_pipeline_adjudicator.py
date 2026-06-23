"""Tests for pipeline_adjudicator.py."""

import json, sys; sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / "tools"))
from pathlib import Path; import pipeline_adjudicator as pa


class TestValidateDecision:
    def test_valid(self):
        assert pa.validate_decision({"decision":"accept","reason":"ok"}) == []
    def test_missing_decision(self):
        assert any("decision" in e for e in pa.validate_decision({"reason":"x"}))
    def test_unknown(self):
        assert any("unknown" in e for e in pa.validate_decision({"decision":"bad","reason":"x"}))

class TestAdjudicate:
    def test_accept(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        r = pa.adjudicate("task-a", {"decision":"accept","reason":"ok"})
        assert r["ok"] and r["seq"] == 1
    def test_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        assert pa.adjudicate("task-c", {"decision":"garbage"})["ok"] is False
