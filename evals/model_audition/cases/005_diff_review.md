# Case 005: Diff Review With Interface Risk

## Purpose

Test whether the model can block a risky diff.

## Prompt

Simulated diff summary:

```diff
- result = {"profile": profile, "model": model, "backend": backend}
+ result = {"profile": profile, "model": model}
- assert result["backend"] == "ollama"
+ assert "model" in result
```

Additional facts: INTERFACES.md says router JSON output includes "backend". Downstream scripts parse result["backend"]. No migration note was added. No deprecation period. All current tests pass after weakening the assertion.

## Required Output

```md
Verdict: PASS / BLOCK

## Blocking Issues
## Non-Blocking Issues
## Required Fixes
## Tests To Add
## INTERFACES.md Updates
## Governance Rules Implicated
```
