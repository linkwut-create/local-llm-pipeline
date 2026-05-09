# Local LLM Debate — Multi-Model Cross-Review

## Purpose

`local_llm_debate.py` runs the same input through multiple local models in sequence, where each model reviews and challenges the previous round's output. The goal is to catch blind spots that a single model misses.

This is NOT a replacement for the controller (Claude Code / Codex) reviewing the output. It is an advisory tool that produces candidate findings for the controller to verify.

## Three-Round Flow

```
Input (diff / file / plan)
    ↓
Round 1: code_worker (qwen3-coder:30b)
    Initial review — find bugs, test gaps, compatibility risks
    ↓
Round 2: reasoning_checker (qwen3.5-27b-reasoning)
    Challenge Round 1 — find logic flaws, over-speculation, missed boundaries
    ↓
Round 3: deep_reviewer (qwen3.5-35b-q8)
    Synthesize — classify findings by confidence level
    ↓
Output: structured report with 4 finding categories
```

## Output Categories

| Category | Meaning |
|---|---|
| `high_confidence_findings` | Both rounds agree, evidence is clear |
| `candidate_findings` | Plausible but needs verification |
| `disputed_findings` | Rounds disagree — controller decides |
| `controller_must_verify` | Cannot be determined without tests or more code |

## Supported Tasks

- `review-diff` — cross-review a git diff
- `risk-analysis` — multi-angle risk assessment
- `architecture-review` — architecture tradeoff analysis
- `failure-mode-analysis` — enumerate and challenge failure scenarios

## Usage

```bash
# Review current diff (full 3-round)
git diff | python tools/local_llm_debate.py review-diff --stdin

# Fast mode (2 rounds, skip deep_reviewer)
git diff | python tools/local_llm_debate.py review-diff --stdin --fast

# Risk analysis on a file
python tools/local_llm_debate.py risk-analysis docs/plan.md

# Architecture review
python tools/local_llm_debate.py architecture-review docs/local-llm-worker.md

# Custom profiles
python tools/local_llm_debate.py review-diff changes.patch --profiles code_worker,deep_reviewer
```

## When to Use

- Before merging a non-trivial diff
- When assessing risk of a new approach
- When reviewing architecture changes
- When you want a second opinion before the controller reviews

## When NOT to Use

- For simple, obvious changes (use single-model `review-diff` instead)
- As a substitute for running tests
- As a final approval mechanism
- For tasks that need fast turnaround (debate takes 2-5 minutes)

## Performance

Based on v0.1.3 benchmarks (zero12, Radeon 8060S, 128GB):

| Round | Profile | Model | Typical Time |
|---|---|---|---|
| 1 | code_worker | qwen3-coder:30b | ~24s |
| 2 | reasoning_checker | qwen3.5-27b-reasoning | ~103s |
| 3 | deep_reviewer | qwen3.5-35b-q8 | ~64s |
| **Total** | | | **~3 min** |

Fast mode (rounds 1+2 only): ~2 min.

## Why Debate Cannot Replace Controller Review

1. Local models can hallucinate — they may agree on a false finding
2. They cannot run tests or read files outside the input
3. They have no project context beyond what is provided
4. High-confidence agreement between two local models is still advisory
5. The controller must verify every actionable finding
