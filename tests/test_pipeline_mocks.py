import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import pipeline_mocks as pm

class TestMockPlanGen:
    def test_default(self):
        p = pm.generate_mock_plan("fix typo in README")
        assert p["generated_by"] == "mock_plan_generator"
        assert p["risk_level"] == "low"
        assert "phases" in p
    def test_keyword_high(self):
        assert pm.generate_mock_plan("fix security vuln")["risk_level"]=="high"
    def test_keyword_medium(self):
        assert pm.generate_mock_plan("refactor router")["risk_level"]=="medium"
    def test_custom_cfg(self):
        cfg=pm.MockPlanConfig(risk_level="high",requires_tests=False,cloud_ok=True)
        p=pm.generate_mock_plan("x",config=cfg)
        assert p["risk_level"]=="high"
        assert not p["requires_tests"]
    def test_guess_mcp(self):
        assert any("mcp" in f for f in pm._guess_files("update MCP"))
    def test_guess_router(self):
        assert any("router" in f for f in pm._guess_files("fix routing"))
    def test_guess_fallback(self):
        assert len(pm._guess_files("???"))==1
class TestRouteCommittee:
    def setup_method(self):self.plan={"task_description":"test","risk_level":"low"}
    def test_qwen_def(self):j=pm.generate_mock_qwen_judgement(self.plan);assert j["recommended_route"]=="local_only"
    def test_qwen_pro(self):j=pm.generate_mock_qwen_judgement(self.plan,qwen_route="pro_decision");assert j["pro_should_adjudicate"]
    def test_gemma_def(self):j=pm.generate_mock_gemma_judgement(self.plan);assert j["model"]=="gemma4-31b"
    def test_agree(self):c=pm.MockRouteCommitteeConfig(qwen_route="local_only",gemma_route="local_only");assert pm.generate_mock_route_decision(self.plan,config=c)["agreement"]
    def test_disagree(self):c=pm.MockRouteCommitteeConfig(qwen_route="direct",gemma_route="blocked",agreement=False);assert pm.generate_mock_route_decision(self.plan,config=c)["recommended_route"]=="blocked"

class TestLocalWorker:
    def test_summary(self):n,c,t=pm.generate_mock_local_artifact("t1","file_summary","x.py");assert n=="file_summary.md"
    def test_diff(self):n,c,t=pm.generate_mock_local_artifact("t1","diff_review");assert json.loads(c)["confidence"]=="high"
    def test_unknown(self):
        try:pm.generate_mock_local_artifact("t1","bad");assert False
        except ValueError as e:assert "Unknown" in str(e)

class TestFlashWorker:
    def test_patch(self):n,c,t=pm.generate_mock_flash_artifact("t1","patch_candidate");assert "MOCK" in c
    def test_results(self):n,c,t=pm.generate_mock_flash_artifact("t1","test_results");assert json.loads(c)["passed"]==5
    def test_unknown(self):
        try:pm.generate_mock_flash_artifact("t1","bad");assert False
        except ValueError as e:assert "Unknown" in str(e)

class TestProDecision:
    def setup_method(self):self.p={"task_id":"t1","artifacts_summary":{"total":3},"route":{"recommended_route":"local_only"}}
    def test_accept(self):assert pm.generate_mock_pro_decision(self.p)["decision"]=="accept"
    def test_reject(self):c=pm.MockProDecisionConfig(decision="reject");assert pm.generate_mock_pro_decision(self.p,config=c)["decision"]=="reject"
    def test_override(self):c=pm.MockProDecisionConfig(decision="pro_execute_allowed",override_reason="hotfix");assert pm.generate_mock_pro_decision(self.p,config=c)["override_reason"]=="hotfix"
    def test_all_types(self):
        for d in("retry_local","cancel","ask_user"):c=pm.MockProDecisionConfig(decision=d);assert pm.generate_mock_pro_decision(self.p,config=c)["decision"]==d

class TestHelpers:
    def test_merge(self):assert pm._merge_routes("direct","blocked")=="blocked"
    def test_delegability(self):assert pm._delegability_for_route("blocked")=="blocked"
    def test_mock_tests(self):assert pm.run_mock_tests("t1")["mock"]