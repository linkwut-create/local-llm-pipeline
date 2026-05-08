Use the local multi-model worker for an initial review of the current git diff.

Run:
```
git diff | python tools/local_llm_router.py review-diff --stdin
```

Then read the latest review-diff JSON and Markdown in .local_llm_out.

You must:
1. Summarize worker-suggested candidate issues.
2. Inspect git diff directly yourself.
3. Separate worker-suggested issues from personally confirmed issues.
4. List tests that still need to run.
5. Never claim tests passed unless you actually ran them.
