# Local-Translator-Agent Privacy Boundary Review

**Date**: 2026-06-14
**Review type**: Read-only structural analysis only — no user data read, no .env read.

## Privacy-Sensitive Areas

| Area | Sensitivity | Risk | Readable? |
|------|-----------|------|-----------|
| Audio transcription | High — user voice data | audio files, Wave/MP3 content | **No** |
| OCR screenshots | High — user screen content | screenshot images, OCR text | **No** |
| Translation history | High — user text/translation data | `history.db` SQLite | **No** |
| Terminology files | Medium — user custom glossaries | `glossary.json` | **No** |
| Profile/config files | Low — model paths, preferences | `.json` configs | Structural only |
| Subtitle files | Medium — user translation output | `.srt` files in data/ | **No** |
| .env | Critical — API keys | `.env` | **Never** |
| Browser extension | Low — manifest, content scripts | `.js`, `.json`, `.html` | ✓ structure only |
| Test fixtures | Medium — test audio/images | `.mp3`, `.mp4`, `.wav`, `.png` | Names only, not content |
| Runtime logs | Medium — may contain paths/errors | `.log`, `.txt` | **No** |
| Audit data | Medium — MCP audit events | `.mcp_audit/` | **No** |

## Allowed Read-Only Inspection

- Code paths (file names, function signatures, imports)
- Test names and markers (not test data)
- Documentation files (30+ docs/*.md)
- Config schema names (not values)
- Governance files (AGENTS.md, CLAUDE.md, etc.)

## Blocked Inspection

- `.env` — API keys, credentials
- `history.db` — user translation data
- `data/audio_cache/`, `data/jobs/`, `data/realtime_sessions/`, `data/subtitles/`, `data/uploads/`
- `tests/fixtures/*.mp3`, `*.mp4`, `*.wav` — test audio
- `test_audio.wav`, `test_audio_v01.wav`, `test_img.png`, `test_ocr_v01.png`
- `server_stderr.log`, `server_stdout.log`, `wd_stdout.txt`
- `.mcp_audit/events.jsonl`, `failures.jsonl`
- `glossary.json`

## Privacy Gate Validation

All task descriptions for external dogfood must pass privacy gate before logging:

```bash
py -3 tools/privacy_gate.py --text "<task description>"
```

If the task mentions file paths, check those paths:

```bash
py -3 tools/privacy_gate.py --path "<relative-path>"
```

## Stop Conditions

- Privacy gate returns `privacy_status == "blocked"` → **Stop, do not proceed**
- Task requires reading any file in the "Blocked Inspection" list → **Stop**
- Task requires running tests that load audio/OCR/GUI → **Stop, return to controller**
- `would_block == true` in any gate output → **Stop, report deviation**
