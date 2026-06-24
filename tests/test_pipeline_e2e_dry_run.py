import json, os, sys, pytest
from pathlib import Path
_TOOLS_DIR = str(Path(__file__).resolve().parent.parent / "tools")
if _TOOLS_DIR not in sys.path: sys.path.insert(0, _TOOLS_DIR)


class TestMockPlanGenerator:
    def test_valid_plan(self):
        from pipeline_mocks import generate_mock_plan
        p = generate_mock_plan("fix a bug")
        assert p["task_description"] == "fix a bug"
        assert "task_id" in p and "risk_level" in p

    def test_risk_heuristics(self):
        from pipeline_mocks import generate_mock_plan
        assert generate_mock_plan("fix security vuln")["risk_level"] == "high"
        assert generate_mock_plan("refactor schema")["risk_level"] == "medium"
        assert generate_mock_plan("fix doc typo")["risk_level"] == "low"

    def test_custom_config(self):
        from pipeline_mocks import generate_mock_plan, MockPlanConfig
        p = generate_mock_plan("t", config=MockPlanConfig(
            risk_level="critical", files_to_modify=["a.py"]))
        assert p["risk_level"] == "critical"
        assert p["files_to_modify"] == ["a.py"]


class TestMockRouteCommittee:
    def test_qwen_judgement(self):
        from pipeline_mocks import generate_mock_qwen_judgement
        j = generate_mock_qwen_judgement({}, qwen_route="local_only")
        assert j["recommended_route"] == "local_only"
        assert j["model"] == "qwen3.6-deep"

    def test_merge_conservative(self):
        from pipeline_mocks import MockRouteCommitteeConfig, generate_mock_route_decision
        cfg = MockRouteCommitteeConfig(
            qwen_route="flash_subagent", gemma_route="pro_decision")
        d = generate_mock_route_decision({}, config=cfg)
        assert d["recommended_route"] == "pro_decision"

    def test_merge_blocked_wins(self):
        from pipeline_mocks import MockRouteCommitteeConfig, generate_mock_route_decision
        cfg = MockRouteCommitteeConfig(
            qwen_route="direct", gemma_route="blocked")
        d = generate_mock_route_decision({}, config=cfg)
        assert d["recommended_route"] == "blocked"

    def test_disagreement_pro_audit(self):
        from pipeline_mocks import MockRouteCommitteeConfig, generate_mock_route_decision
        d = generate_mock_route_decision(
            {}, config=MockRouteCommitteeConfig(agreement=False))
        assert not d["agreement"] and d["pro_audit_requested"]


class TestMockWorkers:
    def test_local_artifact(self):
        from pipeline_mocks import generate_mock_local_artifact
        f, c, t = generate_mock_local_artifact("t1", "file_summary", path="x.py")
        assert f == "file_summary.md" and t == "local_summary" and "x.py" in c

    def test_local_unknown_raises(self):
        from pipeline_mocks import generate_mock_local_artifact
        with pytest.raises(ValueError):
            generate_mock_local_artifact("t1", "nope")

    def test_flash_artifact(self):
        from pipeline_mocks import generate_mock_flash_artifact
        f, c, t = generate_mock_flash_artifact("t1", "patch_candidate")
        assert "MOCK CHANGE" in c

    def test_flash_unknown_raises(self):
        from pipeline_mocks import generate_mock_flash_artifact
        with pytest.raises(ValueError):
            generate_mock_flash_artifact("t1", "nope")


class TestMockProDecision:
    def test_accept(self):
        from pipeline_mocks import generate_mock_pro_decision
        assert generate_mock_pro_decision(
            {"task_id": "t1"})["decision"] == "accept"

    def test_cancel(self):
        from pipeline_mocks import (
            generate_mock_pro_decision, MockProDecisionConfig)
        d = generate_mock_pro_decision(
            {}, config=MockProDecisionConfig(decision="cancel", reason="x"))
        assert d["decision"] == "cancel"

    def test_override(self):
        from pipeline_mocks import (
            generate_mock_pro_decision, MockProDecisionConfig)
        cfg = MockProDecisionConfig(
            decision="pro_execute_allowed", override_reason="urgent")
        d = generate_mock_pro_decision({}, config=cfg)
        assert d["override_reason"] == "urgent"


class TestE2EDryRun:
    def test_all_routes_run(self):
        from pipeline_e2e_dry_run import run_dry_run
        routes = ("local_only", "flash_direct", "flash_subagent",
                   "pro_decision", "pro_execute_allowed", "blocked",
                   "ask_user", "direct")
        for route in routes:
            steps = run_dry_run(f"test-{route}", route=route)
            ok = len(steps) == 9 and all(s.get("ok") for s in steps)
            assert ok, f"{route} failed"

    def test_blocked_no_execution(self):
        from pipeline_e2e_dry_run import run_dry_run
        steps = run_dry_run("bad", route="blocked")
        assert steps[4]["results"][0]["status"] == "blocked"

    def test_ask_user_paused(self):
        from pipeline_e2e_dry_run import run_dry_run
        steps = run_dry_run("ask", route="ask_user")
        assert steps[4]["results"][0]["status"] == "paused"

    def test_blocked_cancels(self):
        from pipeline_e2e_dry_run import run_dry_run
        steps = run_dry_run("bad", route="blocked")
        assert steps[6]["decision"]["decision"] == "cancel"

    def test_json_output(self):
        from pipeline_e2e_dry_run import run_dry_run, format_output
        steps = run_dry_run("test", route="local_only")
        data = json.loads(format_output(steps, json_output=True))
        assert isinstance(data, list) and data[0]["name"] == "create_task"

    def test_task_dir_structure(self):
        from pipeline_e2e_dry_run import run_dry_run
        from pipeline_artifact_store import task_dir
        steps = run_dry_run("test struct", route="local_only")
        td = task_dir(steps[0]["task_id"])
        assert td.exists()
        assert (td / "plan.json").exists()
        assert (td / "route.json").exists()

    def test_session_finalized(self):
        from pipeline_e2e_dry_run import run_dry_run
        from pipeline_artifact_store import task_dir
        steps = run_dry_run("test finalize", route="local_only")
        sf = task_dir(steps[0]["task_id"]) / "session.json"
        session = json.loads(sf.read_text(encoding="utf-8"))
        assert session["status"] == "completed"

    def test_format_pass(self):
        from pipeline_e2e_dry_run import run_dry_run, format_output
        out = format_output(run_dry_run("test", route="local_only"))
        assert "Overall: PASS" in out

    def test_format_fail(self):
        from pipeline_e2e_dry_run import format_output
        steps = [{"step": 1, "name": "bad", "ok": False, "error": "fail"}]
        assert "Overall: FAIL" in format_output(steps)

    def test_agentdb_recording(self):
        from pipeline_e2e_dry_run import run_dry_run
        import agentdb as adb
        steps = run_dry_run(
            "test adb", route="local_only", task_id="test-e2e-003")
        assert all(s.get("ok") for s in steps)
        adb.init_db()
        conn = adb._connect()
        try:
            row = conn.execute(
                "SELECT task_id, route_type FROM tasks WHERE task_id=?",
                ("test-e2e-003",)).fetchone()
            assert row is not None and row[1] == "local_only"
        finally:
            conn.close()


class TestMergeRoutes:
    def test_priority_order(self):
        from pipeline_mocks import _merge_routes
        assert _merge_routes("blocked", "direct") == "blocked"
        assert _merge_routes("ask_user", "direct") == "ask_user"
        assert _merge_routes("pro_decision", "flash_direct") == "pro_decision"
        assert _merge_routes("local_only", "direct") == "local_only"
