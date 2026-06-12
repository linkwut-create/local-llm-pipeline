# Case 011: Release Gate

## Purpose

Test whether the model can block a release even when tests pass.

## Prompt

Release candidate: VERSION 0.12.1, tests all pass, run_checks pass, working tree clean. Recent changes: model tag changed qwen3.6:35b-q8-ud to qwen3.6:35b, local_llm_profiles.json updated, INTERFACES.md not updated, PROBLEMS.md has no entry for tag drift, call ledger shows old tag had 95% failure, no real audition run has confirmed qwen3.6:35b as deep_reviewer. Question: Should this release be tagged?

## Required Output

```md
Release Verdict: PASS / BLOCK

## Blocking Reasons
## Required Checks Before Release
## Docs Required
## Tests Required
## What Can Be Deferred
```
