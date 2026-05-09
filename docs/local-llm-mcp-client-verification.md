# MCP Client Verification Guide

Step-by-step verification that the local LLM MCP server works with Claude Code and Codex.

## Prerequisites

- v0.3.2+ installed (`tools/local_llm_mcp_server.py` present)
- Ollama running (local or remote)
- Python 3.10+

## Claude Code

### 1. Add the MCP server

```bash
cd <project-root>
claude mcp add --transport stdio --scope project local-llm -- python tools/local_llm_mcp_server.py
```

This creates `.mcp.json` at the project root.

### 2. Verify connection

Restart Claude Code, then run:

```
/mcp
```

Expected: `local-llm` listed with 6 tools, status green.

### 3. Test each tool

Run these inside Claude Code:

```
Call local_check — should return Ollama connectivity and model list.
```

```
Call local_summarize_file with path=AGENTS.md — should return file summary.
```

```
Call local_summarize_tree with path=tools and max_files=10 — should return directory overview.
```

```
Call local_review_diff with empty diff_text — should return structured error "diff_text is empty".
```

```
Call local_debate_review_diff with a small diff — should complete in ~2 min, fast+summary_only by default.
```

### 4. Troubleshooting

| Symptom | Check |
|---|---|
| `local-llm` not in `/mcp` | Verify `.mcp.json` exists, restart Claude Code |
| `local_check` fails | `ollama list`, check `OLLAMA_HOST` env var |
| Tools hang | Check Ollama is running, check timeout settings |
| `ModuleNotFoundError` | Run from project root, verify `tools/` is present |

## Codex

### 1. Configure

Uncomment and adjust in `.codex/config.toml`:

```toml
[mcp_servers.local-llm]
command = "python"
args = ["tools/local_llm_mcp_server.py"]
cwd = "."
startup_timeout_sec = 10
tool_timeout_sec = 300
```

### 2. Verify

Restart Codex, then:

```
/mcp
```

Expected: `local-llm` active with 6 tools.

### 3. Test

Same as Claude Code — call `local_check` first, then `local_summarize_file`.

### 4. Troubleshooting

| Symptom | Check |
|---|---|
| Server won't start | Absolute path for `command` and `cwd` if relative fails |
| Timeout | Increase `startup_timeout_sec` or `tool_timeout_sec` |
| `local_check` unreachable | Verify Ollama URL via `LOCAL_LLM_BASE_URL` or `OLLAMA_HOST` |

## DeepSeek + Claude Code

When DeepSeek is configured as the Claude Code model provider, MCP works unchanged.
DeepSeek is the controller model; MCP tools are infrastructure. No special configuration needed.

## Remote Ollama

If Ollama runs on another machine, set before starting Claude Code / Codex:

```bash
# Option A: Full base URL
export LOCAL_LLM_BASE_URL=http://192.168.1.100:11434

# Option B: Host and port
export OLLAMA_HOST=192.168.1.100:11434
```

On Windows (PowerShell):
```powershell
$env:LOCAL_LLM_BASE_URL = "http://192.168.1.100:11434"
$env:OLLAMA_HOST = "192.168.1.100:11434"
```

Resolution order: `LOCAL_LLM_BASE_URL` → `OLLAMA_HOST` → `http://localhost:11434`.
