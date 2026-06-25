"""Tests for pipeline_adjudicator.py."""

import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import pipeline_adjudicator as pa

class TestValidateDecision:
    def test_valid(self):
        assert pa.validate_decision({"decision":"accept","reason":"ok"}) == []
    def test_missing_decision(self):
        assert any("decision" in e for e in pa.validate_decision({"reason":"x"}))
    def test_unknown(self):
        assert any("unknown" in e for e in pa.validate_decision({"decision":"bad","reason":"x"}))
    def test_all_valid(self):
        for d in ("accept","reject","retry_local","retry_flash","pro_execute_allowed","ask_user","cancel"):
            assert pa.validate_decision({"decision":d,"reason":"ok"})==[]
    def test_empty_dict(self):
        assert len(pa.validate_decision({}))>0
    def test_non_dict(self):
        assert "object" in pa.validate_decision("bad")[0]

class TestAdjudicate:
    def test_accept(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        r = pa.adjudicate("task-a", {"decision":"accept","reason":"ok"})
        assert r["ok"] and r["seq"] == 1
    def test_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        assert pa.adjudicate("task-c", {"decision":"garbage"})["ok"] is False
    def test_pro_execute_allowed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        r = pa.adjudicate("task-e", {"decision":"pro_execute_allowed","reason":"hotfix","override_reason":"urgent"})
        assert r["ok"] and r["seq"]==1
    def test_multiple_sequences(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        r1 = pa.adjudicate("task-f", {"decision":"accept","reason":"ok"})
        r2 = pa.adjudicate("task-f", {"decision":"reject","reason":"no"})
        assert r1["seq"]==1 and r2["seq"]==2

class TestBuildPack:
    def test_empty_task_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        td = tmp_path / "task-h"; td.mkdir(parents=True)
        (td / "session.json").write_text(json.dumps({"user_task":"test task","status":"active"}))
        pack = pa.build_adjudication_pack("task-h")
        assert pack["user_task"]=="test task"
        assert pack["plan"] is None
    def test_with_plan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        td = tmp_path / "task-i"; td.mkdir(parents=True)
        (td / "session.json").write_text(json.dumps({"user_task":"x"}))
        (td / "plan.json").write_text(json.dumps({"phases":[{"name":"p1"}]}))
        pack = pa.build_adjudication_pack("task-i")
        assert pack["plan"]=={"phases":[{"name":"p1"}]}
    def test_with_route(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        td = tmp_path / "task-j"; td.mkdir(parents=True)
        (td / "session.json").write_text(json.dumps({"user_task":"x"}))
        (td / "route.json").write_text(json.dumps({"recommended_route":"local_only","risk_level":"low"}))
        pack = pa.build_adjudication_pack("task-j")
        assert pack["route"]["recommended_route"]=="local_only"
    def test_unparseable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        td = tmp_path / "task-k"; td.mkdir(parents=True)
        (td / "session.json").write_text(json.dumps({"user_task":"x"}))
        (td / "plan.json").write_text("not json")
        pack = pa.build_adjudication_pack("task-k")
        assert pack["plan"]=="(unparseable)"