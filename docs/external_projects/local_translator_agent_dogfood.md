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

## First-Round Scenarios (8 scenarios)

### 1. Subtitle regression test
- **Task**: "local-translator-agent: test subtitle timing regression in episode 12"
- **Expected risk**: low
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No (task description only, no subtitle content)
- **Allowed action**: Read-only analysis, test plan
- **Blocked action**: Reading actual subtitle files

### 2. OCR fallback bug triage
- **Task**: "local-translator-agent: triage OCR fallback crash when Tesseract returns empty"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No
- **Allowed action**: Code structure review, test plan
- **Blocked action**: Running OCR on user images

### 3. Translation profile check
- **Task**: "local-translator-agent: verify translation profiles loaded correctly for Japanese models"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No
- **Allowed action**: Profile configuration review
- **Blocked action**: Reading model weights or live translation output

### 4. Nishida terminology table update
- **Task**: "local-translator-agent: review Nishida terminology table format for consistency"
- **Expected risk**: low
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No
- **Allowed action**: Schema/structure review
- **Blocked action**: Modifying terminology data

### 5. Whisper transcription regression
- **Task**: "local-translator-agent: review Whisper model output regression in v3"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No (review of code paths, not audio)
- **Allowed action**: Code path analysis
- **Blocked action**: Reading audio files or transcription output

### 6. SRT bilingual output review
- **Task**: "local-translator-agent: review SRT bilingual output alignment logic"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No
- **Allowed action**: Logic review, test plan
- **Blocked action**: Reading actual SRT files with content

### 7. Release checklist review
- **Task**: "local-translator-agent: review release checklist for v2.1.0"
- **Expected risk**: high
- **Expected actual**: `pro-review`
- **Cloud allowed?**: No (governance/release boundary)
- **Privacy concern?**: No (checklist metadata)
- **Allowed action**: Checklist validation
- **Blocked action**: Running release scripts

### 8. Privacy boundary review for audio/text history
- **Task**: "local-translator-agent: audit audio/text history storage for privacy compliance"
- **Expected risk**: high
- **Expected actual**: `pro-review`
- **Cloud allowed?**: No (privacy boundary)
- **Privacy concern?**: Yes — task involves privacy boundary. Run privacy gate on task text only.
- **Allowed action**: Code structure review of storage paths
- **Blocked action**: Reading actual history files, reading user audio data

## Summary

| # | Scenario | Risk | Actual | Cloud | Privacy |
|---|----------|------|--------|-------|---------|
| 1 | subtitle regression test | low | local-first | No | No |
| 2 | OCR fallback bug triage | medium | local-first | No | No |
| 3 | translation profile check | medium | local-first | No | No |
| 4 | Nishida terminology table | low | local-first | No | No |
| 5 | Whisper transcription regression | medium | local-first | No | No |
| 6 | SRT bilingual output review | medium | local-first | No | No |
| 7 | release checklist review | high | pro-review | No | No |
| 8 | audio/text history privacy audit | high | pro-review | No | Yes |
