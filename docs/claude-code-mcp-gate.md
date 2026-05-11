# Claude Code MCP Commit Gate

Post-v0.9.5 commit gate with repo-scoped state. Prevents `git commit` without
prior local model review, and prevents cross-repo review leakage.

## Architecture

```
git commit
  → Claude Code PreToolUse hook (mcp_gate.py)
  → detects real git commit command
  → checks repo-scoped state (repo / HEAD / diff_hash)
  → blocked if unreviewed or mismatch
    → prompts: local_review_diff with commit_gate=true
  → allowed if matching review state
    → git proceeds
```

## File locations

| File | Location |
|------|----------|
| Hook script | `C:\Users\Zero\.claude\hooks\mcp_gate.py` |
| Hook config | `C:\Users\Zero\.claude\settings.json` (PreToolUse, PostToolUse) |
| State file | `%LOCALAPPDATA%\mcp-gate\state.json` |
| Audit log | `%LOCALAPPDATA%\mcp-gate\hook-events.jsonl` |

The hook is a **user-level Claude Code hook**, not part of this repository.

The MCP fast-path code lives in this repo at `tools/local_llm_mcp_server.py`.

## State file fields

```json
{
  "diff_reviewed": false,
  "dirty_since_review": false,
  "reviewed_at": null,
  "reviewed_by": null,
  "reviewed_repo": null,
  "reviewed_head": null,
  "reviewed_diff_hash": null
}
```

- **diff_reviewed**: `true` after a review tool completes successfully.
- **dirty_since_review**: `true` if Edit/Write/MultiEdit ran after the last review.
- **reviewed_repo**: `git rev-parse --show-toplevel` at review time.
- **reviewed_head**: `git rev-parse HEAD` at review time.
- **reviewed_diff_hash**: SHA256 of `git diff --cached` (falls back to `git diff`).
- **reviewed_at / reviewed_by**: ISO timestamp and tool name of last review.

State is loaded with defaults merged, so old state files (missing new fields) work
without migration.

## Capabilities

### Command detection

The hook parses Git commands with token-level accuracy:

**Detected as git commit:**
- `git commit -m "x"`
- `git commit --dry-run -m "x"`
- `git -C <repo> commit -m "x"`
- `git -C "<repo with spaces>" commit -m "x"`
- `git -c user.name=test commit -m "x"`
- `git --no-pager commit -m "x"`
- `cd <repo> && git commit -m "x"`
- `cd <repo>; git commit -m "x"`
- Bash and PowerShell variants

**Not detected (correctly ignored):**
- `git status`, `git diff`, `git log`, `git branch`
- `git commit-tree` (plumbing, excluded)
- `echo "git commit -m test"` (quoted string, not a command)
- `printf "git commit"`

### Review matching

Commit is allowed only when ALL of these match:
1. `diff_reviewed` = `true`
2. `dirty_since_review` = `false`
3. `reviewed_repo` = current repo root
4. `reviewed_head` = current HEAD
5. `reviewed_diff_hash` = SHA256 of current staged diff

If any condition fails, the commit is blocked with a specific reason:
- "files modified after review"
- "review was for X, current is Y" (cross-repo)
- "HEAD has changed since review"
- "staged diff has changed since review"

## Normal commit workflow

```bash
git add <files>
git diff --cached                           # verify what will be committed
# Call via Claude Code MCP tool:
# mcp__local-llm__local_review_diff with commit_gate=true
git commit -m "message"
```

## MCP fast path

`local_review_diff` with `commit_gate=true`:
- Uses `commit_reviewer` profile (qwen3-coder:30b)
- 60-second timeout
- Single-model review (skips multi-model debate)
- Returns in ~10-60 seconds

The `commit_gate=true` flag skips the automatic debate escalation that would
normally trigger for large diffs (>100 lines, 3+ files, or logic changes).

For deep review, call `local_debate_review_diff` explicitly.

## Important notes

1. **MCP server restart**: After modifying `tools/local_llm_mcp_server.py`,
   restart Claude Code for the MCP server to pick up changes.

2. **commit_gate=true is for commit gate only**. The debate path
   (`local_debate_review_diff`) is still available for deep review.

3. **State is per-user, not per-repo**. The state file lives in
   `%LOCALAPPDATA%\mcp-gate\` and is shared across all repos for the same
   Windows user. Repo-scoping prevents cross-repo leakage, but be aware
   the state file is not in any git repository.

4. **Hook is user-level config**. Modifications to `mcp_gate.py` or
   `settings.json` are not tracked in the local-llm-pipeline repo.
