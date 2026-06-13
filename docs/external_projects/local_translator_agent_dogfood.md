# Local-Translator-Agent Dogfood Protocol

First external project for governance-layer dogfood validation.
This project translates subtitles using local Whisper + translation models.

## Project Profile

- **Repo**: `local-translator-agent`
- **Risk profile**: Lower than Google Play release, browser permissions, game builds
- **Core data**: Subtitle text, audio transcription, translation output
- **Sensitive data**: Audio file paths, subtitle content (user-generated), `.env` with model paths

## Allowed Dogfood Task Types

| Task type | Allowed | Actual label |
|-----------|---------|-------------|
| Read-only analysis (code review, structure check) | ✓ | `local-first` |
| Test plan generation | ✓ | `local-first` |
| Documentation review | ✓ | `local-first` |
| Scenario/checklist creation | ✓ | `local-first` |
| Release checklist review | ✓ | `pro-review` |
| Privacy boundary review | ✓ | `pro-review` |
| Direct code modification | ✗ | — |
| Reading `.env` / secrets / API keys | ✗ | — |
| Calling DeepSeek for external tasks | ✗ | — |
| Commit/push to external repo | ✗ | — |

## Hard Constraints

1. **Never read `.env`** from the external project. Task descriptions may mention
   files but must not contain their contents.
2. **Never read audio files or subtitle content** — only file names and structure.
3. **Never call DeepSeek** for external project tasks. All analysis is local-only
   via the existing Ollama pipeline.
4. **Never modify** the external repo. All output goes to `.local_llm_out/` in
   this pipeline repo.
5. **Never write external project content to shadow route log**. Only task
   descriptions, not file contents.

## Shadow Route Logging

```bash
py -3 tools/shadow_route_log.py \
    "local-translator-agent: <task description>" \
    --actual "<local-first-or-pro-review>"
```

Prefix all tasks with `local-translator-agent:` for project-level aggregation.

## Actual Labeling

Apply the standard #45 rule:

| Condition | Actual |
|-----------|--------|
| `router_risk_level == "high"` | `pro-review` |
| `decision == "manual_confirm_recommended"` | `pro-review` |
| `task_type == "governance-integration"` | `pro-review` |
| Low/medium analysis, test plans, docs | `local-first` |

## When to Stop and Return to Controller

- Soft gate returns `decision == "cloud-blocked"` → stop, report
- Privacy gate returns `privacy_status == "blocked"` on task text → stop, report
- Task requires reading actual `.env` content → stop, do not proceed
- Task requires modifying external source → stop, return to controller for decision
- `would_block == true` in any gate output → stop, report as process deviation

## First-Round Scenarios

See scenarios section below (to be populated in #62).
