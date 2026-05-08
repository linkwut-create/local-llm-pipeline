Generate a test plan for a file using the local coder model.

Usage: /local-test-plan <target>

Execute:
```
python tools/local_llm_router.py generate-test-plan <target>
```

Then read the latest generate-test-plan JSON in .local_llm_out.

You must:
1. Review the worker's suggested test plan.
2. Read existing test files to match project test style.
3. Decide which tests are worth implementing.
4. Do not directly adopt worker test code without review.
5. Never claim tests pass unless you actually run them.
