# Case 002: Repo Map and Modification Targeting

## Purpose

Test whether the model can infer where to make changes from a simplified repository map.

## Prompt

Repository map:

```txt
local-llm-pipeline/
  AGENTS.md, PROBLEMS.md, LONGTODO.md, INTERFACES.md, GRILLME.md, CLAUDE.md
  tools/
    local_llm_router.py, local_llm_worker.py, local_llm_profiles.json
    validate_configs.py, local_llm_mcp_server.py, call_ledger.py
    local_llm_check.py, feedback_ledger.py
  tests/
    test_router.py, test_worker.py, test_profiles.py
    test_validate_configs.py, test_mcp_server.py
  templates/project-governance/
    AGENTS.md, PROBLEMS.md, LONGTODO.md, INTERFACES.md, GRILLME.md, README.md
```

Task: Add a model audition system that lets every candidate model run the same full suite of test prompts, saves raw outputs, scores role suitability, and produces a Markdown report. Do not call real cloud APIs. Do not modify existing profile assignments automatically.

## Required Output

```md
# Repo Modification Map

## New Files
## Existing Files To Modify
## Existing Files To Avoid
## Data Flow
## Test Strategy
## Risk Areas
```
