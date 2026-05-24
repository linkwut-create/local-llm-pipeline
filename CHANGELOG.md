# Changelog

## v0.11.0 (unreleased, post-v0.10.0)

- v0.11.0-A1: removed redundant MCP-layer summarize-file cache
  (`call_summarize_file` L2119-2153).  The MCP cache had three bugs:
  cache key lacked model/prompt_hash/size/mtime_ns, hardcoded 1h TTL,
  and cache hits bypassed the worker entirely (no ledger record).
  Worker cache (`local_llm_cache.py`) is now authoritative for both
  summarize-file and summarize-tree — it has correct cache-key
  composition, no TTL, and always writes ledger records.  16 new
  tests.  1316/1316 passed, 13/13 run_checks.  No VERSION bump.
- v0.11.0-A2: summary cache end-to-end dogfood verification passed.
  Real MCP `local_summarize_tree` calls proved worker cache is
  operational and measurable: first call `cache_hit=false, dur=104527ms`,
  second call (same params) `cache_hit=true, dur=0ms` in ledger (observed
  elapsed ~0.89s).  `local_summarize_file` invalidation confirmed after
  file content change.  Caveat: Claude Code MCP client may cache
  identical `local_summarize_file` calls, so direct same-file A/B
  testing of that tool can be polluted by client-side cache — this is
  a Claude Code behavior, not a pipeline bug.  Summary cache line
  is closed: worker cache is authoritative, ledger records cache hits,
  and file-change invalidation works.  Next: v0.11.0-B0 diff risk
  preclassifier contract audit.
- v0.11.0-B1-A: added diff preclassifier safety core
  (`tools/local_llm_preclassifier.py`). Heuristic-only classification
  module — no model calls, no debate integration, no debate skipping.
  All outputs default to `escalate_to_debate=true` and
  `skip_debate_allowed=false`. 58 focused tests
  (`tests/test_preclassifier.py`) cover docs-only, tests-only,
  sensitive paths (MCP server, hooks, ledger, auth, version/release),
  large diff, empty diff, security patterns in body, commit_gate/release
  context flags, Windows paths, and contract schema compliance.
  B1-A iron rule: `escalate_to_debate` always true, `skip_debate_allowed`
  always false — this is a safety classifier, not a debate bypass engine.
  Next: B1-B ledger contract or B1-C advisory integration, pending review.
- v0.11.0-B1-B: added preclassifier ledger reporting contract.
  Extended `KNOWN_EXTRA_KEYS` with 12 preclassifier/debate-skip fields
  (`diff_risk_level`, `diff_risk_confidence`, `debate_skipped`,
  `debate_skip_reason`, `preclassifier_profile`, `preclassifier_model`,
  `preclassifier_request_id`, `safety_blockers`, `debate_skip_allowed`,
  `skip_debate_recommended`, `preclassifier_method`,
  `changed_files_count`). Added `filter_debate_skips()` and
  `summarize_debate_skips()` to `tools/call_ledger.py`. Added
  `debate-skips` subcommand to `tools/call_ledger_cli.py` with
  JSON/text output, by-risk-level/confidence/profile breakdowns,
  and estimated seconds/tokens saved. 24 new tests
  (`tests/test_preclassifier_ledger.py`) cover field acceptance,
  old-record compatibility, CLI output, zero-skips state, and
  malformed safety_blockers handling. No debate integration yet;
  debate-skips will show zero until B1-C/B1-D starts writing records.
  Next: B1-C advisory integration in non-commit/non-release debate path.
- v0.11.0-B1-C: advisory preclassifier integration in debate path.
  `call_debate_review_diff()` now runs `classify_diff_risk_heuristic()`
  before building the debate command, injects `preclassifier_advisory`
  into the MCP response (additive field), and stamps preclassifier
  metadata into `LOCAL_LLM_LEDGER_EXTRA`. B1-C iron rule: debate is
  always executed regardless of classification — `debate_skipped` and
  `debate_skip_allowed` are always false. Preclassifier import failure
  is non-fatal (safe fallback to `_preclassify=None`). 18 new tests
  (`tests/test_preclassifier_advisory.py`) cover advisory injection,
  no-skip invariant across 6 diff types, exception fallback, ledger
  extra fields, and existing behaviour preservation. Updated 6 existing
  test mocks to accept the new `extra_env` parameter. `call_review_diff`
  auto-debate path intentionally not integrated (safer, simpler).
  Next: B1-C2 dogfood verification or B1-D controlled skip policy audit.
