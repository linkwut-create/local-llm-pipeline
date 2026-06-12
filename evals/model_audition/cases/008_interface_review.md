# Case 008: Interface Review for New CLI

## Purpose

Test whether the model understands CLI/interface contract requirements.

## Prompt

Proposed CLI: `python tools/model_audition.py --model <name>`, `--from-ollama`, `--case <id>`, `--dry-run`.

Proposed output files: `evals/model_audition/results/YYYYMMDD-HHMMSS.jsonl`, `evals/model_audition/reports/YYYYMMDD-HHMMSS.md`.

Question: What interface contract must be documented before merging?

## Required Output

```md
# Interface Review

## CLI Arguments
## Exit Codes
## Output Files
## JSONL Schema
## Backward Compatibility
## INTERFACES.md Required Sections
## Verdict
```
