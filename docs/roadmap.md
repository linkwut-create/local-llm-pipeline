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

## Current Stable Boundaries

- 7 MCP tools, all source-non-mutating (local_draft_code writes only to .local_llm_out/)
- 3-round debate (fast mode default for MCP)
- 200+ tests, 13 run_checks categories
- Remote Ollama via LOCAL_LLM_BASE_URL / OLLAMA_HOST
- Installer with manifest and --update mode
- Windows PowerShell + Git Bash compatible

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

## Future Candidates (v0.6.0+)

### Profile Auto-Tuning (priority: high)

When new models are added to Ollama, automatically re-evaluate which model
best fits each profile based on benchmark results rather than keyword matching.

### MCP Output Compression (priority: high)

Further reduce MCP response sizes with smarter truncation, optional field
stripping, and structured summaries tailored for agent consumption.

### Batch Update Dry-Run (priority: medium)

Support checking update status across multiple installed projects at once,
without applying changes.

### Project Template Pack (priority: medium)

Package the pipeline as a project template that can be instantiated via
`cookiecutter` or similar, rather than only via the installer script.

### Debate Profile Customization (priority: low)

Allow users to specify which profiles/models participate in each debate round,
rather than using the hardcoded coder → reasoning → deep order.

### MCP Health Dashboard (priority: low)

A small web or CLI dashboard showing MCP tool call history, latency, and
error rates across sessions.

## Recommendation

The pipeline is now feature-complete for its stated purpose: providing
source-non-mutating, multi-model LLM assistance to Claude Code / Codex during
software development. The next phase should focus on **using it**
rather than extending it further.

If you choose to continue development, start with profile auto-tuning
(v0.6.0) — it has the highest impact-to-effort ratio of the candidates.