- v0.11.0-B1-C3: fixed debate ledger propagation. `local_llm_debate.py`
  now reads `LOCAL_LLM_LEDGER_EXTRA` safely via new
  `_load_ledger_env_extra_for_debate()` helper and merges allowlisted
  B1-B preclassifier fields into per-round debate ledger records.
  Debate-authoritative fields (`debate_mode`, `debate_rounds`,
  `debate_round_index`, `debate_trigger`, `mcp_tool_name`, `source`)
  can never be overridden by env. `debate_skipped` and
  `debate_skip_allowed` are forced to `False` while the debate
  runner is executing. 15 new tests
  (`tests/test_debate_ledger_preclassifier.py`) cover env merging,
  authoritative override, forced-false invariants, malformed env,
  no-env backward compat, and ledger-failure survival.
  - v0.11.0-B1-C4: dogfood re-verification passed. Real MCP
	  `local_debate_review_diff` executed on docs-only diff (elapsed ~80s,
	  2-round fast mode). `preclassifier_advisory` returned in response:
	  `risk_level=low`, `confidence=high`, `skip_debate_recommended=true`,
	  `debate_skipped=false`, `debate_skip_allowed=false`. Both debate
	  round ledger records (`call_89b33304629d` round 1,
	  `call_96224f4e6b01` round 2) carry all 12 B1-B preclassifier
	  fields. `debate-skips` CLI returns `total_skipped=0`. Working tree
	  clean — no files changed, no commits, no tags.
	- **v0.11.0-B1 closed — diff preclassifier advisory line.**
	  B1-A (safety core): heuristic-only classification, no model calls,
	  no debate integration, `escalate_to_debate` always true,
	  `skip_debate_allowed` always false.  58 tests.
	  B1-B (ledger contract): 12 preclassifier/debate-skip fields in
	  `KNOWN_EXTRA_KEYS`, `filter_debate_skips()` / `summarize_debate_skips()`
	  helpers, `debate-skips` CLI subcommand.  24 tests.
	  B1-C (advisory integration): `preclassifier_advisory` in MCP response,
	  `LOCAL_LLM_LEDGER_EXTRA` stamping, debate always executes.  18 tests.
	  B1-C1 (regression reconciled): health_store failure not reproduced,
	  full tests passed without ignore.
	  B1-C2 (first dogfood): response advisory worked, ledger propagation
	  missing.
	  B1-C3 (ledger propagation fix): `local_llm_debate.py` reads
	  `LOCAL_LLM_LEDGER_EXTRA` via `_load_ledger_env_extra_for_debate()`,
	  merges B1-B allowlist fields, forces `debate_skipped=false` /
	  `debate_skip_allowed=false`.  15 tests.  1431/1431 passed, 13/13
	  run_checks.
	  B1-C4 (dogfood verified): real debate executed, response advisory
	  present, both round ledger records carry B1-B fields, `debate-skips`
	  zero, working tree clean.
	  **B1 state at closeout**: fully observable advisory preclassifier
	  line — classifies, responds, and records without ever skipping debate.
	  Debate skip remains disabled.  Commit gate, release guard, and
	  dangerous command guard unchanged.  VERSION remains 0.10.0.  No tag.
	- v0.11.0-B1-D: controlled skip policy audit (read-only, no code).
	  Inspected all relevant source files (preclassifier, debate, MCP
	  server, call ledger, gate).  Confirmed no skip branches exist.
	  Designed minimal opt-in docs-only auto-debate skip policy:
	  integration point = `call_review_diff` auto-escalation only
	  (manual `local_debate_review_diff` never skipped).  Non-skippable:
	  commit_gate, release, VERSION, pyproject, MCP/worker/router/debate/
	  ledger/hook/cache files, auth/security, runtime code, tests-only,
	  mixed diffs, low confidence, malformed diff, security body patterns.
	  Skippable: docs-only `.md` / `docs/**` / `CHANGELOG.md` /
	  `PROJECT_STATUS.md` with env opt-in.  Two env knobs:
	  `LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP` (default off) and
	  `LOCAL_LLM_FORCE_DEBATE_REVIEW` (circuit breaker, overrides all).
	  Verdict: PROCEED to B1-E implementation.
	- **v0.11.0-B1-E**: controlled low-risk auto-debate skip implemented.
	  Added `_should_skip_auto_debate_for_low_risk_docs()` helper in MCP
	  server — env-gated, preclassifier-driven, docs-only check.  Wired
	  into `call_review_diff()` auto-debate escalation path only.  When
	  skip fires: single-model review still runs, response gains
	  `debate_auto_escalation_skipped` advisory (`safe_to_commit=false`,
	  `requires_commit_gate_review=true`), ledger skip record written
	  (`debate_mode=false`, `debate_skip_allowed=true`).  3 new
	  `KNOWN_EXTRA_KEYS` (`debate_skip_policy`, `debate_skip_policy_version`,
	  `skipped_estimated_seconds_saved`).  37 new tests
	  (`tests/test_b1e_controlled_skip.py`).  Manual
	  `local_debate_review_diff` never skipped.  Commit/release/dangerous
	  guards unchanged.  VERSION remains 0.10.0.  No tag.
	- v0.11.0-B1-E dogfood verified (direct Python, not real MCP env-on).
	  Direct Python verification (all 8 steps passed):
	  env-off → auto-debate still fires; env-on docs-only → auto-debate
	  skipped, single-model review still runs; response
	  `debate_auto_escalation_skipped` with `safe_to_commit=false`,
	  `requires_commit_gate_review=true`; skip ledger record written
	  (`debate_skipped=true`, `debate_skip_allowed=true`, `debate_mode=false`,
	  `debate_skip_policy=b1-d-v1`); `debate-skips` CLI shows
	  `total_skipped=40`; `LOCAL_LLM_FORCE_DEBATE_REVIEW=true` overrides
	  skip; manual `local_debate_review_diff` never skipped; sensitive
	  files (MCP server) never skipped.  Temporary `_dogfood_b1e.py`
	  removed, working tree clean.
	  **Important caveat**: real MCP env-on verification is pending —
	  Claude Code MCP server must be restarted with
	  `LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP=true` before the real MCP
	  path is proven.  Current verification is direct Python only.
	  `B1E_DOGFOOD_DIRECT_VERIFIED=yes`;
	  `B1E_REAL_MCP_ENV_ON_PENDING=yes`.
	  Next: B1-E2 real MCP env-on verification after MCP restart.
	- **v0.11.0-B1-E2**: real MCP env-on verification passed.
	  Claude Code / MCP server was restarted with
	  `LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP=true` and
	  `LOCAL_LLM_FORCE_DEBATE_REVIEW` not set.
	  Real MCP `local_review_diff` called on docs-only heavy diff
	  (163 lines, 6,868 chars, `PROJECT_STATUS.md` only):
	  auto-debate successfully skipped; single-model review
	  (`commit_reviewer` / `qwen3-coder:30b`) still ran (~15s).
	  Response contract verified: `debate_auto_escalation_skipped`
	  present with `skipped=true`, `safe_to_commit=false`,
	  `requires_commit_gate_review=true`,
	  `manual_debate_still_available=true`, `policy=b1-d-v1`,
	  `policy_version=1`.  `preclassifier_advisory`: `risk_level=low`,
	  `confidence=high`.
	  Ledger verified: skip record `call_06dfa216bc1d` written with
	  all 17 expected fields (`debate_skipped=true`,
	  `debate_skip_allowed=true`, `debate_skip_policy=b1-d-v1`,
	  `debate_skip_policy_version=1`, `diff_risk_level=low`,
	  `diff_risk_confidence=high`, `preclassifier_method=heuristic`,
	  `preclassifier_model=none`, `safety_blockers=[]`,
	  `changed_files_count=1`, `skipped_estimated_seconds_saved=500.0`,
	  `source=auto-debate-skip`, `mcp_tool_name=local_review_diff`).
	  `debate-skips` CLI: `total_skipped=49` (includes this skip).
	  Manual `local_debate_review_diff` verified still executes full
	  debate (~127s, 2 models): `debate_skipped=false`,
	  `debate_skip_allowed=false`, no `debate_auto_escalation_skipped`
	  block.  Working tree clean.
	  `B1E_DOGFOOD_DIRECT_VERIFIED=yes`;
	  `B1E_REAL_MCP_ENV_ON_VERIFIED=yes`.
	  Default remains off unless `LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP=true`
	  is set.  Commit gate / release guard / dangerous command guard
	  unchanged.  VERSION remains `0.10.0`.  No tag.
	  **B1-E line closed**: both direct Python and real MCP env-on
	  paths verified.  Auto-debate skip is opt-in, observable, and
	  reversible.  Manual debate path preserved.
	- **v0.11.0-B1 final closeout**: diff preclassifier + controlled
	  auto-debate skip chain closed.
	  Final B1 state:
	  B1-A: heuristic-only preclassifier safety core (58 tests).
	  B1-B: ledger contract + debate-skips CLI (24 tests).
	  B1-C: advisory integration in debate response and ledger
	  (18 tests + 15 tests for B1-C3 ledger propagation).
	  B1-D: controlled skip policy audit (read-only).
	  B1-E: controlled low-risk auto-debate skip implementation
	  (37 tests).
	  B1-E2: real MCP env-on verification passed.
	  Verified guarantees:
	  - default unchanged unless
	    `LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP=true`
	  - `LOCAL_LLM_FORCE_DEBATE_REVIEW` circuit breaker forces debate
	  - docs-only heavy diff can skip auto-debate only when opt-in
	    enabled
	  - single-model review still runs on skip
	  - `safe_to_commit=false`
	  - `requires_commit_gate_review=true`
	  - skip ledger records written (17 fields)
	  - `debate-skips` CLI reports skip records
	  - manual `local_debate_review_diff` never skips
	  - commit gate / release guard / dangerous command guard
	    unchanged
	  Final verification:
	  - real MCP env-on verified: `B1E_REAL_MCP_ENV_ON_VERIFIED=yes`
	  - latest HEAD before closeout: `54d3c69`
	  - VERSION: `0.10.0`
	  - no tag
	  **B1 chain closed.**
	- **v0.11.0-C0**: repo/codebase map read-only audit completed.
	  Audited 14 files across worker, MCP server, cache, router,
	  preclassifier, hooks, ledger, and config layers.  Found no
	  existing persistent repo map, module ownership, test-to-module
	  mapping, subsystem awareness in diff review, or file/module
	  dimensions in ledger.  Designed schema v1 with 8 subsystems,
	  heuristic role classification, risk tags, entrypoint detection,
	  and name-based test mapping inference.  Recommended phased
	  integration: C1 generator only → C2 MCP tool → C3 test-plan
	  advisory → C4 review context → C5 optional SessionStart preload.
	  Verdict: PROCEED to C1 implementation.
	- **v0.11.0-C1**: repo map generator implemented
	  (`tools/local_llm_repo_map.py`).  Heuristic-only, no model
	  calls, no MCP integration, no ledger writes, read-only scan.
	  Schema v1: file classification (19 roles), risk tags (15 types),
	  entrypoint detection (name + content heuristics), test mapping
	  inference (name-based, 23 mappings detected in dogfood),
	  subsystem grouping (14 subsystems), deterministic output order,
	  binary detection, sensitive path exclusion.  CLI with --json
	  and --write flags for manual inspection.  93 focused tests
	  (`tests/test_repo_map.py`).  Dogfood on local-llm-pipeline:
	  171 files, git_head=`a5144d2`, all key roles verified, no
	  sensitive content in output.  Full suite 1561 passed.
	  Advisory-only foundation — no MCP tool, no review/test-plan/hook
	  integration yet.
	- **v0.11.0-C1 dogfood**: verified.  `tools/local_llm_repo_map.py`
	  runs standalone via `--root . --json`.  Output: `ok=true`,
	  `schema_version=1`, `git_head=d223063`, `total_files=171`,
	  `test_mapping entries=23`.  All key roles verified:
	  `mcp_server`, `worker`, `router`, `debate`, `ledger`, `hook`,
	  `docs`, `test`.  `.local_llm_out/` correctly ignored, no
	  sensitive content/body in output.  Tests: 93/93 repo map,
	  146/146 grouped, 1561/1561 full suite.  13/13 run_checks.
	  Commit-gate review `ok=true`.  Boundaries confirmed: no model
	  calls, no MCP tool, no ledger writes, no review/test-plan/hook
	  integration.  Advisory-only foundation.  VERSION remains
	  `0.10.0`, no tag.  **C1 line closed.**
	- **v0.11.0-C2**: MCP tool `local_repo_map` exposed as 10th tool.
	  `call_repo_map()` in MCP server — heuristic-only, no model
	  calls, manual invocation only.  Calls `local_llm_repo_map.py`
	  directly (no subprocess).  Ledger records written with 5 new
	  extra keys (`repo_map_schema_version`, `repo_map_total_files`,
	  `repo_map_test_mappings`, `repo_map_cache_hit`,
	  `repo_map_advisory_only`).  Response carries
	  `advisory_only=true`, `manual_only=true`.  33 focused tests
	  (`tests/test_mcp_repo_map.py`).  3 existing server tests
	  updated (tool count 9→10).  Full suite 1594 passed.
	  Not connected to review/test-plan/hooks/auto-invocation.
	  **C2 implementation complete.**
	  - **v0.11.0-C2 real MCP dogfood**: verified.  `local_repo_map`
		  visible as 10th real MCP tool via MCP tools/list; original
		  9 tools intact.  Real MCP call returned `ok=true`,
		  `schema_version=1`, `total_files=172`, `cache_hit=false`,
		  `advisory_only=true`, `manual_only=true`.  Key roles
		  verified: `mcp_server`, `worker`, `router`, `debate`,
		  `ledger`, `hook`, `project_status`, `test`.  Parameter
		  behavior verified: `include_tests=false` (115 files, 0 test),
		  `include_docs=false` (129 files, 0 docs), `max_files=5`
		  (exactly 5 files, deterministic), invalid path (`ok=false`,
		  `error_type=invalid_path`), `write_output=true` (output
		  `.local_llm_out/repo_map.json`, git-clean).  Ledger
		  verified: `mcp_tool_name=local_repo_map`,
		  `source=manual-mcp`, `profile=repo_map`, `model=none`,
		  `provider=heuristic`, `repo_map_schema_version=1`,
		  `repo_map_advisory_only=true`.  No auto integration:
		  no review_diff/test-plan/hooks/gate changes.
		  Working tree clean.  VERSION remains `0.10.0`, no tag.
		  **C2 line closed.**
		- **v0.11.0-C3-A**: repo map context helper
		  `build_repo_map_context_for_path()` added (commit `9919b3c`).
		  Pure helper — no filesystem I/O, no model calls, no MCP
		  calls.  Extracts target role/subsystem/risk_tags,
		  related_tests, subsystem_peers from a repo map dict.
		  Returns `advisory_only=true`.  No MCP schema change,
		  no `local_generate_test_plan` integration yet, no worker
		  change, no ledger change, no hooks change.  17 new tests,
		  110 repo map tests, 1611 full suite, 13/13 run_checks.
		  Commit-gate `ok=true`.
		- **v0.11.0-C3-A dogfood**: verified.  Target
		  `tools/local_llm_mcp_server.py` → `role=mcp_server`,
		  `subsystem=mcp`, `risk_tags=["mcp"]`,
		  `entrypoint=true`.  `related_tests` returned
		  `tests/test_mcp_server.py`.  `tests/test_mcp_repo_map.py`
		  not mapped — known limitation of conservative name-based
		  substring inference, not a helper failure.  `subsystem_peers`
		  returned `.mcp.json` (role=mcp_config).  Cap behavior,
		  unknown path, Windows path normalization, safety scan
		  all passed.  Working tree clean.  VERSION remains
		  `0.10.0`, no tag.  **C3-A line closed.**
		- **v0.11.0-C3-B**: `local_generate_test_plan` repo map advisory
		  opt-in.  New optional params: `use_repo_map` (default false),
		  `repo_map_path`, `repo_map_max_files`.  When
		  `use_repo_map=true`, loads or builds a repo map, extracts
		  advisory context via the C3-A helper, and injects it as a
		  prompt prefix.  Missing/corrupt repo map never fails the
		  test-plan call — returns warning instead.  Response adds
		  additive metadata: `repo_map_context_used`,
		  `repo_map_related_tests_count`, `repo_map_subsystems`.
		  Ledger records 4 new extra keys.  Worker `build_prompt`
		  reads `LOCAL_LLM_REPO_MAP_CONTEXT` env var (never crashes
		  on bad JSON).  Default path unchanged:
		  `use_repo_map=false` → identical behaviour to before.
		  No MCP schema breaking changes, no hooks/review/debate/gate
		  changes.  `local_repo_map` remains manual-only.  22 new
		  tests, 233 repo-map+MCP, 1633 full suite, 13/13 run_checks.
		  VERSION remains `0.10.0`, no tag.  **C3-B line closed.**
		- **v0.11.0-C3-B real MCP dogfood**: verified.  Claude Code / MCP server
		  restarted with new schema loaded — `repo_map_context_used` present
		  in real MCP response (schema reload confirmed, not a stale process).
		  All 8 steps passed via real MCP calls:
		  (1) default mode: `repo_map_context_used=false`, no warning,
		  no repo map injection, ledger clean.
		  (2) opt-in mode: `use_repo_map=true` → `repo_map_context_used=true`,
		  `repo_map_related_tests_count=1`, `repo_map_subsystems=["mcp"]`.
		  (3) explicit `repo_map_path`: `repo_map_context_used=true`.
		  (4) missing path fallback: in-memory build succeeded,
		  `repo_map_context_used=true`.
		  (5) corrupt path: `repo_map_context_warning="repo_map_corrupt"`,
		  no failure, graceful degrade, warning recorded in ledger.
		  (6) ledger verification: default call no `test_plan_repo_map_used`;
		  opt-in/explicit/missing fallback `test_plan_repo_map_used=true`;
		  corrupt call `test_plan_repo_map_warning=repo_map_corrupt`.
		  (7) boundary integrity: MCP tool count 10, `local_repo_map`
		  manual-only, no hooks/review/debate/gate/release/danger guard
		  changes, git clean, no code/docs touched.
		  `C3B_REAL_MCP_DOGFOOD_VERIFIED=yes`.
		  VERSION remains `0.10.0`, no tag.  **C3-B implementation line
		  closed — both direct Python and real MCP paths verified.**
		- **v0.11.0-C3-C**: policy/docs sync completed.
		  Documented `local_generate_test_plan` repo-map advisory behavior in
		  `docs/mcp-task-policy.md` and `CLAUDE.md`: default-off behavior
		  (`use_repo_map=false`), opt-in params (`use_repo_map`, `repo_map_path`,
		  `repo_map_max_files`), advisory-only nature, corrupt/missing fallback
		  semantics, safety boundaries (no commit gate / release guard / dangerous
		  command guard / hook auto-trigger / review_diff / debate change;
		  `local_repo_map` remains manual-only), ledger keys, and examples.
		  No code / test / MCP schema / worker / ledger / hook / VERSION / tag
		  changes.  **C3 chain complete** (C0 audit → C1 generator → C2 MCP tool
		  → C3-A context helper → C3-B implementation + real MCP dogfood → C3-C
		  docs/policy sync).
		- **v0.11.0-C3 final closeout**: all C3 sub-phases closed and verified.
		  **C3 chain complete** (C0 audit → C1 generator → C1 dogfood closeout →
		  C2 MCP tool → C2 dogfood closeout → C3-A context helper → C3-A dogfood
		  closeout → C3-B implementation → C3-B real MCP dogfood → C3-B closeout →
		  C3-C policy/docs sync → C3-C typo fix).  Capabilities delivered: repo
		  map heuristically generable; `local_repo_map` exposed as 10th manual MCP
		  tool (manual-only); context helper extracts target role / subsystem /
		  risk_tags / related_tests / subsystem_peers; `local_generate_test_plan`
		  supports `use_repo_map=true` opt-in with advisory-only context injection;
		  missing/corrupt repo map never fails test-plan; default behavior unchanged.
		  Boundaries held: no commit gate / release guard / dangerous command guard /
		  hook auto-trigger / review_diff / debate change; no automatic repo map
		  invocation; no VERSION bump; no tag; no zip; no push.  Validation: 1633/1633
		  full suite, 13/13 run_checks, commit-gate reviews passed, real MCP dogfood
		  verified for C2 and C3-B.  VERSION remains `0.10.0`, no tag.
		  Next: v0.11.0-D read-only planning audit for test failure classifier.

