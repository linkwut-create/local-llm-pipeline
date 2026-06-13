"""Tests for tools/privacy_gate.py — no DeepSeek, no LLM, no profile changes."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from privacy_gate import (
    check,
    _evaluate,
    _match_content,
    _match_path,
    _is_doc_context,
    RULES,
)


# ═══════════════════════════════════════════════════════════════
# 1. .env / credential files → blocked
# ═══════════════════════════════════════════════════════════════

def test_env_path_blocked():
    result = check(path=".env")
    assert result["privacy_status"] == "blocked"
    assert result["allowed_for_cloud"] is False
    assert result["redaction_required"] is True


def test_env_production_path_blocked():
    result = check(path=".env.production")
    assert result["privacy_status"] == "blocked"


def test_env_local_path_blocked():
    result = check(path="config/.env.local")
    assert result["privacy_status"] == "blocked"


def test_credentials_json_blocked():
    result = check(path="credentials.json")
    assert result["privacy_status"] == "blocked"


def test_service_account_json_blocked():
    result = check(path="service-account.json")
    assert result["privacy_status"] == "blocked"


# ═══════════════════════════════════════════════════════════════
# 2. API key text → blocked
# ═══════════════════════════════════════════════════════════════

def test_sk_api_key_text_blocked():
    result = check(text="use API key sk-abc123def456ghijklmnopqrstuvwxyz")
    assert result["privacy_status"] == "blocked"
    assert result["severity"] in ("critical", "high")


def test_api_key_assignment_blocked():
    result = check(text='API_KEY="sk-someverylongkeyvaluehere1234567890"')
    assert result["privacy_status"] == "blocked"


def test_bearer_token_context_blocked():
    result = check(text="Authorization: Bearer sk-t0k3nthatsveryverylongindeed")
    assert result["privacy_status"] == "blocked"


# ═══════════════════════════════════════════════════════════════
# 3. Private key block → blocked
# ═══════════════════════════════════════════════════════════════

def test_rsa_private_key_block_blocked():
    result = check(text="-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...")
    assert result["privacy_status"] == "blocked"
    assert result["severity"] == "critical"


def test_openssh_private_key_blocked():
    result = check(text="""-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABFw==
