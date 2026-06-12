# Case 013: Subagent Task Packet Generation

## Purpose

Test whether the model can prepare a minimal context package for a subagent.

## Prompt

User request: "Fix stale Ollama tags in local_llm_profiles.json." Known: current tag qwen3.6:35b, old tag qwen3.6:35b-q8-ud. Do not change to llama4:code. Do not add DeepSeek. Do not change unrelated profiles. Need JSON validation and config validation. Need PROBLEMS.md entry. Create a task packet for a code-worker subagent.

## Required Output

```md
# Subagent Task Packet

## Task
## Allowed Files
## Forbidden Files
## Required Reads
## Exact Changes Allowed
## Commands To Run
## Output Required From Subagent
## Stop Conditions
```