## v0.10.0 - 2026-05-24

- C2 streaming stdout contract fix (v0.10.0-A through v0.10.0-D, chain closed).
  Fixed a `stdout` double-serialization in the streaming subprocess path
  (`run_subprocess_streaming` line 1417) that caused `load_worker_output` to
  fail on streaming results, returning `missing_worker_output`.  Added
  `_parse_worker_stdout` compat parser with 5 strategies (dict pass-through,
  direct file path, raw `JSON:` markers, JSON-encoded string, double-serialized
  legacy), fixed a file-path-vs-stdout bug at line 1413, and unified the
  streaming producer to pass parsed dicts directly.  25 targeted tests.
  Real MCP smoke passed: `local_summarize_file`, `local_review_diff` both
  returned dict payloads with no errors.  v0.10.0-E cleanup (removing compat
  fallbacks) remains explicitly deferred.  See
  `docs/C2_STREAMING_CONTRACT_AUDIT.md` for full design audit.
- P6-B2-C call ledger write-failure observability (v0.10.0-G).  Previously,
  `record_call()` returned `False` on write failure but callers discarded the
  return value and swallowed exceptions, making ledger write loss completely
  silent.  Added `_record_write_failure()` helper (bounded JSONL diagnostic
  log, self-truncating at 1 MB, never raises) and wired it into `record_call()`'s
  `except` block.  `mcp_doctor` gained 3 ledger health checks: file size (WARN
  at 10 MB, FAIL at 100 MB), file presence, and write-failure log status.  13
  targeted tests.  Doctor immediately surfaced a pre-existing test artifact
  (`RuntimeError("nope")` from `test_record_call_never_raises` using an
  unpatched `LEDGER_DIR`) — benign, confirmed not a production bug.
  `record_call()` still returns `bool`, still never raises; worker and debate
  call sites unchanged.  1234 passed, 13/13 run_checks.
