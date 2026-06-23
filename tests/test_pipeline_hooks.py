"""Tests for pipeline_hooks.py — the hook installation manager."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pipeline_hooks as ph


class TestIsPipelineHook:
    def test_matches_enforcer_script(self):
        entry = {"hooks": [{"type": "command", "command": "python tools/claude_hooks/route_enforcer.py"}]}
        assert ph._is_pipeline_hook(entry) is True

    def test_does_not_match_other_script(self):
        entry = {"hooks": [{"type": "command", "command": "echo hello"}]}
        assert ph._is_pipeline_hook(entry) is False

    def test_empty_hooks(self):
        assert ph._is_pipeline_hook({"hooks": []}) is False

    def test_not_a_dict(self):
        assert ph._is_pipeline_hook("not a dict") is False


class TestInstallIdempotent:
    def test_install_dry_run_new_file(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: settings_file)
        monkeypatch.setattr(ph, "_backup_settings", lambda local=False: None)
        result = ph.install(dry_run=True)
        assert "DRY RUN" in result

    def test_install_dry_run_existing_file(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: settings_file)
        monkeypatch.setattr(ph, "_backup_settings", lambda local=False: None)
        result = ph.install(dry_run=True)
        assert "DRY RUN" in result


class TestStatus:
    def test_status_no_file(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: settings_file)
        result = ph.status()
        assert "does not exist" in result

    def test_status_json(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"hooks": {
            "Stop": [{"hooks": [{"command": "python tools/claude_hooks/route_enforcer.py"}]}]
        }}), encoding="utf-8")
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: settings_file)
        result = ph.status(json_output=True)
        data = json.loads(result)
        assert data["pipeline_installed"] is True


class TestUninstall:
    def test_uninstall_no_hooks(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: settings_file)
        monkeypatch.setattr(ph, "_backup_settings", lambda local=False: None)
        result = ph.uninstall()
        assert "No pipeline hooks" in result

    def test_uninstall_dry_run(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"hooks": {
            "Stop": [{"hooks": [{"command": "python tools/claude_hooks/route_enforcer.py"}]}]
        }}), encoding="utf-8")
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: settings_file)
        monkeypatch.setattr(ph, "_backup_settings", lambda local=False: None)
        result = ph.uninstall(dry_run=True)
        assert "DRY RUN" in result

    def test_uninstall_keeps_other_hooks(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"hooks": {
            "Stop": [
                {"hooks": [{"command": "echo custom"}]},
                {"hooks": [{"command": "python tools/claude_hooks/route_enforcer.py"}]},
            ]
        }}), encoding="utf-8")
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: settings_file)
        monkeypatch.setattr(ph, "_backup_settings", lambda local=False: None)
        ph.uninstall()
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        entries = data["hooks"]["Stop"]
        # Only the custom hook should remain
        assert len(entries) == 1
        assert "echo custom" in entries[0]["hooks"][0]["command"]


class TestFindPython:
    def test_returns_string(self):
        result = ph._find_python()
        assert isinstance(result, str)
        assert len(result) > 0


class TestDoctor:
    def test_doctor_runs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ph, "_settings_path", lambda local=False: tmp_path / "nonexistent.json")
        result = ph.doctor()
        assert "Pipeline Hook Doctor" in result
        assert "Python" in result
        assert "Enforcer" in result
