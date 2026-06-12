#!/usr/bin/env python3
"""
Score Model Audition results and generate role recommendations.
Reads JSONL result files from evals/model_audition/results/.

Usage:
    py -3 tools/score_model_audition.py results/*.jsonl
    py -3 tools/score_model_audition.py --all
    py -3 tools/score_model_audition.py results/20260612-qwen3-coder-30b.jsonl --report
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
EVALS_DIR = SCRIPT_DIR.parent / "evals" / "model_audition"
RESULTS_DIR = EVALS_DIR / "results"
REPORTS_DIR = EVALS_DIR / "reports"
RUBRIC_PATH = EVALS_DIR / "rubric.yaml"

# ── Fallback rubric (used if YAML unavailable) ──
FALLBACK_RUBRIC = {
    "dimensions": {
        "correctness": {"weight": 2.0},
        "completeness": {"weight": 1.5},
        "instruction_following": {"weight": 2.0},
        "format_discipline": {"weight": 1.2},
        "hallucination_control": {"weight": 2.0},
        "risk_awareness": {"weight": 1.5},
        "usefulness": {"weight": 1.5},
    },
    "role_mapping": {
        "fast_summary": {"cases": ["001", "002"], "required_min_avg": 3.8},
        "task_bootstrapper": {"cases": ["001", "002", "006"], "required_min_avg": 4.0},
        "code_worker": {"cases": ["004", "006", "007"], "required_min_avg": 4.0},
        "test_agent": {"cases": ["007", "004"], "required_min_avg": 3.8},
        "diff_reviewer": {"cases": ["005", "008", "009"], "required_min_avg": 4.0},
        "deep_reviewer": {"cases": ["003", "005", "008", "011"], "required_min_avg": 4.3},
        "interface_reviewer": {"cases": ["004", "008", "011"], "required_min_avg": 4.2},
        "release_auditor": {"cases": ["005", "010", "011"], "required_min_avg": 4.3},
        "docs_agent": {"cases": ["001", "009"], "required_min_avg": 4.0},
        "translation": {"cases": ["012"], "required_min_avg": 4.0},
    },
}


def load_rubric() -> dict:
    if RUBRIC_PATH.exists():
        try:
            import yaml
            return yaml.safe_load(RUBRIC_PATH.read_text())
        except ImportError:
            pass
    return FALLBACK_RUBRIC


def load_results(paths: list[str]) -> list[dict]:
    results = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
    return results


def auto_score(result: dict) -> dict:
    """Heuristic auto-scoring based on deterministic checks."""
    output = result.get("raw_output", "")
    scores = {}

    # correctness: output is non-empty and contains relevant markers
    scores["correctness"] = 1 if not output else 3  # base score
    if output and len(output) > 100:
        scores["correctness"] = min(5, scores["correctness"] + 1)

    # completeness: has multiple sections
    sections = len([l for l in output.split("\n") if l.startswith("##") or l.startswith("# ")])
    scores["completeness"] = min(5, max(1, sections // 2))

    # instruction_following: output follows requested format
    fmt_keywords = ["verdict", "block", "pass", "files to read", "files to modify"]
    fmt_matches = sum(1 for kw in fmt_keywords if kw in output.lower())
    scores["instruction_following"] = min(5, max(1, fmt_matches))

    # format_discipline: use of markdown structure
    has_headers = 1 if "##" in output else 0
    has_lists = 1 if "- " in output or "* " in output else 0
    has_code = 1 if "```" in output else 0
    scores["format_discipline"] = min(5, 1 + has_headers + has_lists + has_code)

    # hallucination_control: no obvious fabricated paths
    import re
    fabricated = len(re.findall(r"tools/[a-z_]+\.py", output))
    fabricated -= len(re.findall(r"(local_llm_mcp_server|local_llm_router|local_llm_worker|"
                                  r"deepseek_client|call_ledger|validate_configs)", output))
    scores["hallucination_control"] = 5 if fabricated <= 1 else max(1, 5 - fabricated)

    # risk_awareness: mentions risks, tests, or rollback
    risk_markers = sum(1 for kw in ["risk", "test", "rollback", "do not", "block"]
                       if kw in output.lower())
    scores["risk_awareness"] = min(5, max(1, risk_markers))

    # usefulness: length and structure
    scores["usefulness"] = min(5, max(1, len(output) // 500))

    return scores


def compute_role_fit(scores: dict, rubric: dict) -> dict:
    """Compute role suitability based on case scores."""
    role_signals = {}
    role_mapping = rubric.get("role_mapping", FALLBACK_RUBRIC["role_mapping"])

    for role, config in role_mapping.items():
        relevant_scores = []
        for case_id in config["cases"]:
            if case_id in scores:
                avg = sum(scores[case_id].values()) / max(len(scores[case_id]), 1)
                relevant_scores.append(avg)
        if relevant_scores:
            avg_score = sum(relevant_scores) / len(relevant_scores)
            role_signals[role] = round(avg_score, 1)

    return role_signals


def recommend_roles(role_signals: dict, rubric: dict) -> dict:
    """Recommend best, secondary, and avoid roles."""
    role_mapping = rubric.get("role_mapping", FALLBACK_RUBRIC["role_mapping"])
    sorted_roles = sorted(role_signals.items(), key=lambda x: x[1], reverse=True)

    recommendations = {"best": [], "secondary": [], "avoid": []}
    for role, score in sorted_roles:
        threshold = role_mapping.get(role, {}).get("required_min_avg", 4.0)
        if score >= threshold:
            if not recommendations["best"] or score >= sorted_roles[0][1] - 0.3:
                recommendations["best"].append({"role": role, "score": score})
            else:
                recommendations["secondary"].append({"role": role, "score": score})
        elif score >= threshold - 1.0:
            recommendations["secondary"].append({"role": role, "score": score})
        else:
            recommendations["avoid"].append({"role": role, "score": score})

    return recommendations


def generate_report(all_scored: list[dict], report_path: Path | None = None) -> str:
    """Generate a Markdown report from scored results."""
    lines = []
    lines.append("# Model Audition Report")
    lines.append(f"\nDate: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Models Tested: {len(all_scored)}")
    lines.append("")

    # Summary table
    lines.append("## Summary Ranking\n")
    lines.append("| Model | Best Role | Score | Secondary | Avoid |")
    lines.append("|---|---|---|---|---|")
    for r in sorted(all_scored, key=lambda x: x.get("best_score", 0), reverse=True):
        model = r["model"]
        best = r["recommendations"]["best"]
        secondary = r["recommendations"]["secondary"]
        avoid = r["recommendations"]["avoid"]
        best_str = ", ".join(f"{b['role']}({b['score']})" for b in best[:2]) or "-"
        sec_str = ", ".join(f"{s['role']}" for s in secondary[:2]) or "-"
        avoid_str = ", ".join(f"{a['role']}" for a in avoid[:2]) or "-"
        lines.append(f"| {model} | {best_str} | {r.get('best_score', '-')} | {sec_str} | {avoid_str} |")

    # Per-model
    lines.append("\n## Per-Model Recommendations\n")
    for r in all_scored:
        lines.append(f"### {r['model']}\n")
        recs = r["recommendations"]
        if recs["best"]:
            lines.append("**Recommended Roles:**")
            for b in recs["best"]:
                lines.append(f"- {b['role']} (score: {b['score']})")
        if recs["secondary"]:
            lines.append("\n**Possible (with supervision):**")
            for s in recs["secondary"]:
                lines.append(f"- {s['role']} (score: {s['score']})")
        if recs["avoid"]:
            lines.append("\n**Avoid:**")
            for a in recs["avoid"]:
                lines.append(f"- {a['role']} (score: {a['score']})")

        # Evidence from cases
        lines.append("\n**Evidence:**")
        for case_id, case_scores in sorted(r.get("case_scores", {}).items()):
            avg = sum(case_scores.values()) / max(len(case_scores), 1)
            lines.append(f"- Case {case_id}: avg {avg:.1f} — "
                         f"correctness={case_scores.get('correctness','?')}, "
                         f"usefulness={case_scores.get('usefulness','?')}")
        lines.append("")

    # Role assignments
    lines.append("## Suggested Role Assignments\n")
    lines.append("| Role | Primary | Backup |")
    lines.append("|---|---|")
    role_primary = {}
    for r in all_scored:
        for b in r["recommendations"]["best"]:
            role_primary.setdefault(b["role"], []).append((r["model"], b["score"]))
    for role in sorted(role_primary):
        ranked = sorted(role_primary[role], key=lambda x: x[1], reverse=True)
        primary = ranked[0][0] if ranked else "-"
        backup = ranked[1][0] if len(ranked) > 1 else "-"
        lines.append(f"| {role} | {primary} | {backup} |")

    report = "\n".join(lines)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

    return report


def main():
    parser = argparse.ArgumentParser(description="Score Model Audition results")
    parser.add_argument("files", nargs="*", help="JSONL result files to score")
    parser.add_argument("--all", action="store_true", help="Score all results in results/")
    parser.add_argument("--report", action="store_true", help="Generate Markdown report")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    import time as _time

    if args.all:
        args.files = [str(p) for p in sorted(RESULTS_DIR.glob("*.jsonl"))]

    if not args.files:
        print("No result files. Use --all or specify files.")
        sys.exit(1)

    results = load_results(args.files)
    if not results:
        print("No results loaded.")
        sys.exit(1)

    rubric = load_rubric()

    # Group by model
    model_results = {}
    for r in results:
        model_results.setdefault(r["model"], []).append(r)

    all_scored = []
    for model, cases in sorted(model_results.items()):
        case_scores = {}
        for c in cases:
            case_scores[c["case_id"]] = auto_score(c)

        role_signals = compute_role_fit(case_scores, rubric)
        recommendations = recommend_roles(role_signals, rubric)

        best_score = max([b["score"] for b in recommendations["best"]]) if recommendations["best"] else 0

        scored = {
            "model": model,
            "cases_completed": len(cases),
            "cases_passed": sum(1 for c in cases if c["success"]),
            "case_scores": {k: v for k, v in case_scores.items()},
            "role_signals": role_signals,
            "recommendations": recommendations,
            "best_score": best_score,
        }
        all_scored.append(scored)

        if not args.json:
            best_roles = ", ".join(f"{b['role']}({b['score']})" for b in recommendations["best"][:3])
            print(f"{model:40s} best={best_roles or 'unclassified'}")

    if args.report:
        timestamp = _time.strftime("%Y%m%d-%H%M%S")
        report_path = REPORTS_DIR / f"{timestamp}_audition_report.md"
        report = generate_report(all_scored, report_path)
        print(f"\nReport: {report_path}")

    if args.json:
        print(json.dumps(all_scored, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import re
    main()
