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

## Task Selection Rules

When choosing the next read-only dogfood task for this project:

1. **Prefer config/schema/static tests** before media/model/API tests.
2. **Avoid tests that require** audio loading, OCR/image processing,
   subtitle content, or history DB access.
3. **Only inspect function names, imports, and assertion categories**
   unless deeper review is explicitly approved by controller.
4. **Do not run external project tests** until test side effects
   (audio playback, model loading, API calls, GUI launch) are known.
5. **Do not modify external repo** — all output stays in governance repo.
6. **If a file's content is uncertain**, read only the filename and
   line count, then ask controller before reading further.

## Read-Only Task Queue

### Completed (3/3 successful)
| # | Task | File | Status |
|---|------|------|--------|
| 1 | TM schema | test_tm_schema.py | ✓ |
| 2 | Profiles | test_profiles.py | ✓ |
| 3 | Preset checker | test_preset_checker.py | ✓ |

### Safe Next Candidates
- `tests/test_fast.py` — fast/smoke, likely no heavy dependencies
- `tests/test_provider_checker.py` — provider cache/config checks
- `tests/test_tm_schema.py` follow-up — CRUD coverage gaps
- `tests/test_llm_provider.py` — LLM provider config review

### Blocked or Manual-Confirm
- Audio tests (test_audio.py, test_voice*.py, test_realtime*.py)
- OCR/image tests (test_ocr, test_g3d)
- Subtitle content tests (test_subtitle*.py)
- Live API tests (test_api*.py, test_followup_api.py)
- Embedding/live Ollama smoke (test_tm_embedding_live_smoke.py)
- GUI/overlay tests (test_overlay_smoke.py, test_realtime_overlay_mode.py)

## Provider/API Read-Only Boundary Rules

When reviewing provider checker or API-related files:

1. **Structure-only code review** — function names, signatures, imports. Not config values.
2. **Do not read** `.env`, provider config instances, API key names, API key values, or provider endpoint URLs.
3. **Do not run** provider checks, chat probes, or network calls during read-only review.
4. **Do not call** Ollama, OpenAI, DeepSeek, or any provider adapter during review.
5. **Provider/API tasks that soft gate marks as high or manual-confirm** should be recorded as `pro-review` per #45 rule.
6. **Provider checker modules that internally redact API keys** (like `_safe_error`) are strong evidence of privacy-aware design — note this but do not test the redaction.

## Next Phase: Controlled Proposal Mode

After #90, shift from read-only structure review to controlled proposal mode:

- Select one small real issue in local-translator-agent
- Soft gate the task
- Read-only analysis of relevant files
- Produce: patch plan, risk report, files-to-touch list, test plan
- Do NOT modify external repo
- Do NOT run external tests
- Do NOT read secrets
