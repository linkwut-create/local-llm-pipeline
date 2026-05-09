# MCP Usage Patterns

When to use MCP vs CLI for local LLM tasks.

## Decision Matrix

| Task | MCP | CLI | Notes |
|---|---|---|---|
| Health check | `local_check` | `python tools/local_llm_check.py` | Either works |
| Summarize a file | `local_summarize_file` | `local_llm_router.py summarize-file` | MCP preferred during coding |
| Summarize a directory | `local_summarize_tree` | `local_llm_router.py summarize-tree` | MCP for small dirs, CLI for large |
| Generate test plan | `local_generate_test_plan` | `local_llm_router.py generate-test-plan` | Either works |
| Small diff review | `local_review_diff` | `local_llm_router.py review-diff --stdin` | MCP preferred |
| Small diff debate | `local_debate_review_diff` | `local_llm_debate.py review-diff --stdin --fast` | MCP default is fast+summary |
| Large diff review | **CLI** | `local_llm_router.py review-diff --stdin` | MCP may timeout |
| Large diff debate | **CLI** | `local_llm_debate.py review-diff --stdin` | Full debate ~4 min, too long for MCP |
| Full 3-round debate | **CLI** | `local_llm_debate.py review-diff --stdin` | Not available via MCP by default |
| Benchmark | **CLI** | `benchmark_profiles.py` | Long-running, not for MCP |
| Risk analysis | **CLI** | `local_llm_router.py risk-analysis` | Use CLI for now |

## MCP Best Fit

MCP tools are designed for quick, interactive use during a coding session:

- **`local_check`**: First thing to run. Confirms Ollama is reachable.
- **`local_summarize_file`**: When encountering an unfamiliar file.
- **`local_summarize_tree`**: When exploring a new directory. Keep `max_files` ≤ 20.
- **`local_generate_test_plan`**: Before writing tests for a module.
- **`local_review_diff`**: After making a small change, before committing.
- **`local_debate_review_diff`**: After making a non-trivial change, for a second opinion.

## CLI Best Fit

CLI tools are for batch, long-running, or parameter-heavy tasks:

- **Large diffs** (>500 lines changed): Use CLI to avoid MCP timeout.
- **Full debate**: Use CLI when you need all 3 rounds and detailed output.
- **Benchmarking**: Always CLI.
- **Debugging**: CLI gives raw stderr output that MCP may truncate.
- **CI/CD**: Always CLI — MCP is interactive-only.

## `local_debate_review_diff` Limits

This is the most expensive MCP tool. Understand its constraints:

| Aspect | MCP default | Override |
|---|---|---|
| Rounds | 2 (fast) | Set `fast: false` for 3 rounds |
| Output | summary-only | Set `summary_only: false` for full detail |
| Timeout | 900s | Not configurable via MCP |
| Max diff size | 100K chars | Not configurable via MCP |

**Large diffs**: If the diff is >500 lines or >50K chars, prefer CLI:

```bash
git diff | python tools/local_llm_debate.py review-diff --stdin --fast --summary-only
```

The MCP debate tool will reject diffs >100K chars outright. Diffs approaching this limit may timeout.
This is by design — MCP is for interactive use, not batch processing.

## Typical Workflow

```
1. Start session
   → /mcp (verify local-llm is connected)

2. Explore unfamiliar code
   → local_summarize_tree(path="src/", max_files=15)
   → local_summarize_file(path="src/key_module.py")

3. Make a change
   → Write code
   → pytest

4. Review the change (small diff)
   → local_review_diff(diff_text="<git diff output>")
   → local_debate_review_diff(diff_text="<git diff output>")

5. Before commit
   → Controller (Claude Code / Codex) reviews MCP findings
   → Run pytest one more time
   → Commit
```

## Anti-Patterns

- **Don't** use MCP debate for every one-line change — it wastes ~2 minutes.
- **Don't** use MCP for diffs >100K chars — it will reject or timeout.
- **Don't** treat MCP findings as final — local models are advisory.
- **Don't** use MCP when you need raw model output — use CLI for debugging.
- **Don't** run multiple debate calls concurrently — they compete for GPU memory.
