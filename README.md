# Local LLM Pipeline

Portable local LLM development infrastructure for Claude Code and Codex.
Provides read-only multi-model code review, test planning, and risk analysis
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
- [Release Checklist](docs/release-checklist.md)
- [Changelog](CHANGELOG.md)

## Security

All local model output is advisory only. MCP tools are read-only.
No write/delete/shell/git/deploy capabilities. Controller must verify
all important claims. See [AGENTS.md](AGENTS.md) for full policy.
