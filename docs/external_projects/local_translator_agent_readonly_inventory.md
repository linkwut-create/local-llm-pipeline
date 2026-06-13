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

## Test Entrypoint Review

### Safe Test Candidates (no audio/model/user data needed)

| Test file | Category | Safe for read-only? |
|-----------|----------|---------------------|
| `test_agent.py` | agent logic | ✓ structural review |
| `test_atomic_write.py` | file I/O | ✓ code path review |
| `test_fast.py` | fast/smoke | ✓ |
| `test_glossary_unification.py` | glossary | ✓ if not reading glossary.json |
| `test_llm_provider.py` | LLM config | ✓ config review |
| `test_profiles.py` | profiles | ✓ config review |
| `test_preset_checker.py` | presets | ✓ |
| `test_provider_checker.py` | provider check | ✓ |
| `test_tm_schema.py` | TM schema | ✓ schema review |
| `test_tm_prompt_injection.py` | TM security | ✓ |
| `test_cancel_safety.py` | cancel safety | ✓ |
| `test_shutdown.py` | shutdown | ✓ |
| `test_stop_all_script.py` | stop script | ✓ |
| `test_system_health.py` | health check | ✓ |
| `test_mobile_pwa.py` | mobile PWA | ✓ static |
| `test_pdf_reader_static.py` | PDF reader | ✓ static |
| `test_immersive_local_extension.py` | extension | ✓ manifest review |
| `test_tm_confirmation_ui_static.py` | TM UI | ✓ static |

### Risky Test Candidates (may need audio/model/image/user data)

| Test file | Concern |
|-----------|---------|
| `test_audio.py` | may load audio fixtures |
| `test_voice.py`, `test_voice_hotkey.py` | may load voice .mp3 |
| `test_realtime_*.py` (8 files) | may access realtime sessions |
| `test_subtitle*.py` (5 files) | may load subtitle content |
| `test_tm_embedding_live_smoke.py` | requires live Ollama |
| `test_followup_api.py` | may call API |
| `test_api_fallback.py` | may call API |
| `test_selection_api.py` | may call API |
| `test_tm_api.py`, `test_tm_fts_api.py`, `test_tm_semantic_search_api.py` | may call API |
| `test_g3a_prompt_unification.py`, `test_g3d_ocr_audio_prompt_unification.py` | may load media |
| `test_overlay_smoke.py` | smoke test, may need GUI |

### Recommended First Real Read-Only Task

**Review `test_tm_schema.py` test structure** — purely structural code review,
no audio/model/user data, no API calls, no OCR. Verify test coverage patterns
for translation memory schema.
