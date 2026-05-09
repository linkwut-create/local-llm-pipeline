#!/usr/bin/env python3
"""
Versioned prompt registry. Loads prompts from tools/prompts/.

Usage:
    from local_llm_prompt_registry import load_prompt
    prompt = load_prompt("summarize-file")
    # prompt.text, prompt.version, prompt.hash, prompt.prompt_id
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REGISTRY_PATH = SCRIPT_DIR / "prompts" / "registry.json"
PROMPTS_DIR = SCRIPT_DIR / "prompts"

_registry_cache: dict | None = None


@dataclass
class Prompt:
    prompt_id: str
    version: str
    hash: str
    text: str


def _load_registry() -> dict:
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return _registry_cache


def compute_prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def list_prompts() -> list[str]:
    return sorted(_load_registry()["prompts"].keys())


def load_prompt(task: str) -> Prompt | None:
    """Load a prompt by task name. Returns None if not found."""
    registry = _load_registry()
    entry = registry["prompts"].get(task)
    if not entry:
        return None

    prompt_file = PROMPTS_DIR / entry["file"]
    if not prompt_file.exists():
        return None

    text = prompt_file.read_text(encoding="utf-8")
    return Prompt(
        prompt_id=entry["prompt_id"],
        version=entry["version"],
        hash=compute_prompt_hash(text),
        text=text,
    )


def validate_registry() -> list[str]:
    """Validate all prompts. Returns list of errors."""
    errors = []
    try:
        registry = _load_registry()
    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
        return [f"registry.json: {e}"]

    if registry.get("schema_version") != 1:
        errors.append("registry.json: unsupported schema_version")

    for task, entry in registry.get("prompts", {}).items():
        prompt_file = PROMPTS_DIR / entry["file"]
        if not prompt_file.exists():
            errors.append(f"prompt '{task}': file '{entry['file']}' not found")
            continue

        text = prompt_file.read_text(encoding="utf-8")
        if not text.strip():
            errors.append(f"prompt '{task}': file is empty")

        actual_hash = compute_prompt_hash(text)
        stored_hash = entry.get("hash", "")
        if actual_hash != stored_hash:
            errors.append(
                f"prompt '{task}': hash mismatch "
                f"(stored={stored_hash[:8]}, actual={actual_hash[:8]})"
            )

        # Safety checks for draft tasks
        is_draft = task.startswith("draft-") or task == "suggest-improvements"
        if is_draft:
            lower = text.lower()
            if "do not modify source files" not in lower:
                errors.append(
                    f"prompt '{task}': draft prompt missing "
                    f"'do NOT modify source files' directive"
                )

    return errors