- M3 manual call ledger rotation (v0.10.0-H).  Added `rotate_ledger()` helper
  that archives the active `calls.jsonl` by renaming it to a timestamped file
  (`calls.<ISO-date>.jsonl`).  New `call_ledger_cli.py rotate` subcommand with
  `--archive-name`, `--dry-run`, `--path`, and `--format` flags.  `mcp_doctor`
  large-ledger WARN/FAIL messages now reference the rotate command.
  `record_call()` unchanged — still append-only, never-raise, no automatic
  stat or rotation.  `read_records()` unchanged — active file only; archived
  ledgers readable via `--path`.  No automatic truncation, no data deletion,
  no compression.  9 targeted tests.  1243 passed, 13/13 run_checks.
- H6 worker error classification disambiguation (v0.10.0-I → v0.10.0-J,
  follow-up at `b41ec97`).  H6-I read-only audit identified colliding
  substring heuristics in `classify_error()` (timeout before connection,
  port numbers captured as 5xx backend errors, generic JSON references
  captured as invalid_json).  H6-J at `4f4b648` narrowed JSON/parse
  matches, added word-boundary gating on 5xx backend-error codes (prevents
  "port 5001" false positive), moved 5xx/server-error to Layer 6.
  Follow-up `b41ec97` swapped the generic substring order so
  connection-context matching runs before generic timeout matching —
  messages like "connection timed out" now correctly classify as
  `backend_unreachable` instead of `timeout`.  `classify_error()` signature
  unchanged (`tuple[str, str]`); `error_type` value space unchanged
  (6 values: `timeout`, `backend_unreachable`, `empty_response`,
  `invalid_json`, `backend_error`, `unknown_error`); no `error_subtype`;
  no call ledger schema change; no caller changes; no migration required
  for historical ledger records.  `isinstance` checks (Layer 1) remain
  first: `requests.Timeout` → `timeout`, `requests.ConnectionError` →
  `backend_unreachable`.  4 new tests (connection-timed-out → backend_unreachable);
  generic "request timed out" regresses to `timeout`.  1261/1261 passed,
  13/13 run_checks, commit-gate ok=true.  H6 chain closed.
- M7 cost-estimate credibility — execution-location classification
  (v0.10.0-L).  Added `classify_execution_location()` →
  `local`/`lan`/`remote`/`unknown` and `classify_cost_confidence()` →
  `high`/`medium`/`low`/`none`.  Two additive top-level fields in
  `build_record()`: `execution_location`, `cost_confidence`.  Does NOT
  compute exact LAN dollar costs, does NOT expand `LOCAL_LLM_COST_TABLE`,
  does NOT change `estimated_cost_cny` behavior.  Old records (missing the
  new fields) are fully readable — CLI `summary` displays them as
  `unknown`, CLI `by-location` groups them under `<none>`.  New
  `breakdown_counts()` helper and `_print_breakdown()` in CLI.  32 new
  tests (19 classification + 4 build_record + 2 breakdown_counts + 7 CLI).
  1288/1288 passed, 13/13 run_checks.  Deferred: exact LAN dollar cost
  accounting, `LOCAL_LLM_COST_TABLE` expansion, streaming cost passthrough
  (v2-B), cache-tier estimation (v2-C).
- P6-B3-B/H5 endpoint resolution unification (v0.10.0-M).  Extracted shared
  `_resolve_provider()` and `_resolve_endpoint()` helpers from worker's
  `resolve_config()` so debate reuses the same priority chain.  Debate now
  supports `LOCAL_LLM_PROVIDER` env var, `--base-url` CLI flag, and provider
  auto-detection — previously it ignored all three and always defaulted to
  ollama + localhost:11434 when no env was set.  Worker behavior unchanged.
  12 new tests.  1300/1300 passed, 13/13 run_checks.  `_MTP_ENDPOINTS`
  hardcode NOT changed (display-only, does not affect routing).
- Active v0.10.0 maintenance chain closed at HEAD `55a34b8`
  (`v0.9.8-14-g55a34b8`).  1300/1300 passed, 13/13 run_checks.  P5-C
  (V4-Flash `_env` wiring / model warmup / provider hint) is deferred
  indefinitely — not a v0.10.0 blocker.  Next: release-prep read-only audit.

## v0.9.8 - 2026-05-23

**v0.9.8 is a reliability, observability, and cost-discipline release**
spanning 47 commits from v0.9.7. It delivers health telemetry isolation
(P1-H), a full call-ledger cost-discipline chain (P2), escalation cost
control with env-knob gates (P3), a worker-pool dry-run diagnostic (P4),
a V4-Flash experimental profile (P5), runtime reliability and
observability fixes across worker timeout propagation, call-ledger read
diagnostics, and bounded ollama-list subprocess (P6), and hook
silent-failure diagnostics covering gate state persistence, auto-worker
spawn failures, MCP shape warnings, and doctor checks (P7). One test-only
hotfix unblocks the release gate (stale mock signature alignment).

- Test-only hotfix: align stale `fake_run_subprocess` mock in
  `tests/test_local_llm_v093.py::test_mcp_summarize_file_success_does_not_disconnect`
  with the real `run_subprocess` signature, which gained an
  `extra_env=None` keyword in P2-C1.1 (`cc1bcbf`). The mock previously
  raised `TypeError`, which was caught by `handle_tools_call` and
  surfaced as `ok=False`, breaking the success-path acceptance check.
  Fix is a one-line signature update — no production code, no
  behavior change, no other test touched. Unblocks the v0.9.8 release
  hard gate (`py -m pytest` full suite: 1195 → 1196 passed).
