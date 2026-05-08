# Local LLM Routing Logic

## How the Router Works

```
User/Controller runs:
    python tools/local_llm_router.py <task> [target] [options]

Router:
    1. Reads tools/local_llm_tasks.json for task config
    2. Reads tools/local_llm_profiles.json for profile config
    3. Determines profile from task -> default_profile
    4. Determines model from profile -> model
    5. Checks model exists via `ollama list`
    6. Falls back to first available model if needed
    7. Delegates to tools/local_llm_worker.py
```

## Profile Selection

| Profile | Default Model | Used For |
|---|---|---|
| fast_summary | qwen3.5-9b-q8 | summarize-file, summarize-tree, rewrite-text |
| code_worker | qwen3-coder:30b | extract-todos, find-related-files, generate-test-plan, generate-test-draft |
| diff_reviewer | qwen3.6:27b-q8-ud | review-diff |
| deep_reviewer | qwen3.5-35b-q8 | deep-code-review, architecture-review |
| reasoning_checker | qwen3.5-27b-reasoning | risk-analysis, logic-check, failure-mode-analysis |
| translation | translategemma-27b-it-q8 | translate-text |

## Task Risk Levels

| Risk | Tasks | Controller Action |
|---|---|---|
| low | summarize-file, summarize-tree, extract-todos, find-related-files, translate-text, rewrite-text | Review output |
| medium | generate-test-plan, generate-test-draft, review-diff, logic-check | Verify key claims |
| medium-high | risk-analysis, failure-mode-analysis | Verify all claims |
| high | deep-code-review, architecture-review | Must independently verify |

## Override Behavior

```bash
# Override profile
python tools/local_llm_router.py summarize-file README.md --profile deep_reviewer

# Override model directly
python tools/local_llm_router.py summarize-file README.md --model qwen3.5-35b-q8:latest

# Use environment variables
set LOCAL_LLM_MODEL=mistral-medium-3.5-128b-q5_k_xl:latest
python tools/local_llm_router.py review-diff --stdin
```

## Customizing Profiles

Edit `tools/local_llm_profiles.json` to change model assignments.
Run `python tools/local_llm_check.py` to see recommended assignments based on available models.

## Adding New Tasks

1. Add task definition to `tools/local_llm_tasks.json`
2. Add task prompt to `TASK_PROMPTS` in `tools/local_llm_worker.py`
3. Assign to appropriate profile in `tools/local_llm_profiles.json`
