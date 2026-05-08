Run risk analysis on a file or plan using the local reasoning model.

Usage: /local-risk <target>

Execute:
```
python tools/local_llm_router.py risk-analysis <target>
```

Then read the latest risk-analysis JSON in .local_llm_out.

You must:
1. Report failure modes identified by the worker.
2. Assess which risks are plausible vs speculative.
3. Identify items you need to verify directly.
4. Worker risk analysis is advisory — make your own final judgment.
