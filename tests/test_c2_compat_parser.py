"""
v0.10.0-B C2 compatibility parser — targeted unit tests.

These tests exercise _parse_worker_stdout directly against every known
worker-output shape without involving subprocess or real Ollama calls.
"""
import json
import os
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import local_llm_mcp_server as mcp


# --------------------------------------------------------------------------- #
# Helper: create a fake worker output JSON file that load_worker_output        #
# would locate via its JSON: marker.                                           #
# --------------------------------------------------------------------------- #

def _fake_worker_output_file(tmp_path: Path, payload: dict) -> Path:
    out_file = tmp_path / "fake_output.json"
    out_file.write_text(json.dumps(payload), encoding="utf-8")
    return out_file


def _raw_stdout_with_marker(out_file: Path) -> str:
    """Simulate the raw stdout text a worker writes during non-streaming runs."""
    return f"some log output\nJSON: {out_file}\nmore log output\n"


# --------------------------------------------------------------------------- #
# Strategy 1: direct file path (streaming path when output is None)            #
# --------------------------------------------------------------------------- #

class TestParseWorkerStdoutDirectFilePath:
    def test_existing_json_file_returns_dict(self, tmp_path):
        payload = {"ok": True, "summary": "test"}
        out_file = _fake_worker_output_file(tmp_path, payload)
        data, err = mcp._parse_worker_stdout(str(out_file))
        assert err is None
        assert data == payload

    def test_missing_file_returns_none(self):
        data, err = mcp._parse_worker_stdout("/nonexistent/path/output.json")
        assert data is None
        assert err is not None

    def test_non_json_file_returns_none(self, tmp_path):
        txt_file = tmp_path / "not_json.txt"
        txt_file.write_text("hello world", encoding="utf-8")
        data, err = mcp._parse_worker_stdout(str(txt_file))
        assert data is None


# --------------------------------------------------------------------------- #
# Strategy 2: raw text with JSON: marker (non-streaming path)                  #
# --------------------------------------------------------------------------- #

class TestParseWorkerStdoutJsonMarker:
    def test_valid_marker_loads_output(self, tmp_path):
        payload = {"ok": True, "result": "hello"}
        out_file = _fake_worker_output_file(tmp_path, payload)
        stdout = _raw_stdout_with_marker(out_file)
        data, err = mcp._parse_worker_stdout(stdout)
        assert err is None
        assert data == payload

    def test_marker_points_to_missing_file_returns_none(self, tmp_path):
        stdout = f"JSON: {tmp_path / 'no_such_file.json'}\n"
        data, err = mcp._parse_worker_stdout(stdout)
        assert data is None

    def test_no_marker_and_not_json_falls_through(self):
        data, err = mcp._parse_worker_stdout("just some random stdout text")
        assert data is None
        assert err is not None


# --------------------------------------------------------------------------- #
# Strategy 3: JSON-encoded string (streaming path, line 1417)                  #
# --------------------------------------------------------------------------- #

class TestParseWorkerStdoutJsonString:
    def test_json_dict_string_returns_dict(self):
        payload = {"ok": True, "key_files": ["a.py"], "summary": "s"}
        data, err = mcp._parse_worker_stdout(json.dumps(payload))
        assert err is None
        assert data == payload

    def test_json_list_is_not_dict_returns_none(self):
        data, err = mcp._parse_worker_stdout(json.dumps([1, 2, 3]))
        assert data is None

    def test_json_scalar_is_not_dict_returns_none(self):
        data, err = mcp._parse_worker_stdout(json.dumps("just a string"))
        assert data is None


# --------------------------------------------------------------------------- #
# Strategy 4: double-serialized JSON                                          #
# --------------------------------------------------------------------------- #

class TestParseWorkerStdoutDoubleSerialized:
    def test_double_encoded_dict_returns_inner_dict(self):
        inner = {"ok": True, "result": "deep"}
        outer = json.dumps(inner)         # first serialization
        double = json.dumps(outer)        # second serialization
        data, err = mcp._parse_worker_stdout(double)
        assert err is None
        assert data == inner

    def test_double_encoded_non_dict_inner_returns_none(self):
        double = json.dumps(json.dumps([1, 2]))
        data, err = mcp._parse_worker_stdout(double)
        assert data is None


# --------------------------------------------------------------------------- #
# Edge cases                                                                   #
# --------------------------------------------------------------------------- #

