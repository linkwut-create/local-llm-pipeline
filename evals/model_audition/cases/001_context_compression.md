# Case 001: Context Compression

## Purpose

Test whether the model can compress noisy project context into a useful task packet.

## Global Rules

1. Follow the requested output format exactly.
2. Do not invent files, commands, tests, or project facts.
3. Prefer minimal safe changes over broad refactors.
4. If the task is risky, say so explicitly.
5. If cloud upload is unsafe, block it.
6. If a model tag appears missing, check for tag drift before replacing the model family.
7. If interface compatibility may be affected, require INTERFACES.md updates.
8. If governance documents are polluted, recommend cleanup before commit.
9. Answer as if your output will be used to decide which role this model should occupy.

## Prompt

You are given the following project situation:

* Project: local-llm-pipeline
* Purpose: local-first AI development control layer.
* Existing files: AGENTS.md, PROBLEMS.md, INTERFACES.md, LONGTODO.md.
* Recent event: Governance files were generated. Some had pollution risk: "Thought for", "Write(...)", "Wrote N lines", "# INTERFACES.md" inside GRILLME.md, wrong command containing "IN.md". Later cleanup claimed: titles match filenames, pollution grep is clean except PROBLEMS.md BAN self-match, working tree clean after commit.
* Current user request: "Add a model audition system. Each model should do the full test suite. Do not pre-assign models to tasks before seeing their full answers."

## Required Output

```md
# Task Packet

## Project
## Current Request
## Relevant Existing Rules
## Risks
## Non-Goals
## Minimal Implementation Plan
## Tests Needed
## Files Likely To Change
```
