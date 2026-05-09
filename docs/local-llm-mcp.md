# Local LLM MCP Server

## What is MCP?

MCP (Model Context Protocol) lets Claude Code / Codex call tools directly without shelling out to a subprocess. The controller sends a JSON-RPC request over stdio, and the MCP server responds with structured output.

## Why MCP for this project?

Before v0.3.0, the local LLM pipeline was CLI-only:

```
Claude Code / Codex
  -> Bash -> python tools/local_llm_router.py ...
```

After v0.3.0:

```
Claude Code / Codex
  -> MCP tool call -> local_summarize_file(path="src/main.py")
```

MCP integration means:
- No shell parsing overhead
- Structured input/output guarantees
- Error handling at protocol level
- Consistent parameter validation
- Path blocking enforced at MCP boundary

## Tools Exposed (v0.3.0)

All tools are **read-only**. None can modify files, run arbitrary commands, or perform git operations.

| Tool | Description | Key Parameters |
|---|---|---|
| `local_check` | Environment health check | (none) |
| `local_summarize_file` | Summarize a file | `path` (required), `profile`, `model`, `max_chars` |
| `local_summarize_tree` | Summarize a directory tree | `path` (required), `max_files`, `profile`, `model`, `max_chars` |
| `local_generate_test_plan` | Generate test plan for a file | `path` (required), `profile`, `model` |
| `local_review_diff` | Single-model diff review | `diff_text` (required), `profile`, `model` |
| `local_debate_review_diff` | Multi-model debate review | `diff_text` (required), `fast` (default: true), `summary_only` (default: true) |

### Tool Details

#### local_check

No parameters. Returns Ollama connectivity, available models, and recommended profile assignments.

#### local_summarize_file

```
path:         Path to the file (must exist, must not be blocked)
profile:      Optional profile override (e.g. fast_summary, code_worker)
model:        Optional model override
max_chars:    Max input chars (max: 200K)
```

#### local_summarize_tree

```
path:         Path to the directory (must exist, must not be blocked)
max_files:    Max files to read (default: 20, max: 50)
profile:      Optional profile override
model:        Optional model override
max_chars:    Max input chars (max: 200K)
```

#### local_generate_test_plan

```
path:         Path to the source file (must exist, must not be blocked)
profile:      Optional profile override
model:        Optional model override
```

#### local_review_diff

```
diff_text:    The diff text to review (max: 100K chars)
profile:      Optional profile override
model:        Optional model override
```

#### local_debate_review_diff

```
diff_text:     The diff text to review (max: 100K chars)
fast:          Use 2-round fast mode (default: true)
summary_only:  Return only findings summary (default: true)
max_chars:     Max input chars (max: 200K)
```

**Defaults are chosen for MCP**: `--fast --summary-only` keeps output compact and fast. For large/risky diffs, set `fast: false` to run full 3-round debate.

## Claude Code Configuration

Use `claude mcp add` (recommended):

```bash
cd <project-root>
claude mcp add --transport stdio --scope project local-llm -- python tools/local_llm_mcp_server.py
```

This creates `.mcp.json` at the project root (can be committed to share with the team).

Verify with `/mcp` inside Claude Code — you should see `local-llm` with 6 tools.

Manual alternative (add to `.mcp.json`):

```json
{
  "mcpServers": {
    "local-llm": {
      "type": "stdio",
      "command": "python",
      "args": ["tools/local_llm_mcp_server.py"]
    }
  }
}
```

## Codex Configuration

Add to `.codex/config.toml`:

```toml
[mcp_servers.local-llm]
command = "python"
args = ["tools/local_llm_mcp_server.py"]
cwd = "."
startup_timeout_sec = 10
tool_timeout_sec = 300
```

Then verify with `/mcp` inside Codex — you should see `local-llm` active.

## MCP vs CLI

See **[MCP Usage Patterns](local-llm-mcp-usage-patterns.md)** for the full decision matrix.

Summary:

| Use MCP for | Use CLI for |
|---|---|
| Quick health check | Debugging |
| Summarize a file during coding | Large directory summaries |
| Small diff review | Large diffs (>500 lines) |
| Small diff debate | Full 3-round debate |
| Generate test plan | Benchmarking |
| Interactive use | CI/CD, batch processing |

## Remote Ollama

If Ollama runs on another machine, set before starting:

```bash
export LOCAL_LLM_BASE_URL=http://<host>:11434
# or
export OLLAMA_HOST=<host>:11434
```

Resolution: `LOCAL_LLM_BASE_URL` → `OLLAMA_HOST` → `http://localhost:11434`.

## Client Verification

See **[MCP Client Verification Guide](local-llm-mcp-client-verification.md)** for step-by-step instructions for Claude Code and Codex.

## Security Boundaries

### What MCP does NOT expose

- **NO file writing** — no `write_file`, `delete_file`, `create_file`
- **NO arbitrary shell** — no `run_shell`, `exec`, `command`
- **NO git mutation** — no `git_commit`, `git_push`, `git_tag`
- **NO deployment** — no `deploy`, `release`
- **NO secret reading** — blocked paths enforced (`.env`, `.pem`, `.git/config`, etc.)
- **NO source modification** — all tools are read-only analysis

### What MCP DOES enforce

- **Path validation**: All `path` parameters checked via `is_blocked_path()`
- **Symlink resolution**: Paths are resolved to prevent bypass attacks
- **Input size caps**: `diff_text` max 100K, `max_chars` max 200K, `max_files` max 50
- **Subprocess timeout**: Every tool call has a configurable timeout (default 600s)
- **Output truncation**: Large outputs are truncated to keep MCP responses manageable
- **Structured errors**: Errors return `{ok: false, error: "message"}` — never crash

### Why these boundaries exist

Local models are advisory only. They cannot:
- Run tests to verify claims
- Read files outside the input provided
- Have full project context

The MCP server therefore restricts local models to analysis tasks. The controller (Claude Code / Codex) must verify all important claims.

## When to Use CLI vs MCP

| Scenario | Use |
|---|---|
| Day-to-day diff review | MCP `local_review_diff` or `local_debate_review_diff` |
| Large/risky diff review | MCP `local_debate_review_diff` with `fast: false` |
| Summarizing unfamiliar code | MCP `local_summarize_tree` or `local_summarize_file` |
| Generating test coverage ideas | MCP `local_generate_test_plan` |
| Checking environment | MCP `local_check` or CLI `python tools/local_llm_check.py` |
| Debugging MCP issues | CLI tools directly (better error messages) |
| First-time setup | CLI (`install_local_llm_pipeline.py`) |

## Troubleshooting

### MCP server won't start

```bash
# Check Python and dependencies
python tools/run_checks.py

# Test the server directly (will block on stdin — Ctrl+C to exit)
python tools/local_llm_mcp_server.py
```

### Tools return errors

Check that:
1. Ollama is running: `ollama list`
2. Profiles exist: `python tools/local_llm_check.py`
3. The file path exists and is not blocked
4. Input size is within limits

### MCP output is too large

- Use `local_debate_review_diff` with default `summary_only: true`
- Reduce `max_chars` or `max_files`
- Use `local_review_diff` (single model) instead of debate for simple diffs

### Claude Code can't find the MCP server

Verify the path in settings is relative to the project root. Use absolute paths if needed:

```json
{
  "mcpServers": {
    "local-llm": {
      "command": "python",
      "args": ["C:\\path\\to\\project\\tools\\local_llm_mcp_server.py"],
      "cwd": "C:\\path\\to\\project"
    }
  }
}
```
