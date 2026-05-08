Auto-route a task to the appropriate local model using the router.

Usage: /local-route <task> <target> [options]

Execute:
```
python tools/local_llm_router.py <task> <target> [options]
```

The router will:
1. Read task and profile configurations.
2. Select the best available model.
3. Delegate to the worker.

After execution, read the latest .local_llm_out JSON and report:
1. Which profile and model were selected.
2. Key findings from the worker.
3. Items requiring your direct verification.
4. Worker output is advisory — verify important claims.
