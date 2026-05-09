# Local LLM MCP Server — Design Draft

## Purpose

Wrap the existing CLI pipeline (`local_llm_router.py`, `local_llm_debate.py`, `local_llm_check.py`) as MCP (Model Context Protocol) tools so Claude Code / Codex can invoke them natively without shelling out.

## Architecture

```
Claude Code / Codex
    ↓ MCP JSON-RPC (stdio)
local_llm_mcp_server.py
    ↓ subprocess
Existing CLI tools (router, debate, check)
    ↓ Ollama API
Local models
```

## MCP Protocol

- Transport: stdio (JSON-RPC 2.0)
- Methods: `initialize`, `tools/list`, `tools/call`
- Each tool call spawns a subprocess to the existing CLI
- Timeout per tool call: configurable, default 600s

## Tools Exposed (v0.3.0)

### 1. local_check
- **No params required**
- Calls `python tools/local_llm_check.py`
- Returns health status summary (Ollama connectivity, model availability, profiles)
- No LLM call needed

### 2. local_summarize_file
- **Params**: `path` (required), `profile` (optional), `model` (optional), `max_chars` (optional)
- Calls `python tools/local_llm_router.py summarize-file <path>`
- Returns the latest JSON summary from `.local_llm_out/`

### 3. local_summarize_tree
- **Params**: `path` (required), `max_files` (optional, default 20), `profile` (optional), `model` (optional), `max_chars` (optional)
- Calls `python tools/local_llm_router.py summarize-tree <path> --max-files <N>`
- Returns JSON directory summary

### 4. local_generate_test_plan
- **Params**: `path` (required), `profile` (optional), `model` (optional)
- Calls `python tools/local_llm_router.py generate-test-plan <path>`
- Returns JSON test plan

### 5. local_review_diff
- **Params**: `diff_text` (required), `profile` (optional), `model` (optional)
- Passes `diff_text` via stdin to `python tools/local_llm_router.py review-diff --stdin`
- Returns JSON review

### 6. local_debate_review_diff
- **Params**: `diff_text` (required), `fast` (optional, default true), `summary_only` (optional, default true), `max_chars` (optional)
- Passes `diff_text` via stdin to `python tools/local_llm_debate.py review-diff --stdin`
- Defaults: `--fast --summary-only`
- Returns debate JSON

## Tools NOT Exposed (Hard Boundary)

- **NO** `local_write_file` / `local_delete_file` — no filesystem mutation
- **NO** `local_run_shell` — no arbitrary command execution
- **NO** `local_git_commit` / `local_git_push` / `local_git_tag` — no git mutation
- **NO** `local_deploy` — no deployment
- **NO** `local_edit_code` — no source modification
- **NO** `local_read_secrets` — blocked paths enforced

## Security Model

1. **Path validation**: All file paths checked via `is_blocked_path()` from worker
2. **Subprocess only**: MCP server only calls project-internal scripts, never arbitrary commands
3. **Timeout**: Every subprocess call has a configurable timeout (default 600s)
4. **Input size cap**: `diff_text` limited to 100K chars; `max_chars` capped at 200K
5. **Output isolation**: All LLM output goes to `.local_llm_out/`, never to source files
6. **Structured errors**: Errors return JSON with `ok: false` and `error` field, never crash
7. **No network egress** beyond Ollama API (localhost)

## Parameter Constraints

| Parameter | Type | Default | Max |
|---|---|---|---|
| `diff_text` | string | — | 100,000 chars |
| `path` | string | — | must exist, must not be blocked |
| `max_files` | int | 20 | 50 |
| `max_chars` | int | profile default or 60K | 200,000 |
| `timeout` (internal) | int | 600s | 900s |

## Output Format

All tools return JSON with a consistent envelope:
```json
{
  "ok": true/false,
  "tool": "<tool_name>",
  "result": { ... tool-specific output ... },
  "error": null or "<message>",
  "elapsed_seconds": N,
  "created_at": "<ISO8601>"
}
```

## Dependencies

- Python 3.10+
- `requests` (already required by worker)
- No additional Python packages needed (stdlib JSON-RPC)

## Integration Points

- `.codex/config.toml`: add `[mcp_servers.local-llm]` section
- `.claude/commands/local-mcp.md`: usage guide for Claude Code users
- `install_local_llm_pipeline.py`: copy MCP server + docs to target projects
- `run_checks.py`: verify MCP server file exists, verify no dangerous tool names