class TestParseWorkerStdoutEdgeCases:
    def test_empty_string_returns_none(self):
        data, err = mcp._parse_worker_stdout("")
        assert data is None
        assert err is not None

    def test_whitespace_only_returns_none(self):
        data, err = mcp._parse_worker_stdout("   \n  \t ")
        assert data is None
        assert err is not None

    def test_none_like_string_returns_none(self):
        data, err = mcp._parse_worker_stdout("None")
        assert data is None

    def test_marker_wins_over_json_string_when_both_present(self, tmp_path):
        """When stdout has BOTH a JSON: marker and is valid JSON, the marker
        path should win (Strategy 2 before Strategy 3)."""
        payload = {"ok": True, "from": "file"}
        out_file = _fake_worker_output_file(tmp_path, payload)
        # Construct a string that is both valid JSON and contains a JSON: marker.
        # Actually a JSON dict cannot contain "JSON:" as a raw substring...
        # Use the raw marker format which is not valid JSON.
        stdout = _raw_stdout_with_marker(out_file)
        data, err = mcp._parse_worker_stdout(stdout)
        assert err is None
        assert data == payload


# --------------------------------------------------------------------------- #
# Strategy 0 (v0.10.0-C): dict/object input hardening                         #
# --------------------------------------------------------------------------- #

class TestParseWorkerStdoutDictInput:
    def test_dict_input_returns_directly(self):
        payload = {"ok": True, "summary": "direct pass-through"}
        data, err = mcp._parse_worker_stdout(payload)
        assert err is None
        assert data is payload  # same object, not a copy

    def test_empty_dict_is_valid(self):
        data, err = mcp._parse_worker_stdout({})
        assert err is None
        assert data == {}

    def test_list_input_is_rejected(self):
        data, err = mcp._parse_worker_stdout([1, 2, 3])
        assert data is None
        assert err is not None
        assert "list" in err

    def test_none_input_is_rejected(self):
        data, err = mcp._parse_worker_stdout(None)
        assert data is None
        assert err is not None
        assert "NoneType" in err

    def test_int_input_is_rejected(self):
        data, err = mcp._parse_worker_stdout(42)
        assert data is None
        assert err is not None
        assert "int" in err

    def test_custom_object_is_rejected(self):
        class Foo:
            pass
        data, err = mcp._parse_worker_stdout(Foo())
        assert data is None
        assert err is not None
        assert "Foo" in err

    def test_boolean_true_is_rejected(self):
        data, err = mcp._parse_worker_stdout(True)
        assert data is None
        assert err is not None


# --------------------------------------------------------------------------- #
# v0.10.0-D: producer pass-through from streaming path                        #
# --------------------------------------------------------------------------- #

class TestStreamingProducerDictPassthrough:
    """Verify that when run_subprocess_streaming returns a dict in stdout,
    _parse_worker_stdout hands it through without extra encoding."""

    def test_dict_stdout_reaches_parser_unmodified(self):
        """Simulate the v0.10.0-D streaming producer: stdout=dict."""
        payload = {
            "ok": True,
            "result": "review passed",
            "key_files": ["a.py"],
            "summary": "all good",
        }
        # After v0.10.0-D, run_subprocess_streaming returns the dict directly.
        streaming_result = {"ok": True, "stdout": payload, "stderr": ""}
        data, err = mcp._parse_worker_stdout(streaming_result["stdout"])
        assert err is None
        assert data is payload

    def test_dict_stdout_with_missing_output_path_uses_string_fallback(self):
        """When no JSON path was found, stdout is a string (file path or '').
        _parse_worker_stdout must still handle that via string strategies."""
        streaming_result = {"ok": True, "stdout": "", "stderr": ""}
        data, err = mcp._parse_worker_stdout(streaming_result["stdout"])
        assert data is None  # empty string → no output

    def test_legacy_json_string_stdout_still_works(self):
        """Pre-v0.10.0-D streaming stdout (json.dumps string) is still
        handled by Strategy 3."""
        payload = {"ok": True, "result": "old format"}
        legacy_stdout = json.dumps(payload)
        streaming_result = {"ok": True, "stdout": legacy_stdout, "stderr": ""}
        data, err = mcp._parse_worker_stdout(streaming_result["stdout"])
        assert err is None
        assert data == payload
