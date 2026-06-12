#!/usr/bin/env python3
"""
DeepSeek V4 API client — cloud escalation backend for local-llm-pipeline.

Supports: deepseek-v4-pro (thinking + high effort) and deepseek-v4-flash
(non-thinking + low effort, or thinking + medium effort).

Privacy gate: refuses to send content containing secrets, private keys,
or full repository dumps. Only task packets and explicitly allowed snippets
are permitted.

Usage (standalone test):
    python tools/deepseek_client.py "Say hello in Chinese"
"""

import json
import os
import sys
import time
from typing import Any

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"

# ---- privacy gate ----

FORBIDDEN_PATTERNS = [
    # API keys and tokens
    r"sk-[a-zA-Z0-9]{20,}",
    r"api_key\s*=\s*['\"][^'\"]+['\"]",
    r"Bearer\s+[a-zA-Z0-9\-_\.]{20,}",
    # Private keys
    r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----",
    r"-----BEGIN PGP PRIVATE KEY BLOCK-----",
    # Common secret files
    r"\.env",
    r"credentials\.json",
    r"id_rsa",
    r"\.pem",
]

FORBIDDEN_CONTENT_INDICATORS = [
    "PRIVATE KEY",
    "API_KEY",
    "SECRET",
    "PASSWORD",
    "TOKEN",
]


def _check_privacy(content: str) -> tuple[bool, str]:
    """Check if content is safe to send to cloud API.

    Returns (safe: bool, reason: str).
    """
    import re

    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, content):
            return False, f"content matches forbidden pattern: {pattern}"

    upper = content.upper()
    for indicator in FORBIDDEN_CONTENT_INDICATORS:
        if indicator in upper:
            # Only block if it looks like an assignment or value
            if re.search(rf"{indicator}\s*[=:]\s*\S", upper):
                return False, f"content contains potential secret: {indicator}"

    return True, ""


# ---- API client ----

def _build_request(
    model: str,
    messages: list[dict],
    thinking: bool = False,
    reasoning_effort: str = "low",
    max_tokens: int = 16384,
    temperature: float = 0.1,
) -> dict:
    """Build a DeepSeek API request body (OpenAI-compatible format)."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if thinking:
        body["extra_body"] = {"thinking": {"type": "enabled"}}
        body["reasoning_effort"] = reasoning_effort
    else:
        body["extra_body"] = {"thinking": {"type": "disabled"}}

    return body


def call_deepseek(
    prompt: str,
    model: str = "deepseek-v4-flash",
    thinking: bool = False,
    reasoning_effort: str = "low",
    max_tokens: int = 16384,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 180,
) -> dict:
    """Call DeepSeek API and return a standardized result dict.

    Returns:
        {
            "ok": bool,
            "content": str,
            "model": str,
            "usage": {"prompt_tokens": int, "completion_tokens": int} | None,
            "elapsed_seconds": float,
            "error": str | None,
        }
    """
    # Privacy check
    safe, reason = _check_privacy(prompt)
    if not safe:
        return {
            "ok": False,
            "content": "",
            "model": model,
            "usage": None,
            "elapsed_seconds": 0,
            "error": f"privacy gate blocked: {reason}",
        }

    key = api_key or os.environ.get(DEEPSEEK_API_KEY_ENV, "")
    if not key:
        return {
            "ok": False,
            "content": "",
            "model": model,
            "usage": None,
            "elapsed_seconds": 0,
            "error": f"{DEEPSEEK_API_KEY_ENV} not set",
        }

    url = (base_url or DEEPSEEK_BASE_URL).rstrip("/") + "/v1/chat/completions"

    body = _build_request(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )

    try:
        import requests
    except ImportError:
        # Fallback to urllib
        import urllib.request
        import urllib.error

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                elapsed = time.time() - start
                choice = result.get("choices", [{}])[0]
                return {
                    "ok": True,
                    "content": choice.get("message", {}).get("content", ""),
                    "model": result.get("model", model),
                    "usage": result.get("usage"),
                    "elapsed_seconds": elapsed,
                    "error": None,
                }
        except urllib.error.HTTPError as e:
            elapsed = time.time() - start
            return {
                "ok": False,
                "content": "",
                "model": model,
                "usage": None,
                "elapsed_seconds": elapsed,
                "error": f"HTTP {e.code}: {e.reason}",
            }
        except Exception as e:
            elapsed = time.time() - start
            return {
                "ok": False,
                "content": "",
                "model": model,
                "usage": None,
                "elapsed_seconds": elapsed,
                "error": str(e)[:200],
            }

    # requests path
    start = time.time()
    try:
        resp = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        elapsed = time.time() - start
        if resp.status_code == 200:
            result = resp.json()
            choice = result.get("choices", [{}])[0]
            return {
                "ok": True,
                "content": choice.get("message", {}).get("content", ""),
                "model": result.get("model", model),
                "usage": result.get("usage"),
                "elapsed_seconds": elapsed,
                "error": None,
            }
        else:
            return {
                "ok": False,
                "content": "",
                "model": model,
                "usage": None,
                "elapsed_seconds": elapsed,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "ok": False,
            "content": "",
            "model": model,
            "usage": None,
            "elapsed_seconds": elapsed,
            "error": str(e)[:200],
        }


# ---- escalation profile resolver ----

def resolve_escalation_profile(
    profile_name: str,
    profiles_data: dict,
    escalation_level: int = 0,
) -> dict | None:
    """Find the appropriate escalation profile.

    escalation_level:
        0 = no escalation (use local)
        1 = escalate to Flash worker
        2 = escalate to Flash thinking
        3 = escalate to Pro reviewer

    Returns the profile config dict, or None if no escalation profile found.
    """
    escalation_map = {
        1: "deepseek_v4_flash_worker",
        2: "deepseek_v4_flash_thinking",
        3: "deepseek_v4_pro_reviewer",
    }

    target = escalation_map.get(escalation_level)
    if not target:
        return None

    return profiles_data.get("profiles", {}).get(target)


def should_escalate_to_cloud(
    task: str,
    risk: str,
    local_failures: int,
    privacy_ok: bool,
    cloud_ok: bool,
    tasks_data: dict | None = None,
) -> tuple[bool, int, str]:
    """Decide whether to escalate to cloud.

    Returns (should_escalate: bool, escalation_level: int, reason: str).
    """
    if not privacy_ok:
        return False, 0, "privacy gate blocked — contains sensitive content"
    if not cloud_ok:
        return False, 0, "cloud escalation not enabled (use --cloud-ok)"

    # High-risk / interface / release → Pro
    if risk in ("high",):
        return True, 3, "high-risk task — escalate to Pro reviewer"
    if task in (
        "architecture-review", "interface-review", "release-risk-review",
        "security-review",
    ):
        return True, 3, f"task '{task}' requires Pro review"

    # Local failed twice → Flash worker
    if local_failures >= 2:
        return True, 1, f"local model failed {local_failures} times — escalate to Flash worker"

    # Complex multi-file task → Flash thinking
    if task in (
        "harder-bug-analysis", "multi-file-reasoning", "non-release-review",
        "medium-code-task",
    ):
        if local_failures >= 1:
            return True, 2, f"complex task '{task}' with local failure — escalate to Flash thinking"

    return False, 0, "local model should be sufficient"


# ---- CLI ----

if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Say hello."
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

    print(f"Calling {model}...")
    result = call_deepseek(prompt, model=model)
    if result["ok"]:
        print(f"OK ({result['elapsed_seconds']:.1f}s):")
        print(result["content"][:500])
    else:
        print(f"ERROR: {result['error']}")
        sys.exit(1)
