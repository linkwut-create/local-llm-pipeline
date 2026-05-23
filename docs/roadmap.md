# Roadmap

## Completed (v0.1.0 → v0.5.2)

### Phase 1: Baseline (v0.1.x)

- [x] Single-model worker with structured output
- [x] Task routing (router → profile → model)
- [x] Environment health check
- [x] Path blocking and security policy
- [x] Stability checks (run_checks.py)
- [x] Benchmark reporting
- [x] OLLAMA_HOST support for remote Ollama

### Phase 2: Multi-Model Review (v0.2.x)

- [x] Three-round debate: coder → reasoning → deep reviewer
- [x] Fast mode (2 rounds) and full mode (3 rounds)
- [x] Finding classification (high_confidence, candidate, disputed, controller_must_verify)
- [x] MAX_FINDINGS limits to prevent output bloat
- [x] --summary-only for compact MCP-ready output
- [x] Debate quality calibration with dogfood

### Phase 3: MCP Integration (v0.3.x)

- [x] MCP server with 6 source-non-mutating tools over stdio JSON-RPC (expanded to 7 in v0.7.0+)
- [x] local_check, local_summarize_file, local_summarize_tree
- [x] local_generate_test_plan, local_review_diff, local_debate_review_diff
- [x] Claude Code and Codex client verification
- [x] MCP vs CLI usage patterns
- [x] Remote Ollama environment variable support
- [x] Large diff protection with structured timeout errors

### Phase 4: Multi-Project (v0.4.x)

- [x] Installer validated on second real project (local-translator-agent)
- [x] Fix local config leaking (settings.local.json)
- [x] Installer migration documentation
- [x] Reinstall idempotency

### Phase 5: Versioning (v0.5.x)

- [x] Install manifest (.local_llm_pipeline.json)
- [x] --update mode with SHA256 conflict detection
- [x] Sensitive file filtering (.env, *.pem, id_rsa)
- [x] Legacy install update dogfood
- [x] Centralized VERSION file
- [x] CHANGELOG.md
- [x] Release checklist
- [x] Version consistency tests
- [x] Architecture overview and roadmap (this file)

## Completed (v0.6.x → v0.9.8)

### Phase 6: Profile Tuning + Benchmarking (v0.6.x)

- [x] Profile auto-tuning from Ollama model inventory
- [x] Benchmark expansion across model families
- [x] Structured logging framework

### Phase 7: Code Drafting + Config Validation (v0.7.x–v0.8.x)

- [x] Code drafting MCP tool (draft-fix/feature/refactor/suggest-improvements)
- [x] Config schema validation (validate_configs.py)
- [x] Retry and timeout hardening
- [x] Concurrency guard
- [x] Summarize cache
- [x] Structured call logging (call_ledger.py)
- [x] Prompt registry with versioned prompt templates
- [x] Readiness check for installed projects

### Phase 8: MCP 2.0 — Gate, Auto-Worker, Global Launcher (v0.9.x)

- [x] Commit gate review (mcp_gate.py) with diff hash tracking
- [x] Auto-invocation hooks: SessionStart, PostToolUse, Stop
- [x] Dangerous command blocking (PreToolUse)
- [x] Release / tag / push guard
- [x] Hook doctor diagnostic tool (mcp_doctor.py)
- [x] Global MCP launcher for cross-project install
- [x] MCP audit logging and reporting

### Phase 9: Cost Discipline + Reliability + Observability (v0.9.1–v0.9.8)

- [x] Health telemetry isolation (health_store.py) — P1-H
- [x] Call ledger cost-discipline chain (profile/extra/env stamps, CLI reporting) — P2
- [x] Escalation cost control with env-knob gates (confidence, uncertain_points) — P3
- [x] Worker-pool dry-run diagnostic probe — P4
- [x] V4-Flash experimental profile — P5
- [x] Subprocess timeout observability fix (timeout vs worker_failed_no_output) — P6-B1
- [x] Call ledger read diagnostics (malformed line detection, CLI --diagnostics) — P6-B2
- [x] Bounded ollama list subprocess (30s timeout) — P6-B3
- [x] Hook silent-failure diagnostics (gate state, auto-worker spawn, MCP shape, doctor) — P7
- [x] C2 streaming stdout contract fix (compat parser, producer migration) — v0.10.0-A→D
- [x] P6-B2-C call ledger write-failure observability (_record_write_failure, doctor checks) — v0.10.0-G
- [x] M3 manual call ledger rotation (rotate_ledger, CLI rotate, doctor refs) — v0.10.0-H
- [x] H6 classify_error taxonomy (substring disambiguation, word-boundary 5xx, connection-before-timeout) — v0.10.0-I→J
- [x] M7 cost-estimate credibility (execution_location + cost_confidence labels) — v0.10.0-L

## Current State (post-v0.9.8)

- 9 MCP tools, all source-non-mutating (local_draft_code writes only to .local_llm_out/)
- 3-round debate (fast mode default for MCP), parallel review for release audits
- 1288 tests, 13 run_checks categories, 23 profile entries
- Remote Ollama via LOCAL_LLM_BASE_URL / OLLAMA_HOST
- Installer with manifest and --update mode
- Auto-invocation hooks: SessionStart, PreToolUse, PostToolUse, Stop
- Call ledger with profile/extra/env stamps and CLI diagnostics
- Health store with runtime telemetry (not polluting profiles JSON)
- Hook doctor with 33 checks
- Windows PowerShell + Git Bash compatible

## Explicitly Deferred / Not Authorized

These items are known gaps from the P6/P7 reliability audits. They are
**not authorized** for any current or pending phase. Each requires a
separate design and approval before implementation.

- ~~C2~~ — **Done (v0.10.0-A→D).** Streaming stdout contract unified.
- ~~P6-B2-C~~ — **Done (v0.10.0-G).** Write-failure diagnostic log + doctor checks.
- ~~M3~~ — **Done (v0.10.0-H).** Manual CLI rotation; no auto-truncation.
- ~~H6~~ — **Done (v0.10.0-I→J + b41ec97).** Error classification disambiguation complete;
  connection-before-timeout order, word-boundary 5xx gating, narrowed parse matches.
- ~~M7~~ — **Done (v0.10.0-L).** Execution-location classification (`local`/`lan`/`remote`/`unknown`)
  + cost-confidence labels (`high`/`medium`/`low`/`none`).  No exact LAN dollar costs.
- **P6-B3-B / H5** — MTP endpoint hardcoding / configuration surface
- **P5-C** — V4-Flash `_env` wiring, model warmup, per-profile provider hint

## Will NOT Do (by design)

- **Auto-modify source code** — local models are advisory only
- **Auto-commit / auto-push / auto-tag** — human + controller decides
- **Auto-deploy** — pipeline never reaches production
- **MCP write_file / delete_file / shell** — hard boundary
- **Default full debate for all diffs** — fast mode is the default
- **Batch force-overwrite across projects** — conflicts must be reviewed
- **Local model final approval** — controller always has final say
- **Read secrets or keys** — blocked by path validation
- **Train or fine-tune models** — pipeline uses existing Ollama models only

## Recommendation

The pipeline at v0.9.8 is feature-complete for its stated purpose: providing
source-non-mutating, multi-model LLM assistance to Claude Code during software
development with automated participation via hooks. The deferred items above
are known reliability gaps, not feature gaps — they improve observability and
robustness without adding new capabilities. Future work should prioritize
stabilization (addressing deferred items with explicit design-before-code) over
new feature development.
