# Local LLM Pipeline

Portable local LLM development infrastructure for Claude Code and Codex.
Provides source-non-mutating multi-model code review, test planning, and risk analysis
via CLI and MCP (Model Context Protocol).

## Quick Start

```powershell
# Install into a project
python install_local_llm_pipeline.py C:\path\to\your-project

# Add MCP server
cd C:\path\to\your-project
claude mcp add --transport stdio --scope project local-llm -- python tools/local_llm_mcp_server.py

# Verify
python tools/local_llm_check.py
python tools/local_llm_router.py summarize-file README.md
```

## Docs

- [Installation Guide](docs/local-llm-installation.md)
- [Architecture Overview](docs/architecture-overview.md)
- [Roadmap](docs/roadmap.md)
- [MCP Server](docs/local-llm-mcp.md)
- [MCP Usage Patterns](docs/local-llm-mcp-usage-patterns.md)
- [MCP Client Verification](docs/local-llm-mcp-client-verification.md)
- [Debate Multi-Model Review](docs/local-llm-debate.md)
- [MCP Hook Gate](docs/claude-code-mcp-gate.md)
- [Hook Doctor](docs/mcp-phase2d-hook-doctor.md)
- [Cross-Project Setup](docs/mcp-cross-project-setup.md)
- [Release Checklist](docs/release-checklist.md)
- [Changelog](CHANGELOG.md)

## MCP Hook Infrastructure

The pipeline includes a multi-layer PreToolUse guard system:

```text
dangerous guard → release guard → commit gate
```

- **Dangerous guard**: blocks destructive commands (rm -rf, git reset --hard, del /s /q)
- **Release guard**: blocks external publication (git push, git tag, npm publish, twine upload)
- **Commit gate**: requires prior MCP review before git commit

Diagnose hook health at any time:

```bash
python tools/claude_hooks/mcp_doctor.py
```

Phase 3E.1 hardening ensures real-time participation detection works with
real tool response formats and cross-platform path handling.

### MCP Completion Status

**Goal complete.** The system provides default participation, review enforcement, safety blocking, risk routing, diagnostics, and cross-project readiness. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for full capability matrix and freeze status.

Verify before starting work on any project:

```bash
python tools/claude_hooks/mcp_doctor.py
python -m pytest tests/ -q
```

To use MCP hooks with another repo (e.g. local-translator-agent):

```bash
python tools/claude_hooks/mcp_doctor.py --repo-root /path/to/other/repo
```

See [Cross-Project Setup](docs/mcp-cross-project-setup.md) for details.

## Call Ledger Reporting

The pipeline records every local model call to a JSONL ledger
(`tools/call_ledger.py`). Each record carries a top-level `profile` and an
`extra` dict that captures cost-discipline context (`mcp_tool_name`,
`source`, `commit_gate`, escalation fields, debate round fields).

Inspect the ledger via `tools/call_ledger_cli.py`:

| Command | Output |
|---------|--------|
| `summary` | Aggregate totals (calls, tokens, duration, cost). |
| `by-project` | Totals grouped by project. |
| `by-task` | Totals grouped by `task_type`. |
| `by-profile` | Totals grouped by profile (old records → `<none>`). |
| `by-mcp-tool` | Totals grouped by `extra.mcp_tool_name`, with fallback to top-level `tool_name` for pre-P2 records. |
| `failures` | List of failed calls. |
| `recent [--limit N]` | Most recent N records (default 20). |
| `escalations [--limit N]` | Records carrying escalation context (`auto_escalated=true` or any `escalation_*` / `parent_request_id` field). |
| `debates [--limit N]` | Per-round debate records (`extra.debate_mode=true`), one ledger row per `run_round()`. |

All subcommands support `--format json` for machine-readable output and
`--path <ledger.jsonl>` to point at an alternate ledger location. Pre-P2
records that lack the `extra` dict still aggregate correctly — they fall
into the `<none>` bucket (or the `tool_name` fallback for `by-mcp-tool`).

See `docs/MCP_COST_DISCIPLINE_PLAN.md` for the cost-discipline policy
backing these fields, and `PROJECT_STATUS.md` for the P2 phase chain.

## Security

All local model output is advisory only. MCP tools are source-non-mutating:
they never modify source files directly. `local_draft_code` writes drafts only
to `.local_llm_out/` and requires controller verification before any source change.
No write/delete/shell/git/deploy capabilities. Controller must verify
all important claims. See [AGENTS.md](AGENTS.md) for full policy.

## Windows Command Examples

On Windows, use `py -3` to invoke the correct Python interpreter.

```bash
# Run test suites
py -3 -m pytest tests/test_validate_configs.py -q
py -3 -m pytest tests/test_cost_ledger.py -q

# Validate configuration
py -3 tools/validate_configs.py
py -3 tools/validate_configs.py --json

# Cost ledger (records usage/cost metadata only)
py -3 tools/cost_ledger.py --summary
py -3 tools/cost_ledger.py --budget 200 --summary
```

Cost ledger records usage and cost metadata only. It must not store API keys,
raw prompt text, or reasoning output. Historical records are not rewritten.
Ledger files live under `.local_llm_out/cost_ledger/`.

```bash

# Environment health check
py -3 tools/local_llm_check.py

# Commit workflow
py -3 tools/precommit_advisory.py --cloud-ok
py -3 tools/claude_soft_gate.py --stage pre-task --task "<task>" --json
```
