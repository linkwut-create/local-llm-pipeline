# Local LLM Global MCP Launcher

## Goal

The user-scope global MCP launcher (`tools/local_llm_global_mcp_launcher.py`)
lets you register the local-llm pipeline **once** with Claude Code and use it
across **all** git projects on your machine. No per-project `.mcp.json` needed.

## Registration

```bash
claude mcp add --transport stdio --scope user local-llm -- python C:\Users\Zero\local-llm-pipeline\tools\local_llm_global_mcp_launcher.py
```

This registers `local-llm` at the **user scope**. Whenever Claude Code starts in
any git project, the launcher detects that project and proxies all MCP tools
against it.

## How target_project is detected

The launcher walks upward from the current working directory until it finds a
`.git` folder. That directory becomes the `target_project`.

It sets two environment variables before delegating to the real MCP server:

| Variable | Value |
|---|---|
| `LOCAL_LLM_TARGET_PROJECT` | Absolute path to the target git project |
| `LOCAL_LLM_SOURCE_REPO` | Absolute path to the local-llm-pipeline install |

The MCP server's `_get_effective_project_root()` reads `LOCAL_LLM_TARGET_PROJECT`
to resolve all paths, subprocess cwd, and output directories against the
target project instead of the pipeline source repo.

## Output directory

All worker output goes to **`<target_project>/.local_llm_out/`**, never to the
pipeline install directory. The MCP server sets `LOCAL_LLM_OUTPUT_DIR` to
`<target_project>/.local_llm_out/` before spawning any subprocess.

## Non-git CWD handling

If Claude Code starts outside a git repository, the launcher returns a
structured error immediately:

```json
{
  "ok": false,
  "error_type": "no_git_repository",
  "error": "Not in a git repository. Navigate to a git project and restart Claude Code.",
  "suggestion": "cd to any git project and Claude Code will auto-connect the local-llm MCP server."
}
```

The MCP server does **not** crash. Claude Code will see the error and can
reconnect once you navigate to a git project.

## Priority vs project-scoped .mcp.json

If a project has its own `.mcp.json` that also registers a `local-llm` server
at **project scope**, the project-scoped entry takes priority for that project.
The user-scope global launcher serves as a fallback for projects that don't
have their own configuration.

To avoid double-registration:
- For projects that need a specific MCP configuration (custom profile, timeout),
  use project-scoped `.mcp.json`.
- For all other projects, the user-scope global launcher handles it automatically.

## Security boundaries

All 12 tools are **source-non-mutating**:

- They **never** modify source files directly.
- `local_draft_code` writes drafts only to `.local_llm_out/` and requires
  controller verification before any source change.
- No write/delete/shell/git/deploy capabilities.
- Path validation enforced: blocked paths (`.env`, `.env.*`, `*.key`, `*.pem`,
  `.git/`, `node_modules/`, `venv/`, `build/`, `dist/`) are rejected.
- Paths outside the target project are rejected unless
  `LOCAL_LLM_ALLOW_OUTSIDE_PROJECT=1` is set.

## Core delegation

The global launcher does **not** reimplement MCP tool handling. It sets up the
target project environment, then delegates to `local_llm_mcp_server` for:
- `handle_initialize` — protocol handshake
- `handle_tools_list` — tool schema enumeration
- `handle_tools_call` — tool execution with concurrency guard, error handling,
  structured logging, and prompt metadata propagation

Logging is tagged with `source: "global-mcp"` to distinguish from
project-scoped `source: "mcp"` entries.
