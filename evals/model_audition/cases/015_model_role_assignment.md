# Case 015: Model Role Assignment From Evidence

## Purpose

Test whether the model can recommend roles based on audition results rather than model reputation.

## Prompt

Audition summary — qwen3-coder:30b: JSON repair 5/5, patch planning 4/5, test failure analysis 4/5, release gate 2/5, privacy gate 3/5, translation 2/5, latency medium, format high. qwen3.6:35b: tag drift 5/5, diff review 5/5, interface review 4/5, release gate 5/5, context compression 3/5, JSON repair 3/5, latency slow, format medium. gemma4-26b-it:q8_0: context compression 5/5, governance pollution 4/5, docs summary 5/5, JSON repair 2/5, release gate 2/5, translation 3/5, latency fast, format high.

Assign each model to suitable roles. Do not rank them globally.

## Required Output

```md
# Role Assignment

## qwen3-coder:30b
Recommended Roles:
Avoid:
Reason:

## qwen3.6:35b
Recommended Roles:
Avoid:
Reason:

## gemma4-26b-it:q8_0
Recommended Roles:
Avoid:
Reason:

## Final Profile Suggestions
## Do Not Change Yet
```
