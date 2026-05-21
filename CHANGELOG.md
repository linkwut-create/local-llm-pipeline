# Changelog

## Unreleased (post-v0.9.7)

- MCP Cost Discipline P2-C1.1: MCP server stamps worker subprocess calls
  with `LOCAL_LLM_LEDGER_EXTRA`. `tools/local_llm_mcp_server.py` gains a
  `_build_ledger_extra_env` helper and an `extra_env` parameter on
  `run_subprocess` / `run_subprocess_streaming` / `_wrap_worker_call`.
  Every worker-backed MCP tool now stamps the child env with the real
  `mcp_tool_name` and `source="manual-mcp"`; `local_review_diff` also
  stamps `commit_gate` (true on the gate path, false otherwise);
  `local_parallel_review` stamps each parallel worker. `local_check` and
  `local_debate_review_diff` are intentionally left unstamped — the
  former runs the env-health probe, the latter is P2-C3 (per-round
  ledger emission). No hook/router/debate/escalation wiring yet.
- MCP Cost Discipline P2-C1.0: worker ledger env plumbing. Worker reads
  `LOCAL_LLM_LEDGER_EXTRA`, filters JSON via the P2-B `KNOWN_EXTRA_KEYS`
  allowlist, and folds the result into the call ledger record's `extra`
  field. `_emit_ledger` now also passes `profile=config.profile` into the
  P2-B top-level slot. No MCP server / hook / router / debate wiring yet —
  setting the env var is P2-C1.1 (MCP server) and P2-C1.2 (auto hook).
- MCP Cost Discipline P2-B: extend `tools/call_ledger.py` schema/helpers
  for the cost-discipline field model. Adds a top-level `profile` field
  to `build_record` (default `None`, additive JSONL — no migration), and
  exposes a `KNOWN_EXTRA_KEYS` allowlist (frozenset) covering MCP routing
  identity, auto-escalation context, debate context, review classification,
  worker-pool attribution, and structured error type. No call sites wired
  — MCP server, debate, router, worker, and hooks are untouched. Secret
  stripping (`_FORBIDDEN_KEYS`) and backward compatibility preserved.
- MCP Cost Discipline P2-A: read-only audit of current call ledger
  coverage, recorded in conversation; no code changes. Identifies the
  three highest-risk gaps (debate calls bypass ledger entirely;
  auto-escalation child calls lose escalation context; commit-gate flag
  not captured) and the precise schema additions required for P2-B.
- MCP Health Telemetry Isolation P1-H.4: docs closeout for
  P1-H.0–P1-H.3, recording runtime health telemetry migration
  completion in `docs/MCP_HEALTH_TELEMETRY_ISOLATION_PLAN.md` §11.
  No code changes.
- MCP Health Telemetry Isolation P1-H.3: switch `cmd_health_report`
  (router) and `auto_tune_recommendations`
  (update_profiles_from_ollama) to read from the runtime health
  store. Legacy `profile["_health"]` fallback preserved for
  synthetic-dict tests. No profiles JSON writes.
- MCP Health Telemetry Isolation P1-H.1: add isolated runtime health
  store helper `tools/health_store.py` plus tests. No call sites
  switched yet; `tools/local_llm_profiles.json` remains unchanged.
  P1-H.2 will perform the behavioral switch.
- MCP Health Telemetry Isolation P1-H.0: planning document
  `docs/MCP_HEALTH_TELEMETRY_ISOLATION_PLAN.md`. Locks the design for
  moving per-call `_health` telemetry out of
  `tools/local_llm_profiles.json` into a gitignored
  `.local_llm_out/local_llm_health.json`. Implementation phases
  P1-H.1–P1-H.4 not yet scheduled; each requires separate approval.
  No code changes in this commit.
- MCP Cost Discipline P1-A: new read-only helper `tools/profile_policy.py`
  that derives a normalized 8-field policy view (`risk_level`,
  `default_review_necessity`, `auto_allowed`, `requires_escalation_reason`,
  `debate_allowed`, `commit_gate_allowed`, `local_only`, `experimental`)
  from each profile's existing legacy fields. `tools/local_llm_profiles.json`
  is unchanged. No routing, hook, commit gate, or auto-upgrade behavior
  altered — enforcement is deferred to P2+. See
  `docs/MCP_COST_DISCIPLINE_PLAN.md` §12.
- Call Ledger v2-A: real provider usage passthrough for non-stream calls (`5ddca41`).
  `call_ollama` and `call_openai_compat` now return `ModelCallResult` (content +
  normalized usage) instead of plain `str`. `normalize_usage()` maps Ollama
  `prompt_eval_count`/`eval_count` and OpenAI-compatible `prompt_tokens`/
  `completion_tokens` into a unified shape, including DeepSeek
  `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`. Ledger prefers real
  provider usage when available, falls back to `chars//4` estimation otherwise.
  Streaming usage passthrough and cache-tier cost estimation deferred to v2-B/v2-C.

## v0.9.7 (2026-05-19)

- Fix commit gate self-block: replace substring matching with structured allowlist.
  `commit_reviewer` profile now has `_commit_gate_allowed: true`. Constraint check
  uses `_commit_gate_allowed` and `risk_level` instead of parsing `_constraints` text.
- Sync MCP tool count to 9 everywhere: tests, docs, readiness checker, prompts.
  `local_parallel_review` was added in v0.9.6 but documentation lagged.
- Fix readiness check `logging_no_sensitive_data` false positive: match field keys
  instead of substring-scanning JSON strings (was flagging `prompt_id` as sensitive).
- Add `.gitattributes` for consistent line endings across platforms.
- Bump VERSION to 0.9.7.

## v0.9.6 (2026-05-19)

- Proactive input-based routing: call_summarize_file, call_generate_test_plan,
  call_review_diff, and call_debate_review_diff now analyze input characteristics
  (file size, CJK ratio, definition count, security patterns, diff complexity)
  to select the right profile BEFORE the first model invocation.
- New _classify_input_complexity() shared function for all tool handlers.
- Non-commit-gate review_diff routes through _wrap_worker_call for quality escalation.
- Debate auto-decides 2-round vs 3-round based on line count, file count, security.
- Health-aware profile auto-tuning: update_profiles_from_ollama.py --auto-tune
  compares _health data and recommends model swaps. --apply auto-applies >20% improvements.
- Smarter MCP output compression: _strip_nulls, priority field preservation, multi-pass truncation.
- llama.cpp MTP startup script for zero12 (tools/start_llamacpp_mtp.sh).
- local_check.py now probes remote llama.cpp MTP endpoints (ports 8080/8082/8083).
- Updated .codex/local-llm-worker.md with all 8 MCP tools and proactive routing docs.
- AGENTS.md corrected to 8 MCP tools, memory files updated.

## v0.9.5 (2026-05-10)

- Fix version provenance: _read_version() reads from LOCAL_LLM_SOURCE_REPO, not target project.
- Add _get_source_repo_root() to distinguish pipeline assets from target project boundary.
- Global launcher already sets LOCAL_LLM_SOURCE_REPO; MCP server now consumes it correctly.

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
