"""Tests for P4-B worker pool dry-run probe.

Covers:
- `build_probe_report()` shape, invariants, and behavior across
  reachable / unreachable / requests-missing scenarios.
- The `--probe-workers` / `--json` CLI flags on `local_llm_check.main()`.
- Default-path invariance: no flags → existing human-readable health
  check, no JSON probe object.
- No side effects on router / profile / ledger modules.

All HTTP is mocked. No real network is required.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_check as check  # noqa: E402


def _make_mock_requests(*, side_effect=None) -> MagicMock:
    """Return a MagicMock standing in for the `requests` module.

    Default: every `get()` returns a response whose `raise_for_status`
    is a no-op (i.e. reachable). Pass `side_effect=Exception(...)` to
    simulate network failure.
    """
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_requests = MagicMock()
    if side_effect is not None:
        mock_requests.get.side_effect = side_effect
    else:
        mock_requests.get.return_value = mock_resp
    return mock_requests


class TestBuildProbeReportShape:
    """Top-level shape and invariants of build_probe_report()."""

    def test_required_keys_present(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        required = {
            "schema_version",
            "worker_pool_dry_run_enabled",
            "configured_workers",
            "reachable_workers",
            "unreachable_workers",
            "probe_errors",
            "routing_changed",
            "ledger_stamped",
            "probed_at",
        }
        assert required.issubset(report.keys())

    def test_schema_version_is_one(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        assert report["schema_version"] == 1

    def test_worker_pool_dry_run_enabled_is_true(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        assert report["worker_pool_dry_run_enabled"] is True

    def test_routing_changed_is_literal_false_when_all_reachable(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        assert report["routing_changed"] is False

    def test_routing_changed_is_literal_false_when_all_unreachable(self):
        mock_req = _make_mock_requests(side_effect=ConnectionError("boom"))
        with patch.object(check, "requests", mock_req):
            report = check.build_probe_report()
        assert report["routing_changed"] is False

    def test_ledger_stamped_is_literal_false_when_all_reachable(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        assert report["ledger_stamped"] is False

    def test_ledger_stamped_is_literal_false_when_all_unreachable(self):
        mock_req = _make_mock_requests(side_effect=ConnectionError("boom"))
        with patch.object(check, "requests", mock_req):
            report = check.build_probe_report()
        assert report["ledger_stamped"] is False


class TestBuildProbeReportConfiguredWorkers:
    """Configured workers derive from existing read-only sources only."""

    def test_includes_ollama_default(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        types = {w["endpoint_type"] for w in report["configured_workers"]}
        assert "ollama" in types

    def test_includes_openai_compat_default(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        types = {w["endpoint_type"] for w in report["configured_workers"]}
        assert "openai_compat" in types

    def test_includes_all_mtp_endpoints(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        mtp_workers = [
            w for w in report["configured_workers"]
            if w["endpoint_type"] == "llama_cpp_mtp"
        ]
        assert len(mtp_workers) == len(check._MTP_ENDPOINTS)

    def test_count_matches_known_sources(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        # ollama + openai_compat + all _MTP_ENDPOINTS
        expected = 2 + len(check._MTP_ENDPOINTS)
        assert len(report["configured_workers"]) == expected

    def test_each_worker_has_required_fields(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        for w in report["configured_workers"]:
            assert "id" in w and w["id"]
            assert "host" in w and w["host"]
            assert "endpoint" in w and w["endpoint"]
            assert "endpoint_type" in w and w["endpoint_type"]

    def test_worker_ids_are_unique(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        ids = [w["id"] for w in report["configured_workers"]]
        assert len(ids) == len(set(ids))


class TestBuildProbeReportReachability:
    """Reachable/unreachable bucketing and error reporting."""

    def test_all_reachable_when_get_succeeds(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        assert len(report["reachable_workers"]) == len(report["configured_workers"])
        assert len(report["unreachable_workers"]) == 0
        assert len(report["probe_errors"]) == 0
        for w in report["reachable_workers"]:
            assert w["reachable"] is True

    def test_all_unreachable_when_get_raises(self):
        mock_req = _make_mock_requests(
            side_effect=ConnectionError("connection refused"))
        with patch.object(check, "requests", mock_req):
            report = check.build_probe_report()
        assert len(report["reachable_workers"]) == 0
        assert len(report["unreachable_workers"]) == len(report["configured_workers"])
        assert len(report["probe_errors"]) == len(report["configured_workers"])
        for w in report["unreachable_workers"]:
            assert w["reachable"] is False
            assert "error" in w and w["error"]

    def test_probe_errors_reference_configured_ids(self):
        mock_req = _make_mock_requests(side_effect=TimeoutError("slow"))
        with patch.object(check, "requests", mock_req):
            report = check.build_probe_report()
        configured_ids = {w["id"] for w in report["configured_workers"]}
        for e in report["probe_errors"]:
            assert e["id"] in configured_ids
            assert "error" in e and e["error"]

    def test_mixed_reachable_and_unreachable(self):
        # Fail every other call
        call_count = {"n": 0}

        def maybe_fail(*_args, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] % 2 == 0:
                raise ConnectionError("flaky")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        mock_req = MagicMock()
        mock_req.get.side_effect = maybe_fail
        with patch.object(check, "requests", mock_req):
            report = check.build_probe_report()
        total = len(report["configured_workers"])
        assert (
            len(report["reachable_workers"])
            + len(report["unreachable_workers"])
            == total
        )
        assert len(report["reachable_workers"]) > 0
        assert len(report["unreachable_workers"]) > 0

    def test_probe_does_not_raise_on_network_error(self):
        mock_req = _make_mock_requests(side_effect=RuntimeError("blew up"))
        with patch.object(check, "requests", mock_req):
            check.build_probe_report()  # must not raise

    def test_probe_handles_missing_requests(self):
        with patch.object(check, "requests", None):
            report = check.build_probe_report()
        assert len(report["reachable_workers"]) == 0
        assert len(report["unreachable_workers"]) == len(report["configured_workers"])
        for e in report["probe_errors"]:
            assert "requests" in e["error"]


class TestCLIFlags:
    """`--probe-workers` / `--json` flag behavior on main()."""

    def test_default_no_flags_runs_health_check(self, capsys):
        # Use the mocked requests so no real network is hit
        with patch.object(check, "requests", _make_mock_requests()), \
             patch.object(check.subprocess, "check_output",
                          side_effect=FileNotFoundError("no ollama cli")):
            check.main([])
        out = capsys.readouterr().out
        assert "Local LLM Environment Health Check" in out
        assert "Basic Environment" in out
        # Default path must not emit a JSON probe object alone
        stripped = out.strip()
        assert not stripped.startswith("{")

    def test_default_no_flags_does_not_emit_probe_section(self, capsys):
        with patch.object(check, "requests", _make_mock_requests()), \
             patch.object(check.subprocess, "check_output",
                          side_effect=FileNotFoundError("no ollama cli")):
            check.main([])
        out = capsys.readouterr().out
        assert "Worker Pool Dry-Run Probe" not in out

    def test_probe_workers_json_emits_json_only(self, capsys):
        with patch.object(check, "requests", _make_mock_requests()):
            rc = check.main(["--probe-workers", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        # Must be parseable JSON (single object)
        report = json.loads(out)
        assert report["schema_version"] == 1
        assert report["worker_pool_dry_run_enabled"] is True
        assert report["routing_changed"] is False
        assert report["ledger_stamped"] is False
        # Must not have the human-readable section banners
        assert "Local LLM Environment Health Check" not in out
        assert "Basic Environment" not in out

    def test_probe_workers_json_includes_all_required_keys(self, capsys):
        with patch.object(check, "requests", _make_mock_requests()):
            check.main(["--probe-workers", "--json"])
        report = json.loads(capsys.readouterr().out)
        required = {
            "schema_version",
            "worker_pool_dry_run_enabled",
            "configured_workers",
            "reachable_workers",
            "unreachable_workers",
            "probe_errors",
            "routing_changed",
            "ledger_stamped",
            "probed_at",
        }
        assert required.issubset(report.keys())

    def test_json_alone_does_not_emit_probe(self, capsys):
        with patch.object(check, "requests", _make_mock_requests()), \
             patch.object(check.subprocess, "check_output",
                          side_effect=FileNotFoundError("no ollama cli")):
            check.main(["--json"])
        out = capsys.readouterr().out
        # --json alone is a no-op for probe; default health-check flow runs
        assert "Local LLM Environment Health Check" in out
        assert "Worker Pool Dry-Run Probe" not in out

    def test_probe_workers_alone_appends_human_section(self, capsys):
        with patch.object(check, "requests", _make_mock_requests()), \
             patch.object(check.subprocess, "check_output",
                          side_effect=FileNotFoundError("no ollama cli")):
            check.main(["--probe-workers"])
        out = capsys.readouterr().out
        assert "Local LLM Environment Health Check" in out
        assert "Worker Pool Dry-Run Probe" in out
        assert "routing_changed:   False" in out
        assert "ledger_stamped:    False" in out


class TestNoSideEffects:
    """Probe path must not import or call router / profile / ledger code."""

    def test_build_probe_report_source_has_no_router_refs(self):
        src = inspect.getsource(check.build_probe_report)
        forbidden = [
            "resolve_profile",
            "is_profile_healthy",
            "_resolve_starting_profile",
            "local_llm_router",
        ]
        for name in forbidden:
            assert name not in src, (
                f"build_probe_report must not reference {name!r}"
            )

    def test_build_probe_report_source_has_no_ledger_refs(self):
        src = inspect.getsource(check.build_probe_report)
        forbidden = [
            "record_invocation",
            "_emit_ledger",
            "call_ledger",
            "LOCAL_LLM_LEDGER_EXTRA",
        ]
        for name in forbidden:
            assert name not in src, (
                f"build_probe_report must not reference {name!r}"
            )

    def test_module_does_not_import_ledger(self):
        """local_llm_check.py must not have grown a ledger import."""
        check_path = Path(check.__file__)
        text = check_path.read_text(encoding="utf-8")
        assert "import call_ledger" not in text
        assert "from call_ledger" not in text

    def test_module_does_not_import_router(self):
        check_path = Path(check.__file__)
        text = check_path.read_text(encoding="utf-8")
        assert "import local_llm_router" not in text
        assert "from local_llm_router" not in text


class TestSchemaInvariants:
    """Lock the contract that future readers depend on."""

    def test_routing_changed_field_present_and_false(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        assert "routing_changed" in report
        assert report["routing_changed"] is False
        # Must be the literal bool, not a truthy string / non-zero int
        assert isinstance(report["routing_changed"], bool)

    def test_ledger_stamped_field_present_and_false(self):
        with patch.object(check, "requests", _make_mock_requests()):
            report = check.build_probe_report()
        assert "ledger_stamped" in report
        assert report["ledger_stamped"] is False
        assert isinstance(report["ledger_stamped"], bool)

    def test_schema_version_constant_is_exported(self):
        assert hasattr(check, "PROBE_REPORT_SCHEMA_VERSION")
        assert check.PROBE_REPORT_SCHEMA_VERSION == 1
