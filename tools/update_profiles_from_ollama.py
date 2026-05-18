#!/usr/bin/env python3
"""
Update local_llm_profiles.json based on currently available Ollama models.

Scans `ollama list`, matches models to profiles using keyword heuristics,
and writes an updated profiles.json. Existing manual overrides are preserved
unless --reset is used.

Usage:
    python tools/update_profiles_from_ollama.py
    python tools/update_profiles_from_ollama.py --dry-run
    python tools/update_profiles_from_ollama.py --reset
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"

SKIP_SUFFIXES = ["-original", "-agentprefill", "-toolfix", "-agent"]

PROFILE_SPECS = {
    "fast_summary": {
        "keywords": ["gemma-4-e4b", "gemma4:e4b", "qwen3.5-9b", "qwen3.5-7b",
                      "minicpm", "glm-4.7-flash", "gpt-oss-20b", "deepseek-ocr"],
        "prefer_small": True,
        "temperature": 0.2,
        "max_chars": 60000,
        "max_output_chars": 3000,
        "use_for": ["summarize-file", "summarize-tree", "rewrite-text"],
        "risk_level": "low",
    },
    "code_worker": {
        "keywords": ["coder-next", "qwen3-coder-next", "qwen3-coder:30b",
                      "qwen3-coder", "codestral", "deepseek-coder"],
        "prefer_small": False,
        "temperature": 0.15,
        "max_chars": 90000,
        "max_output_chars": 4000,
        "use_for": ["extract-todos", "find-related-files", "generate-test-plan", "generate-test-draft"],
        "risk_level": "medium",
    },
    "diff_reviewer": {
        "keywords": ["coder-next-agent", "qwen3-coder-next-q8-agent",
                      "qwen3-coder-next", "qwen3.6:27b", "qwen3.5-35b",
                      "qwen3.5-27b", "mistral-small-24b"],
        "prefer_small": False,
        "temperature": 0.1,
        "max_chars": 120000,
        "max_output_chars": 5000,
        "use_for": ["review-diff"],
        "risk_level": "medium",
    },
    "deep_reviewer": {
        "keywords": ["mistral-medium", "mistral-small-4", "qwen3.5-35b",
                      "llama4", "nemotron-3-super", "gemma-4-31b",
                      "command-r", "gpt-oss-120b", "qwen3.5-122b",
                      "qwen3.6:35b"],
        "prefer_small": False,
        "temperature": 0.1,
        "max_chars": 160000,
        "max_output_chars": 6000,
        "use_for": ["deep-code-review"],
        "risk_level": "high",
    },
    "architecture_reviewer": {
        "keywords": ["mistral-medium-3.5", "mistral-small-4-119b",
                      "nemotron-3-super", "qwen3.5-35b", "qwen3.6:35b",
                      "gpt-oss-120b", "command-r", "llama4"],
        "prefer_small": False,
        "temperature": 0.1,
        "max_chars": 160000,
        "max_output_chars": 6000,
        "use_for": ["architecture-review"],
        "risk_level": "high",
    },
    "reasoning_checker": {
        "keywords": ["deepseek-r1-distill-llama", "deepseek-r1-distill",
                      "qwen3.5-27b-reasoning", "nemotron-3-nano-omni",
                      "nvidia-nemotron", "nemotron-3-super",
                      "qwq", "deepseek-r1:671b"],
        "prefer_small": False,
        "temperature": 0.1,
        "max_chars": 100000,
        "max_output_chars": 5000,
        "use_for": ["risk-analysis", "logic-check", "failure-mode-analysis"],
        "risk_level": "medium-high",
    },
    "release_auditor": {
        "keywords": ["qwen3.6:27b", "qwen3.5-35b", "mistral-medium",
                      "mistral-small-4", "gemma-4-31b", "command-r",
                      "nemotron-3-super", "qwen3-coder-next"],
        "prefer_small": False,
        "temperature": 0.1,
        "max_chars": 140000,
        "max_output_chars": 6000,
        "use_for": ["deep-code-review", "architecture-review", "risk-analysis"],
        "risk_level": "high",
    },
    "translation": {
        "keywords": ["translategemma", "glm-4.7-flash", "glm-4",
                      "qwen3.5-9b", "qwen3.6:27b", "gemma4:26b",
                      "aya", "nllb", "seamless"],
        "prefer_small": False,
        "temperature": 0.2,
        "max_chars": 80000,
        "max_output_chars": 6000,
        "use_for": ["translate-text"],
        "risk_level": "low",
    },
    "embedding": {
        "keywords": ["nomic-embed", "bge-m3", "bge-large",
                      "e5-mistral", "gte-large", "stella"],
        "prefer_small": True,
        "temperature": 0.0,
        "max_chars": 32000,
        "max_output_chars": 0,
        "use_for": ["embedding"],
        "risk_level": "low",
    },
}


def get_ollama_models() -> list[str]:
    try:
        output = subprocess.check_output(
            ["ollama", "list"], text=True, stderr=subprocess.DEVNULL
        )
        lines = output.strip().splitlines()[1:]
        return [line.split()[0] for line in lines if line.strip()]
    except Exception as e:
        print(f"ERROR: Cannot run ollama list: {e}", file=sys.stderr)
        return []


def is_variant(name: str) -> bool:
    for suffix in SKIP_SUFFIXES:
        if name.endswith(suffix) or name.endswith(f"{suffix}:latest"):
            return True
    return False


def filter_base_models(models: list[str]) -> list[str]:
    return [m for m in models if not is_variant(m)]


def estimate_size(name: str) -> float:
    match = re.search(r"(\d+\.?\d*)[bB]", name)
    if match:
        return float(match.group(1))
    return 30.0


def match_model(profile_name: str, spec: dict, base_models: list[str]) -> str | None:
    candidates = []
    for model in base_models:
        model_lower = model.lower()
        for kw in spec["keywords"]:
            if kw.lower() in model_lower:
                candidates.append(model)
                break

    if not candidates:
        return None

    if spec.get("prefer_small"):
        candidates.sort(key=lambda n: estimate_size(n))
    else:
        candidates.sort(key=lambda n: estimate_size(n), reverse=True)

    return candidates[0]


def auto_tune_recommendations(existing_profiles: dict, all_models: list[str],
                               base_models: list[str]) -> list[dict]:
    """Compare _health data between current profile models and available candidates.

    Returns a list of recommendation dicts with keys:
        profile, current_model, current_latency, candidate, candidate_latency, improvement_pct
    """
    recs = []
    for profile_name, spec in PROFILE_SPECS.items():
        current = existing_profiles.get(profile_name, {})
        current_model = current.get("model", "")
        h = current.get("_health", {})
        current_latency = h.get("avg_latency_s")
        if current_latency is None:
            continue

        # Find candidate models for this profile among available base models
        candidates = []
        for model in base_models:
            model_lower = model.lower()
            for kw in spec["keywords"]:
                if kw.lower() in model_lower and model != current_model:
                    candidates.append(model)
                    break

        # Check each candidate's health data in existing profiles
        for cand_model in candidates:
            # Look for health data across ALL profiles (a candidate might be the
            # primary model of a different profile)
            cand_health = None
            for ep_name, ep_data in existing_profiles.items():
                if ep_data.get("model") == cand_model:
                    cand_health = ep_data.get("_health", {})
                    break
            cand_latency = cand_health.get("avg_latency_s") if cand_health else None
            if cand_latency is None:
                continue
            if cand_health.get("success_rate", 0) < 0.8:
                continue  # Unreliable candidate

            if cand_latency < current_latency:
                pct = (current_latency - cand_latency) / current_latency * 100
                recs.append({
                    "profile": profile_name,
                    "current_model": current_model,
                    "current_latency": current_latency,
                    "current_success": h.get("success_rate", 1.0),
                    "candidate": cand_model,
                    "candidate_latency": cand_latency,
                    "candidate_success": cand_health.get("success_rate", 1.0),
                    "improvement_pct": round(pct, 1),
                })
                break  # Only report the first better candidate per profile
    recs.sort(key=lambda r: r["improvement_pct"], reverse=True)
    return recs


def main():
    parser = argparse.ArgumentParser(description="Update profiles.json from Ollama models")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--reset", action="store_true", help="Ignore existing profiles, regenerate from scratch")
    parser.add_argument("--auto-tune", action="store_true",
                        help="Use _health data to recommend model swaps when candidates have better latency")
    parser.add_argument("--apply", action="store_true",
                        help="Apply auto-tune recommendations with >20%% improvement (requires --auto-tune)")
    args = parser.parse_args()

    if args.apply and not args.auto_tune:
        print("Error: --apply requires --auto-tune")
        sys.exit(2)

    all_models = get_ollama_models()
    if not all_models:
        print("No Ollama models found. Is Ollama running?")
        sys.exit(1)

    base_models = filter_base_models(all_models)
    print(f"Found {len(all_models)} models ({len(base_models)} base models)\n")

    existing = {}
    if PROFILES_PATH.exists() and not args.reset:
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        existing = data.get("profiles", {})

    # Start from existing profiles (preserving all manual entries like smart_summary,
    # qwen3.6_27b_mtp, gemma4_26b, etc.) and only update the PROFILE_SPECS entries.
    new_profiles = dict(existing) if not args.reset else {}
    changes = []

    for profile_name, spec in PROFILE_SPECS.items():
        recommended = match_model(profile_name, spec, base_models)
        old_model = existing.get(profile_name, {}).get("model", "")

        if old_model and old_model in all_models and not args.reset:
            chosen = old_model
            status = "KEEP"
        elif recommended:
            chosen = recommended
            status = "UPDATE" if old_model else "NEW"
        else:
            chosen = old_model or ""
            status = "NO MATCH"

        # Update only the spec-managed fields; preserve everything else (_health, _env, etc.)
        entry = new_profiles.get(profile_name, {})
        entry["model"] = chosen
        entry["temperature"] = spec["temperature"]
        entry["max_chars"] = spec["max_chars"]
        entry["max_output_chars"] = spec["max_output_chars"]
        # Preserve existing use_for if profile already exists, otherwise use spec
        if profile_name not in existing:
            entry["use_for"] = spec["use_for"]
        elif "use_for" not in entry:
            entry["use_for"] = spec["use_for"]
        entry["risk_level"] = spec["risk_level"]
        new_profiles[profile_name] = entry

        icon = {"KEEP": "  ", "UPDATE": "->", "NEW": " +", "NO MATCH": " !"}[status]
        old_str = f" (was: {old_model})" if old_model and status == "UPDATE" else ""
        print(f"  {icon} {profile_name:20s} = {chosen or '(none)'}{old_str}")
        changes.append((profile_name, status, old_model, chosen))

    output = {
        "profiles": new_profiles,
        "default_profile": data.get("default_profile", "fast_summary") if not args.reset else "fast_summary",
    }
    # Preserve _backends and _notes metadata when not resetting
    if not args.reset:
        if "_backends" in data:
            output["_backends"] = data["_backends"]
        if "_notes" in data:
            output["_notes"] = data["_notes"]

    updates = sum(1 for _, s, _, _ in changes if s in ("UPDATE", "NEW"))
    keeps = sum(1 for _, s, _, _ in changes if s == "KEEP")
    missing = sum(1 for _, s, _, _ in changes if s == "NO MATCH")

    print(f"\n{updates} updated, {keeps} kept, {missing} unmatched")

    # Auto-tune: health-aware model swap recommendations
    if args.auto_tune:
        existing_full = {}
        if PROFILES_PATH.exists():
            data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
            existing_full = data.get("profiles", {})
        recs = auto_tune_recommendations(existing_full, all_models, base_models)
        if recs:
            print(f"\n--- Auto-Tune Recommendations ({len(recs)}) ---")
            print(f"{'Profile':<22s} {'Current':<30s} {'Lat':>6s} → {'Candidate':<30s} {'Lat':>6s} {'Better':>7s} {'Action':>10s}")
            print("-" * 125)
            applied_count = 0
            for r in recs:
                action = ""
                if args.apply and r["improvement_pct"] > 20:
                    new_profiles[r["profile"]]["model"] = r["candidate"]
                    action = "APPLIED"
                    applied_count += 1
                elif args.apply:
                    action = "skipped"
                else:
                    action = "manual"
                print(f"  {r['profile']:<20s} {r['current_model']:<30s} {r['current_latency']:>5.1f}s → "
                      f"{r['candidate']:<30s} {r['candidate_latency']:>5.1f}s {r['improvement_pct']:>6.1f}% {action:>10s}")
            if args.apply and applied_count:
                print(f"\n  {applied_count} recommendation(s) auto-applied (improvement >20%).")
            elif args.apply:
                print("\n  No recommendations met the >20% threshold for auto-apply.")
            if not args.apply:
                print("\nTo apply: re-run with --apply to auto-apply recommendations with >20% improvement.")
        else:
            print("\n--- Auto-Tune: No improvements found. All profiles use optimal models. ---")

    if args.dry_run:
        print("\nDRY RUN — no files written.")
        print("\nWould write:")
        print(json.dumps(output, indent=2, ensure_ascii=False)[:500] + "...")
    else:
        PROFILES_PATH.write_text(
            json.dumps(output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        print(f"\nWritten: {PROFILES_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
