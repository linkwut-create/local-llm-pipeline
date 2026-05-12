# MCP Cross-Project Setup

How to use the MCP gate hook system in other git repositories.

## Architecture

The MCP gate has two parts:

1. **Repository module** — `tools/claude_hooks/mcp_gate.py` in the pipeline repo. Contains all hook logic, tests, and shared state. This is the source of truth.

2. **User wrapper** — `~/.claude/hooks/mcp_gate.py`. A thin script that inserts the pipeline repo into `sys.path` and calls `main()` from the repository module.

When a hook event fires, Claude Code executes the user wrapper, which imports the repository module, which reads/writes state and enforces gates.

## Setup for a New Project

### 1. Verify the pipeline repo exists

```bash
ls C:\Users\Zero\local-llm-pipeline\tools\claude_hooks\mcp_gate.py
```

### 2. Check the user wrapper

The wrapper at `~/.claude/hooks/mcp_gate.py` must point to the correct pipeline repo path:

```python
_REPO_ROOT = r"C:\Users\Zero\local-llm-pipeline"
sys.path.insert(0, _REPO_ROOT)
from tools.claude_hooks.mcp_gate import main
main(CONFIG_DIR)
```

### 3. Verify hook registration

In `~/.claude/settings.json`, all four events must be registered:

```json
{
  "hooks": {
    "SessionStart": [{"matcher": "", "command": "python ~/.claude/hooks/mcp_gate.py"}],
    "PreToolUse":   [{"matcher": "", "command": "python ~/.claude/hooks/mcp_gate.py"}],
    "PostToolUse":  [{"matcher": "", "command": "python ~/.claude/hooks/mcp_gate.py"}],
    "Stop":         [{"matcher": "", "command": "python ~/.claude/hooks/mcp_gate.py"}]
  }
}
```

### 4. Run the doctor

```bash
cd C:\path\to\your-project
python C:\Users\Zero\local-llm-pipeline\tools\claude_hooks\mcp_doctor.py --repo-root .
```

Or from within the pipeline repo:

```bash
python tools/claude_hooks/mcp_doctor.py --repo-root C:\path\to\your-project
```

### 5. Verify in your project

1. Open the project in Claude Code
2. Run `local_check` — should succeed
3. Make a small edit to a file
4. Run `local_review_diff` with `commit_gate=true`
5. Run `git commit -m "test"` — should be blocked without review
6. After review, the commit should be allowed

## For local-translator-agent Development

When development begins on `local-translator-agent`:

1. Verify the pipeline repo is at `C:\Users\Zero\local-llm-pipeline`
2. The same user wrapper and settings.json serve all projects — no per-project config needed
3. The commit gate uses per-project state (repo root, HEAD, diff hash) — it cannot confuse one project's review with another's
4. Run the doctor targeting the translator repo:
   ```
   python C:\Users\Zero\local-llm-pipeline\tools\claude_hooks\mcp_doctor.py --repo-root C:\Users\Zero\local-translator-agent
   ```
5. The MCP server (`.mcp.json`) is per-project — the translator project needs its own `.mcp.json`

## Windows / Git Bash / PowerShell Notes

- The hook wrapper uses Unix-style paths (`/c/Users/...`) in settings.json when using Git Bash Python
- The config dir is at `%LOCALAPPDATA%\mcp-gate\` — shared across all projects
- `mcp_doctor.py` uses `encoding="utf-8"` to avoid Windows GBK decode errors
- PowerShell here-string `@'...'@` in commit messages is handled (Phase 2C.1 fix)

## Why No Auto-Install

The doctor and setup docs are deliberately manual. The hook system:
- Writes to `~/.claude/settings.json` (user preferences)
- Manages state in `%LOCALAPPDATA%` (shared across projects)
- Requires Python with the pipeline repo on `sys.path`

Auto-installing would risk overwriting user configuration. The doctor diagnoses; the user decides.

## State Isolation

Even though the config dir is shared, commit gate state is repo-scoped:
- `reviewed_repo` — full path of the reviewed repo
- `reviewed_head` — commit hash at review time
- `reviewed_diff_hash` — SHA256 of the reviewed diff

A review from one project cannot satisfy the commit gate in another. Cross-repo review leakage is prevented by the fingerprint check in `handle_pre_tooluse()`.
