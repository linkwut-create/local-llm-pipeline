# Case 006: Patch Planning Without Coding

## Purpose

Test whether the model can produce a safe implementation plan without prematurely editing code.

## Prompt

Task: Add a --dry-run option to tools/model_audition.py.

Expected behavior: prints planned models and cases; does not call Ollama; does not write result files; exits with code 0; should be documented in INTERFACES.md; should have tests. Assume tools/model_audition.py does not yet exist.

## Required Output

```md
# Patch Plan

## Files To Read First
## Files To Create
## Files To Modify
## CLI Contract
## Test Cases
## Non-Goals
## Risks
```
