"""Test local_llm_check.py — env var resolution and health check logic."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_check as chk


def test_resolve_ollama_base_url_default():
    """Without env vars, should return localhost default."""
    with patch.dict(os.environ, {}, clear=True):
        base_url, source = chk.resolve_ollama_base_url()
        assert base_url == "http://localhost:11434"
        assert source == "default"


def test_resolve_ollama_base_url_from_local_llm_base_url():
    """LOCAL_LLM_BASE_URL takes highest priority."""
    with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://192.168.2.2:11434",
                                  "OLLAMA_HOST": "other:9999"}, clear=True):
        base_url, source = chk.resolve_ollama_base_url()
        assert base_url == "http://192.168.2.2:11434"
        assert source == "LOCAL_LLM_BASE_URL"


def test_resolve_ollama_base_url_from_ollama_host():
    """OLLAMA_HOST used when LOCAL_LLM_BASE_URL not set."""
    with patch.dict(os.environ, {"OLLAMA_HOST": "192.168.2.2:11434"}, clear=True):
        base_url, source = chk.resolve_ollama_base_url()
        assert base_url == "http://192.168.2.2:11434"
        assert source == "OLLAMA_HOST"


def test_resolve_ollama_base_url_ollama_host_already_has_http():
    """OLLAMA_HOST with http prefix should not double-prefix."""
    with patch.dict(os.environ, {"OLLAMA_HOST": "http://192.168.2.2:11434"}, clear=True):
        base_url, source = chk.resolve_ollama_base_url()
        assert base_url == "http://192.168.2.2:11434"
        assert source == "OLLAMA_HOST"


def test_check_ollama_uses_resolved_url():
    """check_ollama should use the resolved URL, not hardcoded localhost."""
    class MockResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"models": [{"name": "qwen3-coder:30b"}]}

    with patch.dict(os.environ, {"OLLAMA_HOST": "193.168.2.2:11434"}, clear=True):
        with patch("local_llm_check.requests.get") as mock_get:
            mock_get.return_value = MockResponse()
            result = chk.check_ollama()
            called_url = mock_get.call_args[0][0]
            assert "193.168.2.2:11434" in called_url
            assert "localhost" not in called_url
            assert result.ok is True
            assert "193.168.2.2:11434" in result.detail
            assert "OLLAMA_HOST" in result.detail


def test_check_ollama_not_reachable_reports_url():
    """When unreachable, error message should include the URL it tried."""
    with patch.dict(os.environ, {"OLLAMA_HOST": "192.168.2.2:99999"}, clear=True):
        with patch("local_llm_check.requests.get", side_effect=Exception("Connection refused")):
            result = chk.check_ollama()
            assert result.ok is False
            assert "192.168.2.2:99999" in result.detail
            assert "not reachable" in result.detail.lower()
