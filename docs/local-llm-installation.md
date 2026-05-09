# Local LLM Pipeline Installation Guide

## Quick Install

```powershell
python C:\Users\Zero\local-llm-pipeline\install_local_llm_pipeline.py C:\path\to\your-project
```

## Preview First (Dry Run)

```powershell
python C:\Users\Zero\local-llm-pipeline\install_local_llm_pipeline.py C:\path\to\your-project --dry-run
```

## What Gets Installed

| Directory/File | Contents |
|---|---|
| `tools/` | local_llm_worker.py, local_llm_router.py, local_llm_check.py, profiles/tasks JSON, maintenance tools |
| `docs/` | Worker, routing, risk policy, and installation documentation |
| `.claude/agents/` | local-worker-auditor subagent |
| `.claude/commands/` | 6 slash commands (local-check, local-worker, local-route, local-review-diff, local-risk, local-test-plan) |
| `.codex/` | config.toml + local-llm-worker.md |
| `AGENTS.md` | Local Worker Policy section (appended if file exists) |
| `CLAUDE.md` | Local Worker Policy section (appended if file exists) |
| `.gitignore` | `.local_llm_out/` entry (appended if file exists) |

## Options

| Flag | Effect |
|---|---|
| `--dry-run` | Show what would be done without making changes |
| `--force` | Overwrite existing files in tools/ and docs/ |
| `--skip-claude` | Don't install .claude/ directory |
| `--skip-codex` | Don't install .codex/ directory |
| `--skip-health-check` | Don't run post-install health check |

## Behavior with Existing Files

- **AGENTS.md / CLAUDE.md**: If the file exists and already contains `## Local Multi-Model Worker Policy`, it is skipped. Otherwise the policy section is appended.
- **tools/ / docs/**: Files are copied. Existing files are skipped unless `--force` is used.
- **.gitignore**: `.local_llm_out/` is appended if not already present.
- **Business code**: Never touched.

## What Does NOT Get Installed

The installer skips these files to avoid leaking local settings:

| Skipped file | Reason |
|---|---|
| `.claude/settings.local.json` | Machine-specific MCP enablement |
| `.claude/settings.json` | Machine-specific Claude Code settings |

These are filtered by `SKIP_FILES` in the installer.

## Real Migration Example (v0.4.0)

Installed into `C:\Users\Zero\local-translator-agent` (Python translation tool):

```powershell
# 1. Preview
python install_local_llm_pipeline.py C:\Users\Zero\local-translator-agent --dry-run
# Output: 36 files would be written, 1 skipped (settings.local.json)

# 2. Install
python install_local_llm_pipeline.py C:\Users\Zero\local-translator-agent
# Output: Health check PASSED (58 models via OLLAMA_HOST)

# 3. Verify
cd C:\Users\Zero\local-translator-agent
python tools/local_llm_check.py
python tools/local_llm_router.py summarize-file README.md

# 4. MCP setup
claude mcp add --transport stdio --scope project local-llm -- python tools/local_llm_mcp_server.py
claude
# In Claude Code: /mcp, local_check, local_summarize_file README.md

# 5. Commit the tooling
git add .gitignore .codex/ .mcp.json AGENTS.md CLAUDE.md docs/ tools/
git commit -m "Add local LLM development tooling"
```

### Rolling Back

If this was only a test installation, roll back with:

```powershell
git restore .gitignore          # revert .gitignore changes
git clean -fd                   # remove untracked directories (tools/, docs/, .codex/, .claude/)
# then remove newly created files if any:
rm -r -fo tools docs .codex .claude AGENTS.md CLAUDE.md .mcp.json .local_llm_out
```

## Post-Install Verification

The installer runs `python tools/local_llm_check.py` automatically after installation.

Manual verification:

```powershell
cd C:\path\to\your-project
python tools/local_llm_check.py
python tools/local_llm_router.py summarize-file README.md
```

## Maintenance Tools

### Update Profiles from Ollama

When you add or remove Ollama models:

```powershell
python tools/update_profiles_from_ollama.py           # update profiles.json
python tools/update_profiles_from_ollama.py --dry-run  # preview changes
python tools/update_profiles_from_ollama.py --reset    # regenerate from scratch
```

### Clean Old Output

```powershell
python tools/clean_local_llm_out.py                    # delete files older than 7 days
python tools/clean_local_llm_out.py --days 3           # delete files older than 3 days
python tools/clean_local_llm_out.py --all              # delete all output files
python tools/clean_local_llm_out.py --keep-latest 10   # keep 10 most recent
python tools/clean_local_llm_out.py --dry-run          # preview what would be deleted
```

### Benchmark Profiles

Test model speed and output quality:

```powershell
python tools/benchmark_profiles.py                              # test all profiles
python tools/benchmark_profiles.py --profiles fast_summary,code_worker  # test specific ones
python tools/benchmark_profiles.py --file src/main.py           # use specific test file
python tools/benchmark_profiles.py --task review-diff            # test different task
```

## Updating an Existing Installation

Re-run the installer with `--force` to update tools and docs:

```powershell
python C:\Users\Zero\local-llm-pipeline\install_local_llm_pipeline.py C:\path\to\your-project --force
```

This overwrites tools/ and docs/ but does not duplicate AGENTS.md/CLAUDE.md policy sections.
