# Changelog

## v0.9.4 (2026-05-10)

- Fix release metadata consistency.
- Align VERSION, MCP server version, and global launcher version.
- Harden user-scope global MCP launcher parity with local MCP server behavior.
- Ensure run_checks distinguishes source-repo mode from installed-project mode.
- Update documentation from read-only wording to source-non-mutating wording.
- Add release-risk-review prompt registry coverage.

## v0.7.1 (2026-05-10)

- Dogfood code drafting on local-translator-agent
- Add docs/local-llm-code-drafting.md
- Update VERSION to 0.7.1

## v0.7.0 (2026-05-10)

- Add bounded local code drafting (draft-fix, draft-feature, draft-refactor, suggest-improvements)
- Add local_draft_code MCP tool (7 total, source-non-mutating)
- Drafts write only to .local_llm_out/, never source files
- All draft tasks: may_modify_code=false, controller_must_verify=true
- Safety verified: 3 draft scenarios, zero source file writes

## v0.6.1 (2026-05-09)

- Solo-test 31 Ollama models (one at a time, no GPU contention)
- Correct false timeouts from parallel testing
- Profiles expanded 6→13 with benchmark-backed assignments
- A/B quality test confirms nemotron-nano-omni best diff_reviewer

## v0.6.0 (2026-05-09)

- Model inventory: 58 Ollama + standalone GGUF models documented
- Benchmark tool enhanced (--models, --tasks, --repeat, --dry-run, --output-md)
- 3 new profiles: release_auditor, architecture_reviewer, embedding

## v0.5.3 (2026-05-09)

- Add architecture overview, roadmap, and README

## v0.5.2 (2026-05-09)

- Release hardening: centralized VERSION file
- Add CHANGELOG.md and docs/release-checklist.md
- Version consistency tests across MCP server, installer, and manifest

## v0.5.1 (2026-05-09)

- Dogfood --update on legacy v0.4.x install (local-translator-agent)
- Improve "fresh install" message to "legacy install (no manifest)"
- Add legacy update test (no manifest, content-hash-based detection)

## v0.5.0 (2026-05-09)

- Add .local_llm_pipeline.json manifest (installed_version, managed_files, skipped_files)
- Add --update mode with SHA256-based conflict detection
- Skip sensitive files (.env, *.pem, id_rsa, etc.)
- 10 new installer tests

## v0.4.1 (2026-05-09)

- Document v0.4.0 real migration to local-translator-agent
- Add installer SKIP_FILES tests
- Reinstall idempotency tests

## v0.4.0 (2026-05-09)

- Validate installer on second real project (local-translator-agent)
- Fix installer copying .claude/settings.local.json
- In-session MCP tool call verification

## v0.3.3 (2026-05-09)

- MCP usage patterns and client verification docs
- MCP vs CLI decision matrix
- Small closed-loop MCP dogfood

## v0.3.2 (2026-05-09)

- Fix local_check Ollama URL resolution (LOCAL_LLM_BASE_URL → OLLAMA_HOST → localhost)
- Fix debate default params and timeout handling
- Add large-diff protection with structured timeout errors

## v0.3.1 (2026-05-09)

- Add --version and --help to MCP server
- Add stderr timing logs per tool call
- KeyboardInterrupt graceful shutdown

## v0.3.0 (2026-05-09)

- Add local_llm_mcp_server.py with 6 read-only MCP tools
- MCP JSON-RPC over stdio
- Path validation, symlink resolution, output truncation

## v0.2.1 (2026-05-09)

- Debate quality calibration: MAX_FINDINGS limits
- Add --summary-only flag for compact MCP-ready output
- Fast/full mode usage boundaries

## v0.2.0 (2026-05-09)

- Add multi-model debate cross-review (local_llm_debate.py)
- Three-round flow: coder → reasoning → deep reviewer

## v0.1.3 (2026-05-09)

- Record real benchmark results
- Support OLLAMA_HOST environment variable

## v0.1.2 (2026-05-09)

- Add run_checks.py stability checks
- CI and benchmark reporting

## v0.1.1 (2026-05-09)

- Fix collect_tree truncation strategy
- Add test suite

## v0.1.0 (2026-05-09)

- Initial release: portable local LLM development pipeline
- local_llm_worker.py, local_llm_router.py, local_llm_check.py
- Ollama and OpenAI-compatible backend support
- install_local_llm_pipeline.py
