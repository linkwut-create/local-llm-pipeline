# Case 003: Ollama Model Tag Drift

## Purpose

Test whether the model can distinguish model tag drift from model capability failure.

## Prompt

A profile called deep_reviewer currently uses model "qwen3.6:35b-q8-ud" (risk_level: high, _backend_class: ollama_heavy_manual).

The call ledger shows: 149 calls, 142 failures (95.3% failure rate).

A developer suggests replacing it with llama4:code.

But ollama list shows: qwen3.6:35b, qwen3.6:27b, qwen3-coder:30b, gemma4-26b-it:q8_0, llama4:code.

The user says: "The underlying weights probably did not change. The tag probably changed."

## Required Output

```md
# Diagnosis

## Likely Root Cause
## Wrong Fix To Avoid
## Minimal Correct Fix
## Commands To Verify
## Tests To Run
## PROBLEMS.md Entry To Add
## Final Recommendation
```
