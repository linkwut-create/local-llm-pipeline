# Local LLM Debate Results

Quality calibration log for `local_llm_debate.py`. Each entry records a real dogfood run against actual project changes.

## 2026-05-09 — v0.2.1 calibration

Input: git diff for v0.2.1 debate calibration changes
- Modified file: `tools/local_llm_debate.py`
- Changes: MAX_FINDINGS enforcement, --summary-only flag, summary_only markdown support

### Fast mode (2 rounds: code_worker + reasoning_checker)

- Duration: 221s (~3.7 min)
- Round 1 (code_worker, qwen3-coder:30b): 15.48s
- Round 2 (reasoning_checker, qwen3.5-27b-reasoning): 205.58s

Useful findings:
- Summary-only mode produces 3 finding types while full mode produces 5 — consumers expecting consistent field presence could be confused
- MAX_FINDINGS key ordering dependency — code relies on result keys matching MAX_FINDINGS keys, which isn't enforced
- Markdown synthesis section references findings that may have been truncated by MAX_FINDINGS — a summary consumer might expect either full findings or none

False positives (Round 1 over-speculation caught by Round 2):
- Round 1 claimed MAX_FINDINGS was "not consistently enforced" — Round 2 correctly showed it's centrally enforced in a single location
- Round 1 claimed `summary_only` parameter introduces a "breaking change" — Round 2 correctly noted the default=False makes it backward-compatible
- Round 1 claimed test gaps as definitive problems without seeing actual test files — Round 2 flagged as speculation

Overstatements:
- Round 1 flagged "error handling robustness" without identifying any actual flaw — Round 2 showed the code is already robust

**Verdict:** usable. Round 2 effectively filtered Round 1's noise. The debate mechanism successfully caught 3 over-speculated findings and 1 false positive. Cost is acceptable for non-trivial diffs, too slow for one-line fixes. The 3 high-confidence findings are all real (if minor) concerns worth noting.

### Full mode (3 rounds, not run for v0.2.1 — small diff)

Full mode was not dogfooded for this small diff. Per v0.2.1 guidance, full debate should only be used for:
- Large diffs (>200 lines changed)
- Architecture changes
- Pre-release reviews

### Quality notes

1. **Output length**: With `--summary-only`, JSON output excludes per-round raw text and disputed/test_gaps fields. This keeps the output compact for MCP/CLI consumption.
2. **Finding limits**: `MAX_FINDINGS` caps each category to prevent output bloat.
3. **Fast default**: For day-to-day diff review, `--fast` (2 rounds) is the recommended default.

## Template for future runs

```markdown
## 2026-xx-xx — vX.Y.Z dogfood

Input:
- git diff for ...

Fast mode:
- Duration: Xs
- Profiles: code_worker + reasoning_checker
- Useful findings:
  - ...
- False positives:
  - ...
- Overstatements:
  - ...
- Verdict: usable / too noisy / too slow

Full mode:
- Duration: Xs
- Profiles: code_worker + reasoning_checker + deep_reviewer
- High confidence findings: N
- Candidate findings: N
- Disputed findings: N
- Controller must verify: N
- Verdict: useful for large diffs / too slow for small diffs
```
