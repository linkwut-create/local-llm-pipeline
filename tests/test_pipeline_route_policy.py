"""Tests for pipeline_route_policy.py — the single source of truth."""

import json
import sys
from pathlib import Path

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pipeline_route_policy as pp


class TestRouteNameResolution:
    def test_canonical_names_unchanged(self):
        for name in ("local_only", "pro_decision", "pro_execute_allowed",
                      "blocked", "ask_user", "plan_only", "direct",
                      "flash_direct", "flash_subagent"):
            assert pp.resolve_route_name(name) == name

    def test_old_name_claude_code_pro(self):
        assert pp.resolve_route_name("claude_code_pro") == "pro_execute_allowed"

    def test_old_name_manual_confirm(self):
        assert pp.resolve_route_name("manual_confirm") == "ask_user"

    def test_old_name_pro_only(self):
        assert pp.resolve_route_name("pro_only") == "pro_decision"

    def test_unknown_name_falls_back_to_ask_user(self):
        assert pp.resolve_route_name("garbage_nonexistent") == "ask_user"

    def test_empty_name_falls_back(self):
        assert pp.resolve_route_name("") == "ask_user"

    def test_none_falls_back(self):
        assert pp.resolve_route_name(None) == "ask_user"


class TestGetPermissions:
    def test_returns_correct_shape(self):
        perms = pp.get_permissions("pro_decision")
        assert "allowed" in perms
        assert "denied" in perms
        assert "cloud_ok" in perms
        assert "bash_policy" in perms

    def test_falls_back_for_unknown_route(self):
        perms = pp.get_permissions("nonexistent_route")
        assert perms == pp.ROUTE_PERMISSIONS["ask_user"]

    def test_old_name_resolves(self):
        perms = pp.get_permissions("claude_code_pro")
        assert perms == pp.ROUTE_PERMISSIONS["pro_execute_allowed"]


class TestValidateRouteJson:
    def test_valid_route_passes(self):
        errors = pp.validate_route_json({"recommended_route": "local_only"})
        assert errors == []

    def test_missing_route_field(self):
        errors = pp.validate_route_json({"risk_level": "low"})
        assert any("recommended_route" in e for e in errors)

    def test_unknown_route(self):
        errors = pp.validate_route_json({"recommended_route": "nonexistent"})
        assert any("unknown" in e for e in errors)

    def test_invalid_allowed_tools(self):
        errors = pp.validate_route_json({
            "recommended_route": "direct",
            "allowed_tools": "not_a_list",
        })
        assert any("allowed_tools" in e for e in errors)

    def test_non_dict_fails(self):
        errors = pp.validate_route_json(None)
        assert any("object" in e for e in errors)

    def test_shorthand_route_field_accepted(self):
        errors = pp.validate_route_json({"route": "direct"})
        assert errors == []

    def test_bad_enforcement_object(self):
        errors = pp.validate_route_json({
            "recommended_route": "direct",
            "_enforcement": "not_an_object",
        })
        assert any("_enforcement" in e for e in errors)


class TestIsToolPermitted:
    def test_read_allowed_under_pro_decision(self):
        ok, _ = pp.is_tool_permitted("Read", "pro_decision")
        assert ok is True

    def test_edit_denied_under_pro_decision(self):
        ok, reason = pp.is_tool_permitted("Edit", "pro_decision")
        assert ok is False

    def test_edit_allowed_under_pro_execute_allowed(self):
        ok, _ = pp.is_tool_permitted("Edit", "pro_execute_allowed")
        assert ok is True

    def test_bash_classified_under_pro_decision(self):
        ok, _ = pp.is_tool_permitted("Bash", "pro_decision",
                                      {"command": "git status"})
        assert ok is True

    def test_bash_rm_blocked_under_pro_execute_allowed(self):
        ok, reason = pp.is_tool_permitted("Bash", "pro_execute_allowed",
                                           {"command": "rm -rf /"})
        assert ok is False
        assert "destructive" in reason

    def test_allowed_tools_override_takes_priority(self):
        ok, _ = pp.is_tool_permitted(
            "Edit", "pro_decision",
            allowed_tools_override=["Read", "Edit"],
        )
        assert ok is True

    def test_allowed_tools_override_blocks_unlisted(self):
        ok, reason = pp.is_tool_permitted(
            "Write", "pro_execute_allowed",
            allowed_tools_override=["Read"],
        )
        assert ok is False
        assert "allowed_tools" in reason

    def test_tool_family_expansion_task_create(self):
        """Task family alias matches actual Claude Code tool name TaskCreate."""
        ok, _ = pp.is_tool_permitted("TaskCreate", "local_only")
        assert ok is True

    def test_tool_family_expansion_task_update(self):
        """Task family alias matches actual Claude Code tool name TaskUpdate."""
        ok, _ = pp.is_tool_permitted("TaskUpdate", "pro_decision")
        assert ok is True

    def test_unknown_route_falls_back_to_ask_user(self):
        ok, _ = pp.is_tool_permitted("Read", "nonexistent")
        assert ok is True

    def test_unknown_route_blocks_edit(self):
        ok, _ = pp.is_tool_permitted("Edit", "nonexistent")
        assert ok is False


class TestAllRoutesHaveBashPolicy:
    def test_every_route_has_bash_policy(self):
        for name, perms in pp.ROUTE_PERMISSIONS.items():
            assert "bash_policy" in perms, f"{name} missing bash_policy"
            assert perms["bash_policy"] in ("deny_all", "readonly_or_test",
                                             "allow_safe", "allow_all"), \
                f"{name} has invalid bash_policy: {perms['bash_policy']}"

    def test_every_route_has_description(self):
        for name, perms in pp.ROUTE_PERMISSIONS.items():
            assert "description" in perms, f"{name} missing description"


class TestRouteSchemaConsistency:
    def test_valid_routes_match_permissions(self):
        assert pp.VALID_ROUTES == set(pp.ROUTE_PERMISSIONS.keys())

    def test_schema_enum_matches_valid_routes(self):
        schema_routes = set(pp.ROUTE_JSON_SCHEMA["properties"]["recommended_route"]["enum"])
        assert schema_routes == pp.VALID_ROUTES
