#!/usr/bin/env python3
"""
Validate local_llm_profiles.json and local_llm_tasks.json schema.

Detects config errors before they cause silent runtime failures.
Exit code 0 = valid, 1 = errors found, 2 = file not found / unreadable.

Usage:
    python tools/validate_configs.py
    python tools/validate_configs.py --json
    python tools/validate_configs.py --quiet
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"
TASKS_PATH = SCRIPT_DIR / "local_llm_tasks.json"

VALID_RISK_LEVELS = {"low", "medium", "medium-high", "high"}

DRAFT_TASKS = {"draft-fix", "draft-feature", "draft-refactor", "suggest-improvements"}

CODE_GENERATION_TASKS = {
    "generate-test-plan", "generate-test-draft", "review-diff",
    "deep-code-review", "draft-fix", "draft-feature", "draft-refactor",
    "suggest-improvements", "extract-todos",
}

HIGH_RISK_TASKS = {
    "release-risk-review", "architecture-review", "deep-code-review",
    "debate-architecture-review", "debate-risk-analysis",
}

REQUIRED_PROFILE_FIELDS = {"model", "risk_level", "use_for"}

REQUIRED_TASK_FIELDS = {
    "risk", "default_profile", "may_modify_code",
    "controller_must_verify", "max_output_chars",
    "allowed_use", "forbidden_use",
}


def load_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except FileNotFoundError:
        return None, f"File not found: {path}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in {path}: {e}"


def validate_profiles(profiles_data: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    profiles = profiles_data.get("profiles", {})
    if not profiles:
        errors.append("profiles.json: no profiles defined")
        return errors

    seen_models: dict[str, str] = {}
    warnings: list[str] = []
    for name, conf in profiles.items():
        prefix = f"profile '{name}'"

        for field in REQUIRED_PROFILE_FIELDS:
            if field not in conf:
                errors.append(f"{prefix}: missing required field '{field}'")

        model = conf.get("model", "")
        if not model or not isinstance(model, str) or not model.strip():
            errors.append(f"{prefix}: 'model' is empty or not a string")
        elif model in seen_models:
            warnings.append(
                f"{prefix}: model '{model}' also used by {seen_models[model]} (allowed but verify intent)"
            )
        else:
            seen_models[model] = f"profile '{name}'"

        risk = conf.get("risk_level", "")
        if not isinstance(risk, str) or risk not in VALID_RISK_LEVELS:
            errors.append(
                f"{prefix}: invalid risk_level '{risk}' "
                f"(must be one of: {', '.join(sorted(VALID_RISK_LEVELS))})"
            )

        use_for = conf.get("use_for", [])
        if not isinstance(use_for, list):
            errors.append(f"{prefix}: 'use_for' must be a list")
        elif name == "embedding" and use_for:
            bad_uses = [t for t in use_for if t in CODE_GENERATION_TASKS]
            if bad_uses:
                errors.append(
                    f"{prefix}: embedding profile must not be used for "
                    f"code generation tasks: {bad_uses}"
                )

        # Prevent MTP drafter / assistant models from being used as standalone profiles
        model_lower = model.lower()
        drafter_keywords = ["assistant", "drafter", "mtp-head", "draft-model"]
        if any(kw in model_lower for kw in drafter_keywords):
            errors.append(
                f"{prefix}: model '{model}' appears to be an MTP drafter / "
                f"assistant model — it must not be used as a standalone profile model. "
                f"Use it as _acceleration._drafter in the backend config instead."
            )

        temp = conf.get("temperature")
        if temp is not None and not isinstance(temp, (int, float)):
            errors.append(f"{prefix}: 'temperature' must be a number")

    return errors, warnings


def validate_tasks(tasks_data: dict, profiles: dict) -> list[str]:
    errors = []
    tasks = tasks_data.get("tasks", {})
    if not tasks:
        errors.append("tasks.json: no tasks defined")
        return errors

    profile_names = set(profiles.keys())

    for name, conf in tasks.items():
        prefix = f"task '{name}'"

        for field in REQUIRED_TASK_FIELDS:
            if field not in conf:
                errors.append(f"{prefix}: missing required field '{field}'")

        default_profile = conf.get("default_profile", "")
        if default_profile and default_profile not in profile_names:
            errors.append(
                f"{prefix}: default_profile '{default_profile}' "
                f"does not exist in profiles.json"
            )

        may_modify = conf.get("may_modify_code")
        if may_modify is True:
            errors.append(
                f"{prefix}: may_modify_code must be false "
                f"(local models must never modify source files)"
            )
        if name in DRAFT_TASKS and may_modify is not False:
            errors.append(
                f"{prefix}: draft task must have may_modify_code=false"
            )

        must_verify = conf.get("controller_must_verify")
        if must_verify is False:
            if name in DRAFT_TASKS:
                errors.append(
                    f"{prefix}: draft task must have controller_must_verify=true"
                )
            if name in HIGH_RISK_TASKS or conf.get("risk") == "high":
                errors.append(
                    f"{prefix}: high-risk task must have controller_must_verify=true"
                )

        risk = conf.get("risk", "")
        if risk not in VALID_RISK_LEVELS:
            errors.append(
                f"{prefix}: invalid risk '{risk}' "
                f"(must be one of: {', '.join(sorted(VALID_RISK_LEVELS))})"
            )

    return errors


def validate_prompt_registry() -> list[str]:
    try:
        from local_llm_prompt_registry import validate_registry
        return validate_registry()
    except ImportError:
        return ["prompt registry module not importable"]
    except Exception as e:
        return [f"prompt registry validation error: {e}"]


def validate_task_prompt_coverage(tasks_data: dict) -> list[str]:
    """Ensure non-debate tasks have a corresponding prompt registry entry."""
    import json as _json
    errors = []
    registry_path = SCRIPT_DIR / "prompts" / "registry.json"
    if not registry_path.exists():
        return ["prompts/registry.json not found — cannot check coverage"]

    try:
        registry = _json.loads(registry_path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as e:
        return [f"prompts/registry.json invalid: {e}"]

    prompt_ids = {entry.get("prompt_id", task_name)
                  for task_name, entry in registry.get("prompts", {}).items()}

    # Tasks that don't need their own prompt (internal / composite / CLI-only)
    exempt = {
        "local_check",  # no LLM call
    }

    tasks = tasks_data.get("tasks", {})
    for task_name in tasks:
        # Debate tasks are exempt — they go through local_llm_debate.py
        if task_name.startswith("debate-"):
            continue
        if task_name in exempt:
            continue
        if task_name not in prompt_ids:
            errors.append(
                f"task '{task_name}': no prompt registry entry found"
            )

    return errors


def main() -> int:
    args = sys.argv[1:]
    quiet = "--quiet" in args
    json_output = "--json" in args

    profiles_data, profiles_err = load_json(PROFILES_PATH)
    if profiles_err:
        if not quiet:
            print(f"ERROR: {profiles_err}", file=sys.stderr)
        return 2

    tasks_data, tasks_err = load_json(TASKS_PATH)
    if tasks_err:
        if not quiet:
            print(f"ERROR: {tasks_err}", file=sys.stderr)
        return 2

    profile_errors, profile_warnings = validate_profiles(profiles_data)
    task_errors = validate_tasks(tasks_data, profiles_data.get("profiles", {}))
    prompt_errors = validate_prompt_registry()
    coverage_errors = validate_task_prompt_coverage(tasks_data)

    all_errors = profile_errors + task_errors + prompt_errors + coverage_errors
    all_warnings = profile_warnings
    profile_count = len(profiles_data.get("profiles", {}))
    task_count = len(tasks_data.get("tasks", {}))

    if json_output:
        result = {
            "ok": len(all_errors) == 0,
            "profiles_count": profile_count,
            "tasks_count": task_count,
            "errors": all_errors,
            "warnings": all_warnings,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    if not quiet:
        print(f"Validating: {PROFILES_PATH.name} ({profile_count} profiles)")
        print(f"           {TASKS_PATH.name} ({task_count} tasks)")
        print(f"           prompts/registry.json")
        print()

        if all_warnings:
            for w in all_warnings:
                print(f"  WARN: {w}")
        if all_errors:
            for e in all_errors:
                print(f"  FAIL: {e}")
            print(f"\n{len(all_errors)} error(s) found")
        else:
            status = f"{len(all_warnings)} warning(s)" if all_warnings else "clean"
            print(f"  PASS: all config schema checks passed ({status})")

    return 0 if not all_errors else 1


if __name__ == "__main__":
    sys.exit(main())
