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

Phase 2C.1 hardening ensures PowerShell here-string commit messages are not falsely blocked.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for current freeze readiness.

## Security

All local model output is advisory only. MCP tools are source-non-mutating:
they never modify source files directly. `local_draft_code` writes drafts only
to `.local_llm_out/` and requires controller verification before any source change.
No write/delete/shell/git/deploy capabilities. Controller must verify
all important claims. See [AGENTS.md](AGENTS.md) for full policy.