- Hook silent-failure diagnostics P7-B.1 verification + P7-C phase
  closeout. **P7 chain closed** (P7-A → P7-B → P7-B.1 → P7-C).
  P7-B.1 (read-only, no commit) verified that the P7-B commit
  `d0ae7fd` touched only the 9 allowed files (3 under
  `tools/claude_hooks/`, 3 hook tests, 3 docs/status), produced zero
  diff against the forbidden-files guard, and that the substance of
  all five items (C3, C4, C5/C6, M4, M5/M6) is recorded across
  `PROJECT_STATUS.md`, `CHANGELOG.md`, and
  `docs/P6_RUNTIME_RELIABILITY_OBSERVABILITY_AUDIT.md` §13. The only
  observed gap was a stale audit-doc footer phrase ("HEAD pending
  commit") which is back-filled with `d0ae7fd` as part of this
  P7-C closeout — no separate docs-only churn commit was filed.
  **P7 phase result:** five previously-silent failure modes are now
  structured-event observable while every caller-visible behavior is
  preserved bit-for-bit — `state_load_failed` /
  `state_save_failed` to `hook-events.jsonl`; auto-worker
  spawn/log-write failures to `.local_llm_out/auto/_spawn_failures.log`
  (self-truncating at 1 MB); three additive `mcp_doctor` auto-worker
  checks; `mcp_shape_unknown` on unrecognized MCP `tool_response`
  shapes (4 reasons). **Explicitly frozen / deferred at P7-C:**
  C2 (streaming double-serialization), H6 (`classify_error` rewrite),
  P6-B2-C (`record_call()` write-failure propagation), M3 (ledger
  rotation), M7 (cost-estimate accuracy), P6-B3-B/H5 (MTP endpoint
  config), P5-C. **Possible future directions, none authorized:**
  P6-B2-C design-only planning; P6-B3-B design-only planning;
  P7-D streaming contract correction; release prep. **No release at
  P7-C:** VERSION remains `0.9.7`; HEAD carries no tag; no release;
  no zip. No `tools/**` / `tests/**` / `VERSION` / `CLAUDE.md` /
  `docs/mcp-task-policy.md` / tag / release changes in P7-C.
- Hook silent-failure diagnostics bundle P7-A + P7-B. P7-A (audit at
  baseline `9d8af1d`) grouped remaining P6 deferred items by risk +
  subsystem + compatibility impact across 8 source files, recommending
  a bundled diagnostics-only slice. P7-B implements the recommendation:
  **(C3)** `mcp_gate.load_state` emits `state_load_failed` event via
  the existing `log_event(config_dir, …)` sink on `JSONDecodeError` /
  read failure, return value (the `_STATE_DEFAULTS` dict) is unchanged.
  **(C4)** `mcp_gate.save_state` emits `state_save_failed` on write
  failure, return value unchanged. **(C5/C6)** `mcp_auto_worker`
  introduces a bounded `_record_spawn_failure()` helper (JSONL,
  self-truncating at 1 MB, fire-and-forget, nested `except: pass`)
  and wires it into all 4 spawn paths — `spawn_background`,
  `spawn_local_check` (preamble log + Popen), `spawn_summarize_file`
  (log write), `spawn_review_diff` (stdin write + log write). Failures
  land in `.local_llm_out/auto/_spawn_failures.log`. Fire-and-forget
  semantics preserved. **(M4)** `mcp_doctor.run_checks` adds 3 additive
  checks: `auto_dir_present` (WARN on missing, OK on present),
  `auto_results_count` (OK/WARN at >50), `spawn_failures_log` (OK
  absent/empty, WARN non-empty, FAIL >1 MB). No existing-check
  semantics changed. **(M5/M6)** `_extract_read_info` and
  `review_tool_succeeded` accept an optional `config_dir` parameter
  (default `None` — legacy callers continue to work passively); on
  unrecognized non-empty `tool_response` shape, log
  `mcp_shape_unknown` with one of four reasons
  (`no_known_read_shape` / `empty_text_from_nonempty_response` /
  `text_not_json` / `result_not_dict`). Return values preserved
  bit-for-bit. New helper `_log_mcp_shape_unknown` swallows its own
  failures. **All five items are diagnostics-only — no business
  behavior change anywhere.** 20 new tests added: 12 in
  `tests/test_mcp_gate_boundary.py`, 4 in `tests/test_mcp_auto_worker.py`,
  7 in `tests/test_mcp_doctor.py`. Hook regression 115 passed;
  P4/P5/P6/call_ledger/check/stop_hook regression 321 passed.
  **Explicitly NOT in this slice:** C2 (streaming
  double-serialization), H6 (`classify_error` rewrite), P6-B2-C
  (`record_call()` write-failure propagation), M3 (ledger rotation),
  M7 (cost-estimate accuracy), P6-B3-B/H5 (MTP endpoint config),
  P5-C. Forbidden files (zero diff against): `local_llm_mcp_server.py`,
  `local_llm_worker.py`, `local_llm_debate.py`, `local_llm_router.py`,
  `call_ledger*.py`, `health_store.py`, `local_llm_check.py`,
  `local_llm_profiles.json`, `local_llm_tasks.json`, `CLAUDE.md`,
  `docs/mcp-task-policy.md`, `VERSION`. No tag, no release.
- Runtime Reliability / Observability P6-C: phase closeout. **P6 chain
  closed** (P6-A → P6-A.1 → P6-B1 → P6-B1.1 → P6-B1.2 → P6-B2-A →
  P6-B2-B → P6-B2-D → P6-B3 → P6-B3-A → P6-B3-A.1 → P6-C). P6 phase
  result: subprocess timeout in `_wrap_worker_call` now produces
  `error_type="timeout"` and reaches the health-store penalty path
  (C1 + H2); `health_store.last_timeout` is cleared on subsequent
  success; `tools/call_ledger.py::read_records_with_diagnostics()`
  exposes corrupt/skipped JSONL line counts (M1/M2);
  `call_ledger_cli.py --diagnostics` makes those diagnostics
  operator-visible; `tools/local_llm_check.py::run_ollama_list()` is
  bounded by a 30s subprocess timeout (M8) — health check can no
  longer wedge on a stalled ollama CLI. **Explicitly frozen /
  deferred:** P6-B2-C (write-failure propagation), P6-B3-B (MTP
  endpoint hardcoding / configuration surface, same item as H5), C2
  (streaming double-serialization), C3/C4 (gate state persistence),
  C5/C6 (auto-worker / audit event observability), H1, H3/H4, H6,
  M3–M7, P5-C. **No release**: VERSION remains `0.9.7`; HEAD carries
  no tag; no release; no zip. **Possible future directions, none
  authorized by P6-C:** P7 read-only audit of remaining hook/gate
  observability; P6-B2-C design-only planning; P6-B3-B design-only
  planning; release prep — each requires a separately approved plan.
  No `tools/**` / `tests/**` / `VERSION` / `CLAUDE.md` /
  `docs/mcp-task-policy.md` / tag / release changes in P6-C.
- Runtime Reliability / Observability P6-B3 + P6-B3-A + P6-B3-A.1: local
  check timeout fix + docs closeout. P6-B3 (audit, baseline `3680464`)
  identified unbounded `subprocess.check_output(["ollama", "list"])` in
  `tools/local_llm_check.py::run_ollama_list()` (M8): the health check
  itself hangs indefinitely if the ollama CLI blocks. P6-B3-A
  (`bfe537e`) bounds the subprocess: signature becomes
  `run_ollama_list(timeout: int = 30)`; uses
  `subprocess.run([...], capture_output=True, text=True, timeout=timeout)`;
  `TimeoutExpired` returns a failed `CheckResult` with
  `"ollama list timed out after 30s"`; `FileNotFoundError` returns
  `"ollama binary not found"`; nonzero exit surfaces stderr. Sole caller
  (`build_probe_report()`) passes no argument — default 30s applies,
  fully backward compatible. 4 new tests in `tests/test_check.py` (ok,
  timeout, missing binary, nonzero exit) → 10 passed; P4/P5/P6/call_ledger
  regression 180 passed. `docs/P6_RUNTIME_RELIABILITY_OBSERVABILITY_AUDIT.md`
  M8 row marked CLOSED. P6-B3-A.1 (this entry) docs closeout: records
  the audit baseline and `bfe537e` landing, defers P6-B3-B (MTP endpoint
  hardcoding / false-positive risk — no `LOCAL_LLM_MTP_ENDPOINTS`, no
  `--skip-mtp`, no host auto-detection), reaffirms deferral of P6-B2-C,
  C2, C3/C4, C5/C6, H1/H3/H4/H6, M3–M7, P5-C. No MTP endpoint config,
  no `all_ok` change, no P4 probe contract change,
  no `recommend_profiles()` change, no router / worker / MCP server /
  ledger / health_store / hooks / profile / task / `CLAUDE.md` /
  `docs/mcp-task-policy.md` / `VERSION` / tag / release changes.
  VERSION remains `0.9.7`; HEAD carries no tag; no release.
- Runtime Reliability / Observability P6-B2-A + P6-B2-B + P6-B2-D:
  call ledger read diagnostics + CLI reporting + docs closeout.
  P6-B2-A (`ec74898`) adds `read_records_with_diagnostics()` to
  `tools/call_ledger.py` — returns `{records, total_lines, empty_lines,
  malformed_json_lines, non_dict_lines, skipped_lines, errors}` with
  errors bounded to 20; `read_records()` unchanged (backward compatible).
  P6-B2-B (`63693c7`) adds `--diagnostics` flag to `call_ledger_cli.py`;
  `summary` command displays skipped/corrupt line counts and error
  examples; JSON output wraps summary + diagnostics in combined object
  with `_diagnostics` sub-key; default output unchanged without flag.
  P6-B2-D (this entry) docs closeout: records both slices, defers
  P6-B2-C (write-failure propagation) and remaining P6 items (C2–C6,
  H3–H6, M3–M8). 222 tests passed. No `call_ledger.py` schema change,
  no `VERSION` / worker / MCP server / router changes.
- Runtime Reliability / Observability P6-B1 + P6-B1.1 + P6-B1.2:
  timeout observability fix + test hygiene + docs closeout. P6-B1
  (`4fcd83a`) fixes C1 + H2: subprocess timeout in `_wrap_worker_call`
  now produces `error_type="timeout"` instead of `worker_failed_no_output`
  (both streaming and non-streaming paths); new `_extract_profile_from_cmd`
  helper for health-store attribution; `tools/health_store.py` now clears
  stale `last_timeout` after subsequent success (was `setdefault`-locked);
  non-timeout failure preserves `last_timeout`. 15 focused tests in
  `tests/test_p6_timeout_observability.py`; 354 regression passed.
  P6-B1.1 (`a5637ee`) removes the fragile working-tree-diff boundary test
  and `_P6_B1_ALLOWED` exemption from `tests/test_p5_v4_flash_experimental.py`;
  15 static P5 invariant tests retained. P6-B1.2 (this entry) docs closeout:
  records completed slices, defers C2–C6/H3–H6/M1–M8, notes P6-B2
  (call_ledger observability) as recommended but not authorized. No
  router / worker / ledger / hooks / VERSION / tag changes.
- Runtime Reliability / Observability P6-A + P6-A.1: read-only audit +
  docs-only boundary lock-in. P6-A inspected 17 files across 4 layers
  (worker, MCP server, hook/gate, observability) and identified 6
  CRITICAL, 6 HIGH, 8 MEDIUM, and 5 LOW findings. Key themes: silent
  failure is the default across ledger/gate-state/health-store;
  subprocess timeout is systematically misreported as
  `worker_failed_no_output` in all 6 `_wrap_worker_call`-routed tools;
  `last_timeout` in health_store is never cleared after later success.
  P6-A.1 creates `docs/P6_RUNTIME_RELIABILITY_OBSERVABILITY_AUDIT.md`
  with full findings table, cross-component themes, and P6-B1 as the
  smallest next implementation slice: fix timeout propagation (C1),
  connect timeout to health-store penalty, clear stale `last_timeout`
  after success (H2), plus focused regression tests. Explicitly defers
  C2–C6, all other HIGH items, and all MEDIUM items. **P6-B1 is NOT
  authorized by P6-A.1** and requires separate approval.
  `PROJECT_STATUS.md` adds P6-A / P6-A.1 / P6-B1 rows. No `tools/**` /
  `tests/**` / `VERSION` / tag changes. VERSION remains `0.9.7`; HEAD
  carries no tag; no release.
- V4-Flash Experimental Profile P5-D: docs/status closeout for the
  P5 chain. **P5 chain closed** (P5-A → P5-B → P5-D; P5-C
  explicitly deferred / not authorized). P5 core objective
  reaffirmed: `v4_flash_local_experimental` profile exists as
  manual-only experimental with full policy boundary; 16 focused
  tests; no router / MCP server / worker / ledger / P4 probe /
  tasks.json changes anywhere in the P5 chain. P5-C (`_env` wiring,
  model warmup, provider hint) remains not authorized — each would
  require a separately approved plan. `PROJECT_STATUS.md` flips
  P5-D from `Not started` → `Done`. `docs/P5_V4_FLASH_EXPERIMENTAL_PROFILE_PLAN.md`
  updated with §10 closeout section restating the completed chain,
  deferred items, and unchanged boundaries. No `tools/**` /
  `tests/**` / `VERSION` / tag / release changes. VERSION remains
  `0.9.7`; HEAD carries no tag; no release.
- V4-Flash Experimental Profile P5-B: minimal implementation slice.
  Adds `v4_flash_local_experimental` profile to
  `tools/local_llm_profiles.json` (`model=v4-flash`,
  `risk_level="experimental"`, manual invocation only — no task
  default points to it, router does not auto-select it). Adds
  `"experimental"` to `tools/validate_configs.py::VALID_RISK_LEVELS`
  (Option A alignment — `tools/profile_policy.py:33` already
  accepted it). Updates `tests/test_profile_policy.py`
  `test_no_profile_marked_experimental_yet` →
  `test_exactly_one_experimental_profile`. New
  `tests/test_p5_v4_flash_experimental.py` (16 tests) covering
  profile shape, validation acceptance, policy derivation, router
  non-auto-selection, explicit override, MCP tool count, P4 probe
  invariants, ledger schema compatibility, and the
  `provider=tongyi` stale reference removal. Stale-doc
  reconciliation: `docs/MCP_COST_DISCIPLINE_PLAN.md:367`
  `provider=tongyi` → `provider=auto-detected`. No router / MCP
  server / worker / ledger / hook / VERSION / tag changes.
  VERSION remains `0.9.7`; HEAD carries no tag; no release.
- V4-Flash Experimental Profile P5-A: read-only audit + boundary
  lock-in. Adds `docs/P5_V4_FLASH_EXPERIMENTAL_PROFILE_PLAN.md`
  recording: P5's hard boundary as a single profile-entry change
  (no routing change, no new MCP tool/parameter, no new provider,
  no `tasks.json` default change, no P3 escalation wiring, no P4
  probe wiring, no ledger schema change, no worker pool, no model
  provisioning); the current architecture findings
  (`tools/validate_configs.py:22` does not include `"experimental"`
  in its `VALID_RISK_LEVELS` set while `tools/profile_policy.py:33`
  does — a latent divergence P5-B must reconcile; profile schema
  required fields are `model` / `risk_level` / `use_for`; policy
  derivation in `_derive_experimental` / `_derive_auto_allowed` /
  `_derive_default_review_necessity` already covers experimental
  profiles correctly, so the policy machinery is data-ready; router
  accepts `--profile` override; 8 of the 9 worker-backed MCP tools
  already accept a `profile` parameter; worker only knows
  `"ollama"` and `"openai-compatible"` providers — there is no
  `"tongyi"` provider and the `MCP_COST_DISCIPLINE_PLAN.md:367`
  reference to `provider=tongyi` is stale); explicit non-goals; the
  smallest viable P5-B slice (Option A — one profile entry in
  `tools/local_llm_profiles.json` named `v4_flash_local_experimental`
  with `risk_level="experimental"` + a one-line allowlist alignment
  in `tools/validate_configs.py`; Option B — same profile entry
  with `risk_level="high"` and the latent divergence left in
  place); an 11-item test plan; a 9-row risk list; and 8 stop
  conditions that escalate to human review if scope creeps toward
  routing/escalation/worker-pool/new-provider behavior.
  `PROJECT_STATUS.md` splits the original `P5 | Not started` row
  into P5-A (Done) / P5-B (Not started) / P5-C (optional) / P5-D
  (optional, closeout). **P5-B is not authorized by P5-A** and
  requires separate approval. No `tools/**` / `tests/**` /
  `tools/local_llm_profiles.json` / `tools/validate_configs.py` /
  `tools/local_llm_router.py` / `tools/local_llm_mcp_server.py` /
  `tools/local_llm_worker.py` / `tools/local_llm_check.py` /
  `tools/call_ledger.py` / `tools/call_ledger_cli.py` /
  `tools/local_llm_tasks.json` / `tools/profile_policy.py` /
  `tools/health_store.py` / `tools/claude_hooks/` / `CLAUDE.md` /
  `docs/mcp-task-policy.md` / `docs/MCP_COST_DISCIPLINE_PLAN.md` /
  `VERSION` / tag changes in P5-A. VERSION remains `0.9.7`; HEAD
  carries no tag; no release.
- Worker Pool Dry-Run P4-D: docs/status closeout for the P4 chain.
  Flips `PROJECT_STATUS.md` P4-D from `Not started, optional` →
  `Done` and records P4 as closed (P4-A → P4-B → P4-D), with P4-C
  (`configurable worker list`) explicitly **skipped / deferred** —
  not required for the P4 core objective ("probe-only diagnostic,
  no scheduling"); may be revived only under a separately approved
  plan that re-cites the boundary contract in
  `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` §2 / §4 / §6 / §8. P4 core
  objective reaffirmed: `tools/local_llm_check.py --probe-workers
  --json` emits a structured diagnostic report
  (`PROBE_REPORT_SCHEMA_VERSION = 1`) reusing existing endpoint
  sources only; default invocation behavior preserved; MCP
  `call_local_check` contract unchanged; `routing_changed` and
  `ledger_stamped` baked in as the literal boolean `False`. Adds a
  "Resolution / Closeout (recorded at P4-D)" section to
  `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` documenting the closed
  state, the explicit P4-C deferral, and the unchanged hard
  boundary (no scheduler, no daemon, no queue loop, no background
  worker, no automatic multi-host execution, no router changes, no
  MCP contract change, no ledger stamping, no profile mutation).
  P5 (V4-Flash local experimental profile) is the next runway,
  starting from a P5-A read-only audit. No `tools/**` / `tests/**`
  / `tools/local_llm_check.py` / `tools/local_llm_mcp_server.py` /
  `tools/local_llm_router.py` / `tools/call_ledger.py` /
  `tools/call_ledger_cli.py` / `tools/local_llm_profiles.json` /
  `tools/local_llm_worker.py` / `tools/health_store.py` /
  `tools/claude_hooks/` / `CLAUDE.md` / `docs/mcp-task-policy.md`
  / `docs/MCP_COST_DISCIPLINE_PLAN.md` / `VERSION` / tag changes.
  VERSION remains `0.9.7`; HEAD carries no tag; no release.
- Worker Pool Dry-Run P4-B: smallest viable implementation slice per
  `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` §5. Adds two opt-in CLI flags
  to `tools/local_llm_check.py`:

  - `--probe-workers` — runs a diagnostic worker-pool dry-run probe.
  - `--json` — when combined with `--probe-workers`, emits the probe
    report as a single JSON object on stdout (no human-readable flow);
    no-op for probing without `--probe-workers`.

  Adds a `build_probe_report()` helper and a
  `PROBE_REPORT_SCHEMA_VERSION = 1` constant. The probe reuses
  existing endpoint sources only — resolved Ollama URL,
  `OPENAI_COMPAT_BASE`, and `_MTP_ENDPOINTS` — for a total of 5
  configured workers in the current zero12 environment. Each
  configured worker has `{id, host, endpoint, endpoint_type}`;
  reachable workers also carry `reachable=True`; unreachable workers
  carry `reachable=False` and `error`; `probe_errors` mirrors them
  with `{id, error}`. `routing_changed` and `ledger_stamped` are
  baked in as the literal boolean `False` in both the helper and the
  emitted JSON. Probe failures never raise — network errors,
  timeouts, and a missing `requests` library all land in
  `unreachable_workers` / `probe_errors`.

  When `--probe-workers` is passed alone (no `--json`), the existing
  human-readable health check runs unchanged and a "Worker Pool
  Dry-Run Probe (diagnostic only)" section is appended at the end
  with a count summary, per-unreachable details, and the literal
  `routing_changed: False` / `ledger_stamped: False` lines. Default
  invocation with no flags is byte-equivalent (modulo timestamps) to
  the pre-P4-B build — no probe runs and no probe section emits.

  New tests in `tests/test_p4_worker_pool_dry_run.py` (32 cases):
  shape and required-keys assertions, `schema_version == 1`,
  `worker_pool_dry_run_enabled is True`, `routing_changed is False`
  and `ledger_stamped is False` across both reachable and
  unreachable scenarios (each tested as the literal `bool`),
  configured-workers count matches `len(_MTP_ENDPOINTS) + 2`,
  reachable/unreachable bucketing under mocked HTTP, mixed
  reachable+unreachable parity, no-raise guarantee on network error,
  graceful handling of `requests is None`, the four CLI flag
  combinations (no flags, `--json` alone, `--probe-workers` alone,
  `--probe-workers --json`), default-path retains
  "Local LLM Environment Health Check" banner with no JSON object,
  and four source-level assertions that `build_probe_report` does
  not reference router or ledger code and that the module does not
  import `call_ledger` or `local_llm_router`. All HTTP is mocked;
  no real network is required.

  Regression: `tests/test_mcp_server.py` 68/68 passes (MCP
  `call_local_check` contract unchanged — it still shells out and
  returns `{stdout, stderr}`; the structured probe surface is
  CLI-only); `tests/test_router_profiles.py` +
  `tests/test_call_ledger.py` 130/130 passes (no routing change, no
  ledger schema change, `worker_id` / `host` slots remain
  allowlisted but unstamped).

  `PROJECT_STATUS.md` flips P4-B from `Not started` to `Done`.

  No changes to `tools/local_llm_mcp_server.py`,
  `tools/local_llm_router.py`, `tools/call_ledger.py`,
  `tools/call_ledger_cli.py`, `tools/local_llm_profiles.json`,
  `tools/local_llm_worker.py`, `tools/health_store.py`,
  `tools/claude_hooks/`, `CLAUDE.md`, `docs/mcp-task-policy.md`,
  `docs/MCP_COST_DISCIPLINE_PLAN.md`, `VERSION`, or tags. VERSION
  remains `0.9.7`; HEAD carries no tag; no release. P4-C
  (configurable worker list) and P4-D (P4 chain closeout) remain
  `Not started, optional`.
- Worker Pool Dry-Run P4-A: read-only audit + boundary lock-in. Adds
  `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` recording: P4's hard
  boundary as a probe-only diagnostic (no scheduler, no daemon, no
  multi-host dispatch, no routing change, no ledger schema change,
  no profile mutation); the current architecture findings
  (`tools/local_llm_check.py:28` `_MTP_ENDPOINTS` already probes
  three llama.cpp MTP endpoints; `call_local_check`
  (`tools/local_llm_mcp_server.py:1926`) returns stdout/stderr only;
  no per-profile host field; `worker_id` / `host` allowlisted in
  `KNOWN_EXTRA_KEYS` but never stamped today); explicit non-goals;
  the smallest viable P4-B slice (`--probe-workers --json` flag in
  `tools/local_llm_check.py`, default path byte-identical, no MCP /
  router / ledger / profile touches); the proposed structured probe
  payload shape with `routing_changed=false` and
  `ledger_stamped=false` baked in; a 9-item test plan for P4-B; a
  risk list; and explicit stop conditions that escalate to human
  review if scope creeps toward scheduling. `PROJECT_STATUS.md`
  splits P4 into P4-A (Done) / P4-B (Not started) / P4-C (optional) /
  P4-D (optional, closeout). **P4-B is not authorized by P4-A** and
  requires separate approval. No `tools/**` / `tests/**` /
  `tools/local_llm_profiles.json` / `tools/call_ledger.py` /
  `tools/call_ledger_cli.py` / `CLAUDE.md` /
  `docs/mcp-task-policy.md` / `docs/MCP_COST_DISCIPLINE_PLAN.md` /
  `VERSION` / tag changes. VERSION remains `0.9.7`; HEAD carries no
  tag; no release.
- MCP Cost Discipline P3-E: docs closeout for the P3 chain. Flips
  `PROJECT_STATUS.md` P3-E from `Not started` → `Done`, records P3 as
  closed (P3-A → P3-A.1 → P3-B → P3-C1 → P3-C2 → P3-C2.1 → P3-D →
  P3-E), reaffirms the P3 core objective (`confidence=="low"` and
  `len(uncertain_points) > 3` no longer auto-escalate by default;
  legacy restorable via `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE` /
  `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN`), and explicitly skips/defers
  optional P3-C3 (`review_necessity="user-forced"` ledger stamp) —
  not required for the P3 core objective, may be revived only under a
  separately approved plan. Adds a "Resolution (recorded at P3-E)"
  paragraph to the historical "P3-C2 Handoff / Next Window Notes"
  block so future readers know Path B (skip P3-C3) was taken.
  `docs/MCP_COST_DISCIPLINE_PLAN.md` §10 P3 row and §13.5 P3 bullet
  minimally updated to reflect chain completion. No
  `structural_risk` runtime trigger, no `escalate=true` /
  `user_requested` MCP parameter, no `tools/**` / `tests/**` /
  `CLAUDE.md` / `docs/mcp-task-policy.md` / `tools/call_ledger.py` /
  `tools/call_ledger_cli.py` / `tools/local_llm_profiles.json` /
  `VERSION` / tag changes. VERSION remains `0.9.7`; HEAD carries no
  tag; no release. Next runway: P4 (worker pool dry-run) or, if
  explicitly approved, P3-C3.
- MCP Cost Discipline P3-D: policy-doc final alignment with the
  narrowed P3 runtime. `CLAUDE.md` "Escalation Rules" and
  `docs/mcp-task-policy.md` "Escalation Rules" rewritten so the
  controller-facing rules match what `_check_quality_escalation`
  actually does after P3-C1 / P3-C2: `confidence=="low"` and
  `len(uncertain_points) > 3` no longer auto-escalate to a stronger
  model by default; legacy auto-escalation is opt-in via
  `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE=true` and
  `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN=true` (truthy values: `true` /
  `1` / `yes` / `on`, case-insensitive). The `timeout` branch is
  re-clarified as an unconditional **downgrade** to a lighter model,
  not a strong-model escalation, so it doesn't inflate cost. Both
  docs now state explicitly that there is no strict
  `escalation_reason` enum, no `structural_risk` runtime trigger, and
  no `escalate=true` / `user_requested` MCP parameter; the ledger
  `escalation_trigger` value space remains
  (`timeout` / `low_confidence` / `uncertain_points` / `unknown`).
  `PROJECT_STATUS.md` flips P3-D from `Not started` → `Done`; P3-C3
  remains `Not started (optional)` and P3-E remains `Not started`. No
  `tools/**` / `tests/**` / `tools/call_ledger.py` /
  `tools/call_ledger_cli.py` / `tools/local_llm_profiles.json` /
  `docs/MCP_COST_DISCIPLINE_PLAN.md` / `VERSION` / tag changes.
- MCP Cost Discipline P3-C2 docs/status closeout + handoff checkpoint:
  `PROJECT_STATUS.md` flips P3-C2 from `In review` → `Done (6669bae)`,
  adds an explicit P3-C2.1 row, and appends a "P3-C2 Handoff / Next
  Window Notes" section recording the clean baseline (HEAD `6669bae`,
  `git describe v0.9.7-24-g6669bae`, VERSION `0.9.7`, no tag, no
  release), the P3-A → P3-C2 progress summary, the P3 core-objective
  completion statement, the remaining not-started items (P3-C3
  optional, P3-D, P3-E), the two recommended next-window paths
  (continue with P3-C3 vs skip to P3-D/P3-E), and explicit
  prohibitions for the next window (no `structural_risk` runtime
  trigger, no `escalate=true` / `user_requested` MCP parameter, no
  `call_ledger.py` / `call_ledger_cli.py` edits, no VERSION bump, no
  tag, no release). No runtime / test / `VERSION` changes; no
  `tools/**` / `tests/**` / `CLAUDE.md` / `docs/mcp-task-policy.md` /
  `docs/MCP_COST_DISCIPLINE_PLAN.md` edits.
- MCP Cost Discipline P3-C2: second (and final core) behavioral flip in
  the auto-escalation chain. `_check_quality_escalation` in
  `tools/local_llm_mcp_server.py` now gates the `uncertain_points > 3`
  branch behind `_parse_env_flag(_ENV_AUTO_ESCALATE_ON_UNCERTAIN,
  default=False)`. Default behavior: a worker payload with
  `len(uncertain_points) > 3` alone no longer auto-escalates. Legacy
  behavior is restorable by setting
  `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN=true` (truthy values: `1`,
  `yes`, `on`, case-insensitive). Together with P3-C1's
  `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE` gate, this completes the
  P3 core objective: neither quality signal auto-triggers a
  strong-model invocation by default. `_derive_escalation_trigger`
  gated in lock-step on the uncertain branch — when both knobs are OFF
  and a payload carries both `confidence=="low"` and
  `uncertain_points > 3`, the helper returns `"unknown"`, matching the
  fact that `_check_quality_escalation` returns `None` (no escalation
  fires). The `timeout` downgrade path remains unconditional and
  unchanged. Path A (`_resolve_starting_profile` content-pattern
  routing), Path B (volume-based auto-debate in `call_review_diff`),
  and Path D (hook-layer `classify_diff_risk` advisory) all unchanged.
  `tests/test_p3_env_knobs.py` expanded from 72 → 104 tests adding:
  the P3-C2 default-OFF parametrize (unset / falsy / empty /
  unrecognized → no escalation); the env-knob restore parametrize
  (truthy → legacy escalation, plus chain-tier assertion); a threshold
  guard (count of exactly 3 must not escalate even with knob ON); the
  full 4-cell dual-signal matrix using a `_set_knobs` helper; refreshed
  `_derive_escalation_trigger` per-knob coverage including empty
  payload across the 4 knob combinations; a 16-cell
  timeout-precedence matrix proving timeout wins regardless of either
  knob; and explicit P3-C1 regression guards proving P3-C2 did not
  re-enable low_confidence auto-escalation or break its env-knob
  restore. The existing autouse fixtures in
  `tests/test_mcp_escalation_ledger_env.py` and
  `tests/test_layer4_quality.py::TestQualityEscalation` (both set
  knobs to `"true"` at module/class scope, added in P3-C1) carry
  through unchanged. P2 ledger contract preserved: `escalation_trigger`
  value space unchanged (`timeout` / `low_confidence` /
  `uncertain_points` / `unknown`), only the *frequency* of
  `low_confidence` and `uncertain_points` labels changes; ledger schema
  / CLI subcommand surface untouched. No `tools/call_ledger.py` /
  `tools/call_ledger_cli.py` / `tools/local_llm_profiles.json` /
  `CLAUDE.md` / `docs/mcp-task-policy.md` /
  `docs/MCP_COST_DISCIPLINE_PLAN.md` / `VERSION` / tag changes.
- MCP Cost Discipline P3-C1: first behavioral flip in the
  auto-escalation chain. `_check_quality_escalation` in
  `tools/local_llm_mcp_server.py` now gates the `confidence=="low"`
  branch behind `_parse_env_flag(_ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE,
  default=False)`. Default behavior: a worker payload with
  `confidence=="low"` alone no longer auto-escalates. Legacy behavior is
  restorable by setting `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE=true`
  (or any truthy value: `1`, `yes`, `on`, case-insensitive). When the
  knob is OFF and a payload carries both `confidence=="low"` and
  `len(uncertain_points) > 3`, escalation still fires via the uncertain
  branch (which P3-C2 will gate). `_derive_escalation_trigger` updated
  in lock-step so the ledger `escalation_trigger` label matches the
  branch that actually fires — `"low_confidence"` now appears only when
  the knob is ON; otherwise the helper falls through to
  `"uncertain_points"` / `"unknown"`. `_check_quality_escalation`
  `uncertain_points > 3` and `timeout` branches unchanged; Path A
  (starting-profile routing), Path B (volume-based auto-debate), and
  Path D (mcp_gate advisory) unchanged. `tests/test_p3_env_knobs.py`
  expanded from 49 → 72 tests covering: default-OFF for low_confidence,
  env-knob restore on truthy values, falsy/empty/unrecognized → OFF,
  dual-signal fallthrough to uncertain, `_derive_escalation_trigger`
  behavior across knob states, timeout precedence unchanged, and three
  untouched-path guards. `tests/test_mcp_escalation_ledger_env.py` and
  `tests/test_layer4_quality.py::TestQualityEscalation` gained autouse
  fixtures that set both env knobs to `true` so their existing
  escalation-plumbing assertions continue to exercise the legacy path.
  No `tools/call_ledger.py` / `tools/call_ledger_cli.py` /
  `tools/local_llm_profiles.json` / `CLAUDE.md` /
  `docs/mcp-task-policy.md` / `VERSION` / tag changes.
- MCP Cost Discipline P3-B: env knob helper + constants in
  `tools/local_llm_mcp_server.py`. Adds `_ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE`
  and `_ENV_AUTO_ESCALATE_ON_UNCERTAIN` literal env-var names, plus
  `_parse_env_flag(name, default=False)` boolean parser (truthy: `true`
  / `1` / `yes` / `on`; falsy: `false` / `0` / `no` / `off` / empty;
  unrecognized → default; case-insensitive, whitespace-trimmed).
  **Plumbing only — helpers exist but are NOT wired into
  `_check_quality_escalation`.** Pre-P3 escalation behavior preserved
  unchanged at this commit: `confidence=="low"` and
  `len(uncertain_points) > 3` continue to auto-escalate regardless of
  either knob's value. Adds `tests/test_p3_env_knobs.py` (49 tests):
  constant-name spec lock, parser semantics across unset/truthy/falsy/
  empty/unrecognized/case/whitespace variants, plus three runtime-
  invariance smoke tests that fail if the wiring leaks into P3-B. P3-C1
  / P3-C2 will perform the behavioral flip (default OFF, env-knob
  restorable). No `tools/call_ledger.py` / `tools/call_ledger_cli.py` /
  `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes.
- MCP Cost Discipline P3-A.1: docs/spec reconciliation only. Rewrites
  `docs/MCP_COST_DISCIPLINE_PLAN.md` §1.1, §4 (split into §4.1 current
  runtime behavior, §4.2 P3 target, §4.3 other escalation surfaces
  Paths A/B/C/D, §4.4 why no strict `escalation_reason` enum, §4.5 max
  passes), §10 P3 row, and §13.5 P3 follow-up to match the runtime at
  HEAD `e8a5315`. Earlier drafts referenced `confidence=medium` and
  `uncertain_points ≥ 3` as the triggers; the runtime actually keys on
  `confidence=="low"` and `uncertain_points > 3`. The proposed
  `escalation_reason` enum (`test-failure | dirty-after-review |
  structural-risk | reviewer-disagreement | user-requested`) was never
  implemented and is withdrawn. P3 scope narrowed to env-knob-restorable
  default-OFF for `low_confidence` / `uncertain_points` plus an optional
  `review_necessity="user-forced"` ledger stamp; `structural_risk`
  runtime trigger and new `escalate=` MCP parameter both deferred outside
  P3. `PROJECT_STATUS.md` adds P3-A / P3-A.1 rows and the P3-B → P3-E
  sub-phase split. Also fixes the stale P2-E row from `Done (this
  commit)` to `Done (e8a5315)`. No runtime / test / VERSION / tag
  changes.
- MCP Cost Discipline P2-E: docs closeout for P2-A → P2-D1. Records the
  completed cost-discipline ledger chain in `PROJECT_STATUS.md`, adds the
  `docs/MCP_COST_DISCIPLINE_PLAN.md` §13 P2 completion notes (phase commit
  table, final state of the ledger schema and call sites, review policy
  actually used, acceptance evidence), and adds a "Call ledger reporting"
  section to `README.md` listing the `call_ledger_cli.py` subcommands. No
  code, tests, profiles JSON, or VERSION changes. No tag.
- MCP Cost Discipline P2-D1: call ledger CLI adds `by-profile`,
  `by-mcp-tool`, `escalations`, and `debates` reporting commands over
  P2 cost-discipline fields. Includes `group_by_extra`,
  `filter_escalations`, and `filter_debates` library helpers with
  old-record compatibility (missing extra/profile → `<none>` bucket).
- MCP Cost Discipline P2-C3.1: debate rounds now emit one call ledger
  record per `run_round()` with debate metadata (`debate_mode`,
  `debate_rounds`, `debate_round_index`, `debate_trigger`) while
  preserving debate stdout/output JSON format. Captures real provider
  usage from `ModelCallResult` instead of dropping it.
  `call_debate_review_diff` MCP handler now passes `--debate-trigger
  manual-mcp`; `call_review_diff` auto-escalation to debate passes
  `--debate-trigger auto-escalate`. No worker / router / hook changes.
- MCP Cost Discipline P2-C2.1: `_wrap_worker_call` now stamps escalated
  child worker calls with escalation context in `LOCAL_LLM_LEDGER_EXTRA`,
  preserving MCP tool/source/commit_gate identity and linking child
  ledger records to the parent request via `parent_request_id`. Adds
  `_derive_escalation_trigger` and `_merge_escalation_ledger_extra_env`
  helpers. No worker / router / debate / hook behavior changes.
- MCP Cost Discipline P2-C2.0: add `escalation_trigger` to call ledger
  known extra keys, preparing escalation context ledger capture. No
  worker / MCP server / router / debate / hook behavior changes.
- MCP Cost Discipline P2-C1.2: auto hook replaces broken CLI
  `--commit_gate true` passthrough with `LOCAL_LLM_LEDGER_EXTRA` env
  stamping. `tools/claude_hooks/mcp_auto_worker.py` ships a
  self-contained `_build_ledger_extra_env` helper (decoupled from the
  MCP server) and `spawn_review_diff` now drops the dead CLI flag and
  stamps the subprocess env with
  `{mcp_tool_name=local_review_diff, commit_gate=true, source=auto-hook}`.
  No worker / MCP server / router / debate changes; fire-and-forget
  behaviour preserved.
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
