# Local LLM Model Notes

Empirical observations and recommendations. Based on v0.6.0 benchmark (2026-05-09, zero12, AGENTS.md test file) and dogfood usage through v0.6.1.

## Benchmark-Driven Findings

### Surprising Results

1. **qwen3-coder:30b (18GB) is 6x faster than qwen3-coder-next-q8 (86GB)** for code tasks, but next-q8 is the newer, more capable model. Keep next-q8 as primary coder for intelligence; use qwen3-coder:30b as fast fallback.

2. **qwen3.6:35b-q8-ud outperforms qwen3.5-35b-q8** in both speed and reliability. qwen3.5-35b TIMED OUT on review-diff. qwen3.6 is the clear replacement for all review/architecture tasks.

3. **qwen3.5-27b-reasoning is more reliable than deepseek-r1-distill-qwen:32b** for time-limited use. deepseek timed out on logic-check. Keep deepseek for CLI-based deep analysis where timeouts don't matter.

4. **translategemma-27b-it is unusable for MCP** — timed out at 300s. glm-4.7-flash-q8 is the only viable option.

5. **nvidia-nemotron-30b-q8_0 (33GB) is surprisingly fast** at 45s for summarization — competitive with qwen3.5-9b (42s). Worth exploring for general tasks.

## Fast Summary

| Observation | Detail |
|---|---|
| `qwen3.5-9b` is fast and reliable for summarization | ~10s for a file, good structure |
| `gemma4:e4b` is the fastest option | Use when speed > quality |
| `glm-4.7-flash` has strong multilingual support | Preferred for Chinese content |
| Light models sometimes skip details | Controller must verify completeness |

**When to use**: Daily file/directory summarization. Default for `summarize-file` and `summarize-tree`.

## Code Workers

| Observation | Detail |
|---|---|
| `qwen3-coder-next-q8` is significantly better than `qwen3-coder:30b` | Prefer for all code tasks |
| `qwen3-coder-next-q8-agent` sometimes produces more structured output | Good for test plans, JSON tasks |
| Coder models sometimes over-explain | Set `max_output_chars` lower if output is too verbose |
| NOT good at risk analysis or high-level architecture | Use reasoning or deep reviewer for those |

**When to use**: Test plan generation, TODO extraction, code explanation, finding related files.

## Diff Reviewers

| Observation | Detail |
|---|---|
| `qwen3-coder-next-q8-agent` gives the most structured review output | Best for MCP `local_review_diff` |
| Diff reviewers find real bugs but also produce false positives | ~30% of findings are noise |
| Small diffs (<200 lines) review well | Large diffs need debate mode or human review |
| Diff reviewers tend to be overly cautious | Controller must triage findings |

**When to use**: Small to medium diff review. Large diffs use debate or CLI.

## Deep Reviewers

| Observation | Detail |
|---|---|
| `qwen3.5-35b` is the daily deep review workhorse | ~30-60s, reliable |
| `mistral-medium-3.5-128b` is the strongest but very slow | ~60-90s, use for release audits only |
| Deep reviewers sometimes "agree with everything" | Pair with reasoning checker for adversarial review |
| NOT suitable for quick turnaround | Only use `--fast` debate or single-model for routine review |

**When to use**: Architecture review, release audit, deep code review of critical paths.

## Reasoning Checkers

| Observation | Detail |
|---|---|
| `qwen3.5-27b-reasoning` is the fastest reasoning model | ~30-60s, good for daily risk analysis |
| `deepseek-r1-distill-llama:70b` is the strongest | ~90-120s, use for critical risk assessment |
| Reasoning models sometimes overthink simple questions | Use fast summary for simple tasks |
| Reasoning output is verbose | Set lower `max_output_chars` for MCP use |

**When to use**: Risk analysis, failure mode enumeration, logic checking, security boundary review.

## Translation

| Observation | Detail |
|---|---|
| `translategemma-27b` is purpose-built for translation | Preferred for all translation tasks |
| `glm-4.7-flash` is a good fast alternative | ~10s vs ~30s for translategemma |
| Translation models may lose technical precision | Controller must verify technical translations |
| NOT suitable for code | Translation models may "translate" code identifiers |

**When to use**: User-facing text translation, documentation localization.

## Embedding

| Observation | Detail |
|---|---|
| `nomic-embed-text-v2-moe` is the primary choice | Good quality, reasonable speed |
| `bge-m3` has better multilingual support | Preferred for mixed Chinese/English content |
| Embedding models are NOT for text generation | They only produce vectors |

**When to use**: Semantic search, finding similar files, project-level RAG (future).

## General Notes

1. **Heavy models are a scarce resource**: Only one heavy model can run at a time on consumer hardware. Don't call `mistral-medium-3.5-128b` for a small diff review.

2. **Coder vs Reasoning division**: Coder models find "what" (bugs, missing checks). Reasoning models find "why" (architectural issues, failure cascades). Use both for critical reviews.

3. **Temperature matters**: Lower temperature (0.1) for review/analysis tasks. Higher (0.2) for creative/translation tasks.

4. **Timeout expectations**:
   - Fast models: 30-60s
   - Coder models: 20-60s
   - Reasoning models: 60-120s
   - Heavy models: 90-180s
   - Debate (fast): 120-240s

5. **Model variants to skip**: Models with `-original`, `-agentprefill`, `-toolfix` suffixes are development variants. Use the base models.

6. **Backend choice**: Ollama is the default. If llama.cpp gives better inference performance (especially for reasoning models on AMD), set:
   ```powershell
   $env:LOCAL_LLM_BASE_URL = "http://localhost:8080/v1"
   ```
   The worker already supports OpenAI-compatible API. Set `--provider openai-compatible` or configure `LOCAL_LLM_BASE_URL`.
