Run a local LLM worker task directly.

Usage: /local-worker <task> <target> [options]

Available tasks: summarize-file, summarize-tree, extract-todos, find-related-files,
generate-test-plan, generate-test-draft, review-diff, deep-code-review,
architecture-review, risk-analysis, logic-check, failure-mode-analysis,
translate-text, rewrite-text.

Execute the worker, then read the .local_llm_out JSON output.

You must:
1. Report worker findings as candidates only.
2. Note any uncertain points.
3. Never claim tests passed unless you actually ran them.
4. Treat all worker output as advisory.
