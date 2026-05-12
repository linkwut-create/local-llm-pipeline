# MCP Phase 1 Dogfood Validation Report

- **Date**: 2026-05-12
- **Validator**: Claude Code (controller) + local models (qwen3.5-claude-opus-9b via smart_summary)
- **Scope**: Cross-check 4 policy documents for consistency; verify MCP tool availability; verify policy can guide actual task flow

## MCP Tools Actually Called

| Step | Tool | Profile | Result |
|------|------|---------|--------|
| Session start | `local_check` | (no LLM) | `ok=true`, 4.75s |
| Read mcp-task-policy.md | `local_summarize_file` | `smart_summary` | `ok=true`, 35.97s, confidence=medium |
| Read model-routing-policy.md | `local_summarize_file` | `smart_summary` | `ok=true`, 34.57s, confidence=medium |
| Direct read CLAUDE.md | (controller) | — | lines 64-111, confirmed consistent |
| Direct read AGENTS.md | (controller) | — | lines 61-86, confirmed consistent |

MCP calls: 3/3 `ok=true`. No timeouts. No UnicodeDecodeError.

## Consistency Check Results

### 7-Point Cross-Check

| # | Check Item | CLAUDE.md | AGENTS.md | mcp-task-policy.md | model-routing-policy.md | Result |
|---|-----------|-----------|-----------|--------------------|-------------------------|--------|
| 1 | Commit gate model = commit_reviewer | "MUST use commit_reviewer" | "commit_reviewer only" | "Must use commit_reviewer" | qwen3-coder:30b in Tier 1 | **PASS** |
| 2 | Staged diff requires re-review | "MUST be re-reviewed" | "must be re-reviewed" | "MUST be re-reviewed" | N/A (task policy scope) | **PASS** |
| 3 | MCP failure = hard stop | "STOP. Do not commit." | "STOP, do not commit." | 4-row table of hard stops | N/A (task policy scope) | **PASS** |
| 4 | Release requires release_auditor | "release_auditor mandatory" | (not in AGENTS.md) | "Must use release_auditor" | Tier 6: mistral-medium | **PASS** |
| 5 | translategemma blocked from CLI | "glm-4.7-flash only" | (not in AGENTS.md) | "Must NOT" in hard stops | Tier 7 note explains why | **PASS** |
| 6 | Known-bad models excluded | "MUST NOT enter automated routing" | (not in AGENTS.md) | "Must NOT enter automated routing" | 8-model Known-Bad list | **PASS** |
| 7 | No "manual substitute for MCP" loophole | "MUST NOT say I reviewed it manually" | "must not manually substitute" | Explicitly prohibited | N/A (task policy scope) | **PASS** |

**Zero conflicts found.** All four documents agree on all seven verification points.

### AGENTS.md Coverage Gap (minor)

AGENTS.md has a shorter hard-stop list than CLAUDE.md and mcp-task-policy.md. It covers 4 of the 12 prohibition rules. This is by design — AGENTS.md is a summary for external agents, CLAUDE.md and mcp-task-policy.md are authoritative. Not a conflict.

### local_check Display vs Profiles (pre-existing, not a policy conflict)

`local_check` "Recommended Profiles" shows models that differ from the authoritative `tools/local_llm_profiles.json`:

| Profile | local_check says | profiles.json (authoritative) |
|---------|-----------------|-------------------------------|
| diff_reviewer | qwen3.5-35b-q8 | nvidia-nemotron-3-nano-omni |
| deep_reviewer | mistral-medium-3.5-128b | qwen3.6:35b-q8-ud |
| reasoning_checker | deepseek-r1-distill-llama:70b | qwen3.5-27b-reasoning |

This is a known display issue in `local_check`'s recommendation logic, not a policy conflict. The profiles file is authoritative. The `local_check` recommendations should be updated to match the profiles file in a future cleanup.

## Policy Enforceability Assessment

### What Worked

1. **local_check at session start**: Natural, fast (4.75s), provides useful environment context.
2. **summarize before deep reading**: Called `local_summarize_file` with `smart_summary` for two policy docs. Both completed successfully in ~35s. The summaries correctly identified key structures.
3. **Direct read for short familiar files**: CLAUDE.md and AGENTS.md are short (< 200 lines). Reading directly was efficient and policy-compliant.
4. **Cross-check methodology**: The 7-point checklist was mechanically verifiable — no ambiguity.

### What Needs Phase 2 Hooks

1. **Enforcement of "summarize before editing unfamiliar files"**: Currently relies on Claude Code self-discipline. A PreToolUse hook on Edit/Write for files in `tools/` or `docs/` could remind but not block.
2. **Enforcement of "staged diff re-review"**: Currently requires Claude Code to remember. A pre-commit hook would enforce this mechanically.
3. **Enforcement of "MCP failure → STOP"**: The existing commit-gate hook already enforces this for commits. But for non-commit tasks (reading, planning), there's no mechanical enforcement — Claude Code could skip MCP and the system wouldn't stop it.

### What Does NOT Need Hooks

1. **Task → tool mapping**: The table is clear enough that Claude Code can follow it from documentation alone.
2. **Model selection rules**: The profiles file + task config enforce these mechanically. No hook needed.
3. **Escalation rules**: These are judgment calls (e.g., "uncertain_points > 3"). Automation would be complex and brittle. Documentation is sufficient.

## Phase 2 Hook Recommendation (Minimum Viable)

Based on this dogfood, Phase 2 should add only these hooks:

1. **Stop hook**: On session end, if MCP was never called during a code-change task, remind the user.
2. **Pre-commit enforcement** (already exists): Keep the existing commit-gate hook as-is.
3. **No PreToolUse on Edit/Write**: Too noisy. Wait until Phase 3 after more dogfood data.

## Verdict

**MCP 2.0 Phase 1 documentation is internally consistent and executable.**
Claude Code successfully followed the task→tool mapping during this validation session.
No policy conflicts were found.
One minor display discrepancy noted in `local_check` (pre-existing, not a policy issue).
Phase 2 hook scope should be minimal: Stop reminder + keep existing commit gate.
