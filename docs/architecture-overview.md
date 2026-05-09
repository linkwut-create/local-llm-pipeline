# Architecture Overview

## Component Map

```
┌─────────────────────────────────────────────────┐
│ Controller (Claude Code / Codex / DeepSeek)     │
│   - Reads MCP/CLI output                        │
│   - Makes final decisions                       │
│   - Verifies claims                             │
├───────────────┬─────────────────────────────────┤
│   MCP Server  │          CLI Tools              │
│   (stdio)     │          (subprocess)           │
├───────────────┴─────────────────────────────────┤
│              Router (local_llm_router.py)        │
│   - Task → profile mapping                      │
│   - Model availability check                    │
│   - Risk level annotation                       │
├───────────────┬─────────────────────────────────┤
│    Worker     │          Debate                 │
│ (single LLM)  │    (multi-model cross-review)   │
│               │    coder → reasoning → deep     │
├───────────────┴─────────────────────────────────┤
│              Backend                             │
│   Ollama (localhost or remote)                  │
│   OpenAI-compatible (llama.cpp etc.)            │
├─────────────────────────────────────────────────┤
│              Installer + Manifest                │
│   install_local_llm_pipeline.py                 │
│   .local_llm_pipeline.json                      │
└─────────────────────────────────────────────────┘
```

## Data Flow

```
User request (via Claude Code / Codex)
    │
    ├── MCP path ──→ local_llm_mcp_server.py ──→ subprocess ──→ router
    │
    └── CLI path ──→ local_llm_router.py
                          │
                    profile + model selection
                          │
                    ┌─────┴─────┐
                    │   worker   │  (single model)
                    │   debate   │  (multi-model)
                    └─────┬─────┘
                          │
                    Ollama API call
                          │
                    Structured JSON → .local_llm_out/
                          │
                    Controller review
                          │
                    Final decision (human + Claude Code / Codex)
```

## Components

### Controller (Claude Code / Codex / DeepSeek)

- Reads all local model output
- Decides which findings to act on
- Runs tests, reads source files
- Never delegates final approval to local models

### MCP Server (`tools/local_llm_mcp_server.py`)

- 6 read-only tools over stdio JSON-RPC
- Path validation, symlink resolution, output truncation
- Timeout per tool call
- No write/delete/shell/git/deploy

### CLI Router (`tools/local_llm_router.py`)

- Task routing: maps task names to profiles and models
- Model availability check
- stdin support for diff review

### Worker (`tools/local_llm_worker.py`)

- Single-model task execution
- Structured output (JSON + Markdown)
- Blocked path enforcement

### Debate (`tools/local_llm_debate.py`)

- Multi-model cross-review (up to 3 rounds)
- Fast mode (2 rounds, ~2 min) for daily use
- Full mode (3 rounds, ~4 min) for high-risk reviews
- MAX_FINDINGS caps to prevent output bloat
- --summary-only for compact output

### Installer (`install_local_llm_pipeline.py`)

- Copies tools/, docs/, .claude/, .codex/ to target project
- Appends policy to AGENTS.md / CLAUDE.md
- Appends .local_llm_out/ to .gitignore
- Writes .local_llm_pipeline.json manifest
- --update mode with SHA256 conflict detection
- Skips local config (settings.local.json) and sensitive files

### Manifest (`.local_llm_pipeline.json`)

- Records installed_version, managed_files, skipped_files, policy_markers
- Enables safe --update across versions
- Read by installer to identify legacy installs

### Backend

- Ollama: local or remote via LOCAL_LLM_BASE_URL / OLLAMA_HOST
- OpenAI-compatible: llama.cpp, vLLM, etc.

## Security Boundaries

### What local models CAN do

- Summarize files and directories
- Generate test plans
- Review diffs
- Run risk analysis
- Challenge each other's findings (debate)

### What local models CANNOT do

- Modify source code
- Read secrets (.env, keys, tokens)
- Run tests or claim test results
- Commit, push, tag, or deploy
- Decide whether a change is safe
- Approve security-critical findings

### What MCP CANNOT expose

- write_file / delete_file
- arbitrary_shell / exec
- git_commit / git_push / git_tag
- deploy / release

## MCP vs CLI

| Use MCP for | Use CLI for |
|---|---|
| Quick health check | Debugging |
| Summarize file/dir | Large directory summaries |
| Small diff review | Large diffs (>500 lines) |
| Small diff debate | Full 3-round debate |
| Generate test plan | Benchmarking |
| Interactive coding sessions | CI/CD, batch processing |

## File Map

| Path | Role |
|---|---|
| `tools/local_llm_worker.py` | Single-model task execution |
| `tools/local_llm_router.py` | Task routing and model selection |
| `tools/local_llm_check.py` | Environment health check |
| `tools/local_llm_debate.py` | Multi-model cross-review |
| `tools/local_llm_mcp_server.py` | MCP stdio server |
| `tools/local_llm_profiles.json` | Model profiles |
| `tools/local_llm_tasks.json` | Task definitions |
| `tools/run_checks.py` | Non-LLM stability checks |
| `install_local_llm_pipeline.py` | Project installer |
| `VERSION` | Centralized version number |
| `.local_llm_pipeline.json` | Install manifest (in target projects) |
| `docs/` | User and developer documentation |
