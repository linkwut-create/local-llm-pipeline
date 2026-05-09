Use the local multi-model debate for cross-review of the current git diff.

Run (full 3-round):
```
git diff | python tools/local_llm_debate.py review-diff --stdin
```

Or fast mode (2 rounds, skip deep_reviewer):
```
git diff | python tools/local_llm_debate.py review-diff --stdin --fast
```

For other tasks:
```
python tools/local_llm_debate.py risk-analysis <file>
python tools/local_llm_debate.py architecture-review <file>
python tools/local_llm_debate.py failure-mode-analysis <file>
```

Then read the latest debate JSON and Markdown in .local_llm_out.

You must:
1. Read the high_confidence_findings and controller_must_verify sections.
2. Inspect the actual code/diff directly yourself.
3. Separate worker-suggested issues from personally confirmed issues.
4. Treat disputed_findings as unresolved — investigate both sides.
5. Never claim tests passed unless you actually ran them.
6. Never treat debate output as final approval.
