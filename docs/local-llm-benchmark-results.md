# Local LLM Benchmark Results

## 2026-05-09 Benchmark (v0.1.3 baseline)

Hardware: zero12 (FEVM AI Max+ 395, Radeon 8060S, 128GB LPDDR5X)
Ollama: http://193.168.2.2:11434
Network: R9000P → zero12 via 193.168.2.x LAN (~1ms RTT)

| Task | Profile | Model | Input | Size | Time | Output | Quality | Notes |
|---|---|---|---|---:|---:|---:|---|---|
| summarize-file | fast_summary | qwen3.5-9b-q8 | AGENTS.md | 1.8KB | 40.6s | 2627 | usable | identified key files and risks correctly |
| summarize-tree | fast_summary | qwen3.5-9b-q8 | tools/ | 4KB | 100.0s | 4641 | usable | complete tree summary, slow for small dir |
| generate-test-plan | code_worker | qwen3-coder:30b | local_llm_worker.py | 24.8KB | 23.6s | 2380 | good | fastest profile, structured plan |
| review-diff | diff_reviewer | qwen3.6:27b-q8-ud | AGENTS.md | 1.8KB | 138.9s | 3357 | good | thorough review |
| risk-analysis | reasoning_checker | qwen3.5-27b-reasoning | risk-policy.md | 2.1KB | 103.0s | 2817 | good | chain-of-thought visible |
| architecture-review | deep_reviewer | qwen3.5-35b-q8 | local-llm-worker.md | 4.1KB | 63.8s | 5152 | good | most detailed output |
| translate-text | translation | translategemma-27b-it-q8 | AGENTS.md | 1.8KB | 97.3s | 1039 | acceptable | lower output/input ratio |

### Observations

1. **code_worker (qwen3-coder:30b) is the fastest** — 23.6s, even with 24.8KB input. Good choice for daily code tasks.
2. **fast_summary (qwen3.5-9b-q8) is slower than expected** — 40-100s. The 9B model on zero12 is not as "fast" as the name implies. Consider keeping it for its lighter memory footprint rather than speed.
3. **deep_reviewer (qwen3.5-35b-q8) is surprisingly fast** — 63.8s, faster than some lighter profiles. Good output quality and volume.
4. **diff_reviewer (qwen3.6:27b-q8-ud) is the slowest** — 138.9s. Acceptable for code review which isn't time-critical.
5. **reasoning_checker (qwen3.5-27b-reasoning)** — 103s. The thinking/reasoning overhead is visible but results are structured.
6. **translation (translategemma-27b-it-q8)** — 97s, low output ratio. Fine for occasional use.

### Profile Tuning Decisions

- **fast_summary**: Keep qwen3.5-9b-q8. Speed is acceptable for background tasks. Memory-efficient for concurrent use.
- **code_worker**: Keep qwen3-coder:30b. Best speed/quality ratio.
- **diff_reviewer**: Keep qwen3.6:27b-q8-ud. Slow but review quality matters more.
- **deep_reviewer**: Keep qwen3.5-35b-q8. Only manual invocation, not default.
- **reasoning_checker**: Keep qwen3.5-27b-reasoning. Only manual invocation.
- **translation**: Keep translategemma-27b-it-q8. Specialized task.

### max_chars Assessment

- fast_summary at 60000 is adequate after v0.1.1 truncation fix (adaptive budget allocation).
- code_worker at 90000 covers most single-file inputs.
- diff_reviewer at 120000 handles large diffs.
- No changes needed.

### Model Tiers

Daily (auto-routed):
- fast_summary (9B) — summarize, rewrite
- code_worker (30B) — extract-todos, test-plan, test-draft, find-related

Manual only:
- diff_reviewer (27B) — review-diff
- deep_reviewer (35B) — deep-code-review, architecture-review
- reasoning_checker (27B) — risk-analysis, logic-check, failure-mode
- translation (27B) — translate-text