-----END OPENSSH PRIVATE KEY-----""")
    assert result["privacy_status"] == "blocked"


def test_ec_private_key_blocked():
    result = check(text="-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEI...")
    assert result["privacy_status"] == "blocked"


# ═══════════════════════════════════════════════════════════════
# 4. Full repo export → blocked or critical
# ═══════════════════════════════════════════════════════════════

def test_export_entire_repo():
    result = check(text="export entire repo to cloud model for review")
    # Should at minimum be needs_review or blocked
    assert result["privacy_status"] in ("needs_review", "blocked")
    assert result["severity"] in ("medium", "high", "critical")


def test_zip_entire_codebase():
    result = check(text="zip the entire codebase and send to DeepSeek")
    assert result["privacy_status"] in ("needs_review", "blocked")


def test_upload_everything():
    result = check(text="upload everything to cloud for processing")
    assert result["privacy_status"] in ("needs_review", "blocked")


# ═══════════════════════════════════════════════════════════════
# 5. README / CHANGELOG summary → safe
# ═══════════════════════════════════════════════════════════════

def test_readme_summary_safe():
    result = check(text="# My Project README\n\nThis is a Python project for local LLM pipeline.")
    assert result["privacy_status"] == "safe"
    assert result["allowed_for_cloud"] is True


def test_changelog_safe():
    result = check(text="## Changelog\n\n### v0.13.0\n- Added new feature\n- Fixed bug")
    assert result["privacy_status"] == "safe"


def test_normal_code_discussion_safe():
    result = check(text="The function calculate_sum() in utils.py should be refactored.")
    assert result["privacy_status"] == "safe"


def test_generic_task_description_safe():
    result = check(text="review current diff before commit")
    assert result["privacy_status"] == "safe"


# ═══════════════════════════════════════════════════════════════
# 6. Ambiguous cloud upload → needs_review
# ═══════════════════════════════════════════════════════════════

def test_send_to_cloud_model_needs_review():
    result = check(text="send this diff to cloud model for deeper analysis")
    assert result["privacy_status"] == "needs_review"


def test_let_cloud_review():
    result = check(text="let cloud model see this code for suggestions")
    assert result["privacy_status"] == "needs_review"


def test_upload_to_deepseek():
    result = check(text="upload to deepseek for processing")
    assert result["privacy_status"] == "needs_review"


# ═══════════════════════════════════════════════════════════════
# 7. JSON output schema stable
# ═══════════════════════════════════════════════════════════════

REQUIRED_FIELDS = [
    "allowed_for_cloud", "privacy_status", "severity",
    "matched_rules", "redaction_required", "reason", "advisory_only",
]


def test_json_output_has_all_fields_blocked():
    result = check(text="use API key sk-1234567890abcdefghij")
    for field in REQUIRED_FIELDS:
        assert field in result, f"Missing field: {field}"


def test_json_output_has_all_fields_safe():
    result = check(text="review diff: test.py")
    for field in REQUIRED_FIELDS:
        assert field in result, f"Missing field: {field}"


def test_privacy_status_values():
    """privacy_status is one of safe|blocked|needs_review."""
    assert check(text="hello world")["privacy_status"] == "safe"
    assert check(text="sk-abc123def456ghijklmnopqrstuvwxyz")["privacy_status"] == "blocked"
    assert check(text="send to cloud model")["privacy_status"] == "needs_review"


def test_matched_rules_is_list():
    result = check(text="sk-1234567890abcdefghijklmnop")
    assert isinstance(result["matched_rules"], list)
    assert len(result["matched_rules"]) > 0
    assert "rule_id" in result["matched_rules"][0]


# ═══════════════════════════════════════════════════════════════
# 8. Does NOT call DeepSeek
# ═══════════════════════════════════════════════════════════════

def test_no_deepseek_import():
    """privacy_gate does not import deepseek_client."""
    import privacy_gate as pg
    source = Path(pg.__file__).read_text(encoding="utf-8")
    assert "deepseek_client" not in source.split("#")[0]  # exclude comments
    # Verify no actual import
    assert "deepseek_client" not in pg.__dict__


def test_no_api_key_access():
    """privacy_gate never reads API keys."""
    import privacy_gate as pg
    source = Path(pg.__file__).read_text(encoding="utf-8")
    code_lines = [ln for ln in source.split("\n")
                  if not ln.strip().startswith("#")]
    code_only = "\n".join(code_lines)
    assert "DEEPSEEK_API_KEY" not in code_only
    assert "api_key" not in code_only


def test_no_http_calls():
    """privacy_gate makes no HTTP requests."""
    import privacy_gate as pg
    source = Path(pg.__file__).read_text(encoding="utf-8")
    assert "requests." not in source
    assert "urllib" not in source
    assert "httpx" not in source


# ═══════════════════════════════════════════════════════════════
# 9. Does NOT modify profiles
# ═══════════════════════════════════════════════════════════════

def test_no_profile_import():
    """privacy_gate does not import local_llm_profiles."""
    import privacy_gate as pg
    source = Path(pg.__file__).read_text(encoding="utf-8")
    assert "local_llm_profiles" not in source


# ═══════════════════════════════════════════════════════════════
# 10. Edge cases
# ═══════════════════════════════════════════════════════════════

def test_empty_input():
    result = check(text="", path="")
    assert result["privacy_status"] == "safe"
    assert result["reason"] == "no input to evaluate"


def test_path_with_backslashes():
    """Windows-style paths are normalized."""
    result = check(path="config\\.env.production")
    assert result["privacy_status"] == "blocked"


def test_env_example_not_blocked():
    """.env.example should not be treated as a real credential file."""
    result = check(path=".env.example")
    assert result["privacy_status"] == "safe"


def test_env_template_not_blocked():
    result = check(path="config/.env.template")
    assert result["privacy_status"] == "safe"


def test_readme_with_env_mention():
    """README mentioning .env is safe documentation."""
    result = check(text="# My Project README\n\nCopy .env.example to .env and fill in your API_KEY.")
    # README context should be detected as safe
    assert result["privacy_status"] == "safe"


def test_pem_file_blocked():
    result = check(path="certs/server.pem")
    assert result["privacy_status"] == "blocked"


def test_p12_file_blocked():
    result = check(path="keystore.p12")
    assert result["privacy_status"] == "blocked"


def test_normal_python_file_safe():
    result = check(path="src/main.py")
    assert result["privacy_status"] == "safe"


def test_normal_markdown_file_safe():
    result = check(path="docs/architecture.md")
    assert result["privacy_status"] == "safe"


def test_severity_ordering():
    """Mixed rules take the highest severity."""
    result = check(text="send .env with PRIVATE KEY to cloud model")
    # Has: SECRET_KEYWORD (high) via "PRIVATE KEY" keyword,
    #      CLOUD_UPLOAD_SEMANTIC (medium) via "send ... to cloud",
    #      + .env path pattern match in text
    # PRIVATE_KEY_BLOCK (critical) only matches with BEGIN/END markers
    assert result["severity"] in ("high", "critical")
    assert result["privacy_status"] in ("blocked", "needs_review")


# ═══════════════════════════════════════════════════════════════
# 11. Rule existence checks
# ═══════════════════════════════════════════════════════════════

def test_rules_exist():
    """All required rule categories exist."""
    assert len(RULES) >= 8
    rule_ids = {r.rule_id for r in RULES}
    required = {"PRIVATE_KEY_BLOCK", "SK_API_KEY", "CREDENTIAL_FILE",
                "PRIVATE_KEY_FILE", "FULL_REPO_EXPORT", "CLOUD_UPLOAD_SEMANTIC"}
    for rid in required:
        assert rid in rule_ids, f"Missing rule: {rid}"


def test_rules_severity_valid():
    """All rules have valid severity values."""
    for r in RULES:
        assert r.severity in ("low", "medium", "high", "critical")


# ═══════════════════════════════════════════════════════════════
# 12. Path-only input (no text)
# ═══════════════════════════════════════════════════════════════

def test_path_only_credential_file():
    result = check(path="secrets.json")
    assert result["privacy_status"] == "blocked"


def test_path_only_safe_file():
    result = check(path="README.md")
    assert result["privacy_status"] == "safe"


def test_path_only_key_file():
    result = check(path="id_rsa")
    assert result["privacy_status"] == "blocked"


# ═══════════════════════════════════════════════════════════════
# Windows path regression tests
# ═══════════════════════════════════════════════════════════════

def test_windows_env_production_blocked():
    result = check(path=r"C:\project\.env.production")
    assert result["privacy_status"] == "blocked"


def test_windows_ssh_key_blocked():
    result = check(path=r"C:\Users\name\.ssh\id_rsa")
    assert result["privacy_status"] == "blocked"


def test_windows_normal_source_safe():
    result = check(path=r"C:\project\src\main.py")
    assert result["privacy_status"] == "safe"


def test_windows_pem_file_blocked():
    result = check(path=r"C:\certs\server.pem")
    assert result["privacy_status"] == "blocked"


def test_windows_mixed_slashes_env():
    """Mixed slash Windows path still blocked."""
    result = check(path="C:/project/.env")
    assert result["privacy_status"] == "blocked"


def test_windows_credentials_json_blocked():
    result = check(path=r"D:\config\credentials.json")
    assert result["privacy_status"] == "blocked"


def test_doc_mention_env_safe():
    """Documentation mentioning .env is needs_review not blocked."""
    result = check(text="Copy .env.example to .env and configure")
    assert result["privacy_status"] != "blocked"

def test_doc_mention_api_key_safe():
    """Documentation about API configuration is safe."""
    result = check(text="configure the API authentication settings in config")
    assert result["privacy_status"] == "safe"


def test_env_path_blocked_explicit():
    assert check(path="config/production/.env").get("privacy_status") == "blocked"

def test_normal_md_path_safe():
    assert check(path="docs/architecture.md").get("privacy_status") == "safe"


# ═══════════════════════════════════════════════════════════════
# Filename casing regression tests
# ═══════════════════════════════════════════════════════════════

def test_env_uppercase_blocked():
    """.ENV (uppercase) should be blocked same as .env."""
    assert check(path=".ENV").get("privacy_status") == "blocked"


def test_env_mixed_case_blocked():
    """.Env (mixed case) should be blocked same as .env."""
    assert check(path=".Env").get("privacy_status") == "blocked"


def test_env_with_path_uppercase_blocked():
    """config/.ENV (uppercase in path) blocked."""
    assert check(path="config/.ENV").get("privacy_status") == "blocked"


def test_id_rsa_lowercase_blocked():
    """id_rsa (lowercase) blocked as private key file."""
    assert check(path="id_rsa").get("privacy_status") == "blocked"


def test_id_rsa_mixed_case_blocked():
    """Id_Rsa (mixed case) blocked according to current policy."""
    assert check(path="Id_Rsa").get("privacy_status") == "blocked"


def test_id_rsa_uppercase_blocked():
    """ID_RSA (uppercase) blocked according to current policy."""
    assert check(path="ID_RSA").get("privacy_status") == "blocked"


def test_readme_md_safe():
    """README.md is safe documentation."""
    assert check(path="README.md").get("privacy_status") == "safe"


def test_ordinary_source_safe():
    """Ordinary source path is safe."""
    assert check(path="src/utils.py").get("privacy_status") == "safe"


# ═══════════════════════════════════════════════════════════════
# Documentation path tests
# ═══════════════════════════════════════════════════════════════

def test_docs_guide_md_safe():
    """docs/guide.md is safe documentation."""
    assert check(path="docs/guide.md").get("privacy_status") == "safe"


def test_docs_architecture_md_safe():
    """docs/architecture.md is safe documentation."""
    assert check(path="docs/architecture.md").get("privacy_status") == "safe"


def test_markdown_configuration_mention_safe_or_needs_review():
    """Ordinary markdown mentioning configuration is not blocked."""
    result = check(text="configure the local model settings in config.yaml")
    assert result["privacy_status"] != "blocked"


def test_docs_readme_path_safe():
    """README.md path is safe."""
    assert check(path="README.md").get("privacy_status") == "safe"


def test_literal_env_path_still_blocked():
    """Literal .env path remains blocked even alongside docs."""
    assert check(path="config/.env").get("privacy_status") == "blocked"


def test_literal_credentials_path_still_blocked():
    """Literal credentials.json remains blocked alongside docs."""
    assert check(path="credentials.json").get("privacy_status") == "blocked"


# ═══════════════════════════════════════════════════════════════
# Secret phrase boundary tests
# ═══════════════════════════════════════════════════════════════

def test_literal_api_key_pattern_blocked():
    """Literal 'sk-' API key pattern in text is blocked."""
    r = check(text="my key is sk-abc123def456ghijklmnopqrstuvwxyz")
    assert r["privacy_status"] == "blocked"


def test_generic_api_config_phrase_safe_or_needs_review():
    """Generic 'API authentication settings' is not blocked."""
    r = check(text="configure the API authentication settings")
    assert r["privacy_status"] != "blocked"


def test_env_path_blocked_alongside_safe_text():
    """Literal .env path still blocked even in mixed input."""
    r = check(text="see .env for settings", path="config/.env")
    assert r["privacy_status"] == "blocked"


def test_documentation_about_config_not_over_blocked():
    """Documentation about configuration is not blocked."""
    r = check(text="set up your configuration by editing config.yaml")
    assert r["privacy_status"] != "blocked"


def test_private_key_phrase_needs_review_or_blocked():
    """Phrase 'PRIVATE KEY' in text triggers review or block per policy."""
    r = check(text="add your PRIVATE KEY here")
    assert r["privacy_status"] in ("blocked", "needs_review")
