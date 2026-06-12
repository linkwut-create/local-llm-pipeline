# Model Audition System

Each candidate model takes the full 15-case battery. Output determines role suitability.
**Model-first**, not task-first.

## Quick Start

```bash
# Test one model
py -3 tools/model_audition.py --model qwen3-coder:30b

# Test all Ollama models (skips non-text)
py -3 tools/model_audition.py --from-ollama

# Single case
py -3 tools/model_audition.py --model qwen3-coder:30b --case 003

# Score results
py -3 tools/score_model_audition.py --all --report
```

## Design

```
model A → 15 cases → raw outputs (JSONL) → scores → role recommendations → report
model B → 15 cases → raw outputs (JSONL) → scores → role recommendations → report
```

## Cases

| ID | Case | Tests |
|----|------|-------|
| 001 | Context Compression | Summarization, noise filtering |
| 002 | Repo Map | Structural understanding, hallucination control |
| 003 | Tag Drift | Engineering judgment, minimal intervention |
| 004 | JSON Repair | Structured data, validation awareness |
| 005 | Diff Review | Interface awareness, governance rules |
| 006 | Patch Planning | Scope control, risk awareness |
| 007 | Test Failure | Evidence-based diagnosis |
| 008 | Interface Review | Contract awareness, migration planning |
| 009 | Governance Pollution | Format discipline, cleanup precision |
| 010 | Privacy Gate | Security boundary enforcement |
| 011 | Release Gate | Risk aggregation, release judgment |
| 012 | Translation | Terminology stability, uncertainty marking |
| 013 | Subagent Packet | Context compression, scope definition |
| 014 | Command Hygiene | Ambiguity elimination, verification |
| 015 | Role Assignment | Evidence-based vs reputation-based |

## Scoring

Auto-scored on 7 dimensions: correctness, completeness, instruction_following,
format_discipline, hallucination_control, risk_awareness, usefulness.
Each dimension 0-5, weighted. Role thresholds defined in rubric.yaml.

## Rules

- Results in `results/` and `reports/` are gitignored (except `.gitkeep`).
- Real model tests are manual only — `py -3 tools/model_audition.py --from-ollama`.
- CI tests use mocked model calls — `py -3 -m pytest tests/test_model_audition*.py`.
- **Never auto-modify profiles based on audition results.** Only generate recommendations.
