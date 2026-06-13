#!/usr/bin/env python3
"""
Privacy Gate — local rule-based privacy check for future DeepSeek cloud calls.

Checks whether task text, file paths, or content contain information that
should NOT be sent to a cloud API. Pure rule-based — no LLM calls, no API
calls, no file scanning beyond explicit --path.

Design constraints:
  - Never calls DeepSeek API or any LLM.
  - Never reads API keys or secrets from disk.
  - Never scans the repo (only checks explicit --text / --path input).
  - Conservative: uncertain → needs_review, clearly sensitive → blocked.
  - All output is advisory-only.

Usage:
  py -3 tools/privacy_gate.py --text "check .env.production for credentials"
  py -3 tools/privacy_gate.py --path ".env"
  py -3 tools/privacy_gate.py --text "export entire repo to cloud model"
  py -3 tools/privacy_gate.py --json --text "use API key sk-xxx"
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# Rule definitions
# ═══════════════════════════════════════════════════════════════

@dataclass
class PrivacyRule:
    """A single privacy detection rule."""
    rule_id: str
    category: str          # file_path | content_pattern | semantic
    severity: str          # low | medium | high | critical
    description: str
    patterns: list = field(default_factory=list)  # regex patterns
    keywords: list = field(default_factory=list)  # case-insensitive keyword substrings
    path_suffixes: list = field(default_factory=list)  # file path endings to match
    path_exact: list = field(default_factory=list)  # exact file name matches


# Rules are ordered by severity (critical first) for deterministic matching.
RULES: list[PrivacyRule] = [
    # ── Critical: private keys ──
    PrivacyRule(
        rule_id="PRIVATE_KEY_BLOCK",
        category="content_pattern",
        severity="critical",
        description="Private key block (RSA/EC/DSA/OpenSSH/PGP)",
        patterns=[
            r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----",
            r"-----BEGIN PGP PRIVATE KEY BLOCK-----",
            r"-----BEGIN ENCRYPTED PRIVATE KEY-----",
            r"-----BEGIN PRIVATE KEY-----",
        ],
    ),

    # ── Critical: API keys in sk- format ──
    PrivacyRule(
        rule_id="SK_API_KEY",
        category="content_pattern",
        severity="critical",
        description="OpenAI/DeepSeek-style sk- API key",
        patterns=[
            r"sk-[a-zA-Z0-9]{20,}",
            r"sk-[a-zA-Z0-9\-_]{20,}",
        ],
    ),

    # ── High: API key / token assignments ──
    PrivacyRule(
        rule_id="API_KEY_ASSIGNMENT",
        category="content_pattern",
        severity="high",
        description="API key or token in assignment context",
        patterns=[
            r"""(?:api[_-]?key|apikey|api_secret|secret[_-]?key)\s*[=:]\s*['"][^'"]{8,}['"]""",
            r"""(?:token|auth[_-]?token|access[_-]?token)\s*[=:]\s*['"][^'"]{8,}['"]""",
            r"""(?:password|passwd)\s*[=:]\s*['"][^'"]{4,}['"]""",
            r"""(?:credential|secret)\s*[=:]\s*['"][^'"]{8,}['"]""",
        ],
        keywords=["API_KEY", "APIKEY", "API_SECRET", "SECRET_KEY",
                  "AUTH_TOKEN", "ACCESS_TOKEN"],
    ),

    # ── High: credential files ──
    PrivacyRule(
        rule_id="CREDENTIAL_FILE",
        category="file_path",
        severity="high",
        description="Credential or secret file path",
        path_suffixes=[
            ".env", ".env.local", ".env.development", ".env.production",
            ".env.staging", ".env.backup",
        ],
        path_exact=[
            ".env",
            "credentials.json", "credentials.yml", "credentials.yaml",
            "secrets.json", "secrets.yml", "secrets.yaml",
            "service-account.json", "service_account.json",
        ],
    ),

    # ── High: private key files ──
    PrivacyRule(
        rule_id="PRIVATE_KEY_FILE",
        category="file_path",
        severity="high",
        description="Private key or certificate file",
        path_suffixes=[".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"],
        path_exact=["id_rsa", "id_ecdsa", "id_ed25519", "id_dsa",
                     "ssh_host_rsa_key", "ssh_host_ecdsa_key", "ssh_host_ed25519_key"],
    ),

    # ── High: secret keywords in content ──
    PrivacyRule(
        rule_id="SECRET_KEYWORD",
        category="content_pattern",
        severity="high",
        description="Content contains secret/credential indicators",
        keywords=[
            "PRIVATE KEY", "PRIVATE_KEY",
            "CLIENT_SECRET", "MASTER_KEY", "ENCRYPTION_KEY",
            "DATABASE_PASSWORD", "DB_PASSWORD",
        ],
    ),

    # ── Medium: full repo / codebase export ──
    PrivacyRule(
        rule_id="FULL_REPO_EXPORT",
        category="semantic",
        severity="medium",
        description="Full repository or codebase export to cloud",
        keywords=[
            "full repo", "entire repo", "whole repo",
            "entire codebase", "whole codebase", "full codebase",
            "export entire", "export whole", "export full",
            "zip export", "tarball", "archive repo",
            "dump repo", "dump codebase",
            "upload everything", "send everything",
        ],
        patterns=[
            r"export\s+(the\s+)?(entire|whole|full)\s+(repo|codebase|project)",
            r"(zip|tar|archive|bundle)\s+(the\s+)?(repo|codebase|project)",
            r"upload\s+(the\s+)?(entire|whole|full|everything)",
        ],
    ),

    # ── Medium: cloud upload semantics ──
    PrivacyRule(
        rule_id="CLOUD_UPLOAD_SEMANTIC",
        category="semantic",
        severity="medium",
        description="Explicit upload-to-cloud or send-to-external-model semantics",
        patterns=[
            r"send\s+(this|the)\s+(to|through)\s+(cloud|deepseek|openai|external)",
            r"upload\s+(this|the)\s+(to|through)\s+(cloud|deepseek|openai|external)",
            r"share\s+(this|the)\s+(with|to)\s+(cloud|deepseek|openai|external)",
            r"(send|push|upload)\s+(code|source|files?|context)\s+(to|through)\s+(cloud|api)",
            r"let\s+cloud\s+model\s+(see|read|process|analyze|review)",
            r"pass\s+(it|this|the\s+code)\s+(to|through)\s+(cloud|deepseek|api)",
            r"(send|upload|push)\s+to\s+(deepseek|cloud|openai|external\s+api)",
        ],
        keywords=[
            "cloud model", "external model", "remote model",
            "send to deepseek", "send to cloud", "upload to cloud",
            "upload to deepseek", "cloud processing", "cloud api",
        ],
    ),

    # ── Medium: Broad credential references in text ──
    PrivacyRule(
        rule_id="BROAD_CREDENTIAL_REF",
        category="content_pattern",
        severity="medium",
        description="Broad mention of credentials/config with sensitive context",
        patterns=[
            r"\.env\b.*\b(credential|secret|password|key|token)",
            r"(credential|secret|password|key|token)\b.*\.env",
        ],
    ),
]


# ═══════════════════════════════════════════════════════════════
# Safe-list patterns (override blocked status to needs_review)
# ═══════════════════════════════════════════════════════════════

# Content that matches block rules but is clearly safe documentation
SAFE_CONTEXT_INDICATORS = [
    # README/Changelog markers
    r"^#\s+.+\b(README|Changelog|CHANGELOG|Release Notes)\b",
    r"^\*\*Changelog\*\*",
    r"^##\s+Changelog",
    # Template/example markers
    r"\.env\.example\b",
    r"\.env\.template\b",
    r"\.env\.sample\b",
    r"<YOUR_API_KEY>",
    r"<your-api-key>",
    r"your-api-key-here",
    r"your-api-key",
    r"YOUR_API_KEY_HERE",
    r"your_secret_here",
    r"YOUR_SECRET_HERE",
]


# ═══════════════════════════════════════════════════════════════
# Core engine
# ═══════════════════════════════════════════════════════════════

def _is_doc_context(text: str) -> bool:
    """Check if text looks like a README/Changelog/documentation context."""
    for pattern in SAFE_CONTEXT_INDICATORS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _match_path(path: str) -> list[PrivacyRule]:
    """Match a file path against path-based rules."""
    matched = []
    path_lower = path.lower().replace("\\", "/")
    filename = Path(path).name.lower()

    for rule in RULES:
        if rule.category != "file_path":
            continue
        for suffix in rule.path_suffixes:
            if path_lower.endswith(suffix.lower()):
                matched.append(rule)
                break
        else:
            for exact in rule.path_exact:
                if filename == exact.lower():
                    matched.append(rule)
                    break
    return matched


def _match_content(text: str) -> list[PrivacyRule]:
    """Match text content against content and semantic rules."""
    matched = []
    text_upper = text.upper()

    for rule in RULES:
        if rule.category == "file_path":
            continue

        # Check regex patterns
        for pattern in rule.patterns:
            if re.search(pattern, text, re.IGNORECASE):
                matched.append(rule)
                break
        else:
            # Check keywords (case-insensitive)
            for kw in rule.keywords:
                if kw.upper() in text_upper:
                    matched.append(rule)
                    break

    return matched


def _evaluate(text: str = "", path: str = "") -> dict:
    """Core evaluation: run all rules against input, return structured result."""

    matched_rules: list[PrivacyRule] = []
    source = ""

    if path:
        source = "path"
        matched_rules = _match_path(path)
        # Also check the path string as text content
        content_matches = _match_content(path)
        for r in content_matches:
            if r not in matched_rules:
                matched_rules.append(r)
    elif text:
        source = "text"
        matched_rules = _match_content(text)
    else:
        return {
            "allowed_for_cloud": True,
            "privacy_status": "safe",
            "severity": "low",
            "matched_rules": [],
            "redaction_required": False,
            "reason": "no input to evaluate",
            "advisory_only": True,
            "source": "none",
        }

    if not matched_rules:
        return {
            "allowed_for_cloud": True,
            "privacy_status": "safe",
            "severity": "low",
            "matched_rules": [],
            "redaction_required": False,
            "reason": "no privacy rules matched",
            "advisory_only": True,
            "source": source,
        }

    # Determine highest severity
    severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    max_severity = max(
        (r.severity for r in matched_rules),
        key=lambda s: severity_order.get(s, 0),
    )

    # Check if this is a documentation context → downgrade to needs_review or safe
    is_doc = _is_doc_context(text) if text else False

    # Determine if any match is a critical regex pattern (not just keyword)
    has_critical_pattern = any(
        r.severity == "critical" and any(
            re.search(p, text, re.IGNORECASE) for p in r.patterns
        )
        for r in matched_rules
    )

    # Determine status
    rules_info = [
        {"rule_id": r.rule_id, "severity": r.severity, "description": r.description}
        for r in matched_rules
    ]

    if max_severity in ("critical", "high"):
        if is_doc:
            if has_critical_pattern:
                # Actual key material in docs → needs_review
                return {
                    "allowed_for_cloud": True,
                    "privacy_status": "needs_review",
                    "severity": "medium",
                    "matched_rules": rules_info,
                    "redaction_required": False,
                    "reason": (
                        f"matched {len(matched_rules)} rule(s) but context appears to be "
                        f"documentation/template — human review required"
                    ),
                    "advisory_only": True,
                    "source": source,
                }
            else:
                # Keywords in docs → safe (normal documentation)
                return {
                    "allowed_for_cloud": True,
                    "privacy_status": "safe",
                    "severity": "low",
                    "matched_rules": rules_info,
                    "redaction_required": False,
                    "reason": (
                        f"matched {len(matched_rules)} rule(s) but context is clearly "
                        f"documentation/template — downgraded to safe"
                    ),
                    "advisory_only": True,
                    "source": source,
                }
        else:
            return {
                "allowed_for_cloud": False,
                "privacy_status": "blocked",
                "severity": max_severity,
                "matched_rules": rules_info,
                "redaction_required": True,
                "reason": (
                    f"blocked by {len(matched_rules)} rule(s): "
                    + "; ".join(
                        f"{r.rule_id}({r.severity})" for r in matched_rules[:3]
                    )
                ),
                "advisory_only": True,
                "source": source,
            }

    # Medium severity → needs_review
    return {
        "allowed_for_cloud": True,
        "privacy_status": "needs_review",
        "severity": max_severity,
        "matched_rules": rules_info,
        "redaction_required": False,
        "reason": (
            f"matched {len(matched_rules)} medium-severity rule(s) — "
            f"human review recommended"
        ),
        "advisory_only": True,
        "source": source,
    }


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def check(text: str = "", path: str = "") -> dict:
    """Check if input is safe for cloud API transmission.

    Args:
        text: Free-form text to check.
        path: File path to check.

    Returns:
        Dict with allowed_for_cloud, privacy_status, severity, matched_rules,
        redaction_required, reason, advisory_only.
    """
    return _evaluate(text=text, path=path)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Privacy Gate — local rule-based cloud safety check"
    )
    parser.add_argument("--text", default="",
                        help="Text content to check")
    parser.add_argument("--path", default="",
                        help="File path to check")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    if not args.text and not args.path:
        parser.print_help()
        sys.exit(1)

    result = check(text=args.text, path=args.path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    sys.exit(0)


def _print_human(result: dict) -> None:
    """Human-readable output (ASCII-safe for Windows GBK)."""
    status = result["privacy_status"].upper()
    severity = result["severity"].upper()
    allowed = "[OK]" if result["allowed_for_cloud"] else "[BLOCKED]"

    print(f"Privacy Gate: {status} ({severity}) {allowed}")
    print(f"  reason:    {result['reason']}")
    if result["matched_rules"]:
        print(f"  rules:     {len(result['matched_rules'])} matched")
        for r in result["matched_rules"]:
            print(f"    - [{r['severity']}] {r['rule_id']}: {r['description']}")
    print(f"  advisory:  {result['advisory_only']}")


if __name__ == "__main__":
    main()
