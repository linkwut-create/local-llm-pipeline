# Local-Translator-Agent Readonly Inventory

**Date**: 2026-06-14
**Repo path**: `C:\Users\Zero\local-translator-agent`

## Project Profile

- Voice-controlled universal translation + interpretation assistant
- Stack: FastAPI + DeepSeek API + PaddleOCR + faster-whisper + PySide6 GUI
- Current line: v0.11.0-dev
- pytest with `live_ollama` marker for optional live smoke tests

## Read-Only Inspected Files (safe)

| File | Type | Notes |
|------|------|-------|
| README.md | docs | Project overview, quick start |
| requirements.txt | config | 150+ packages, DeepSeek/OCR/audio/GUI |
| pytest.ini | config | live_ollama marker for optional smoke tests |

## Detected Project Components

### Source
- `services/` — 15 service modules (subtitle, TM, realtime, LLM provider, etc.)
- `tools/` — 20+ tools (MCP server, router, worker, profiles, prompts)
- `app.py`, `agent.py` — application entrypoints

### Tests (67 files)
- `tests/test_*.py` — comprehensive suite covering subtitle, TM, realtime, audio, API, etc.
- `tests/fixtures/` — audio/video test fixtures (.mp3, .mp4, .wav)
- `tests/test_voice_*.mp3` — voice test audio files

### Documentation
- 30+ docs in `docs/` covering architecture, MCP, TM, glossary, release

### Browser Extension
- `browser_extension/immersive_local/` — Chrome extension (manifest, content scripts, popup)

## Blocked Files (must not read)

| Category | Files | Reason |
|----------|-------|--------|
| Secrets | `.env` | API keys, credentials |
| Database | `history.db` | User translation history |
| User data dirs | `data/audio_cache/`, `data/jobs/`, `data/realtime_sessions/`, `data/subtitles/`, `data/uploads/` | User-generated content |
| Audio fixtures | `tests/fixtures/*.mp3`, `*.mp4`, `*.wav` | Test audio (may contain user voice) |
| Media | `test_audio.wav`, `test_audio_v01.wav`, `test_img.png`, `test_ocr_v01.png` | Screenshot/audio samples |
| Logs | `server_stderr.log`, `server_stdout.log`, `wd_stdout.txt` | Runtime logs |
| Audit data | `.mcp_audit/` | Audit event logs |
| Binary | `cloudflared.exe` | External binary |
| Terminology | `glossary.json` | User terminology data |

## Safe Dogfood Candidate Tasks

1. Review test structure (test file names, markers, entrypoints)
2. Review documentation consistency (docs/)
3. Review service module boundaries (file names, imports)
4. Review AGENTS.md / CLAUDE.md governance docs
5. Review pytest configuration and test markers

## Privacy Notes

- Project uses DeepSeek API — never read `.env` or API key
- Audio/OCR/image fixtures exist in test dir — avoid reading content
- Translation history is in `history.db` — never read
- Browser extension has its own manifest — safe to review structurally
- Templates dir contains governance templates — safe, reusable
