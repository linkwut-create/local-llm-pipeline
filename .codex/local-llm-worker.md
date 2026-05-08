# Local Multi-Model Worker Rules for Codex

Codex may call `tools/local_llm_router.py` for read-only auxiliary work.

## Allowed Tasks

- summarize-file
- summarize-tree
- find-related-files
- extract-todos
- generate-test-plan
- generate-test-draft
- review-diff
- deep-code-review
- architecture-review
- risk-analysis
- logic-check
- failure-mode-analysis
- translate-text
- rewrite-text

## Rules

- Worker output is advisory.
- Codex must verify important claims directly.
- Codex must run tests itself.
- Codex must inspect git diff itself.
- The worker must not modify source code.
- The worker must not read secrets.
- The worker must not handle auth, crypto, database migration, deployment, release, or final approval.

## Preferred Workflow

1. Use local worker to compress broad context.
2. Read the worker JSON output.
3. Read only the key files directly.
4. Implement changes.
5. Run tests.
6. Use worker for initial diff review.
7. Verify diff directly.

## Standard Commands

```bash
python tools/local_llm_check.py
python tools/local_llm_router.py summarize-file <path>
python tools/local_llm_router.py summarize-tree <path> --max-files 30
python tools/local_llm_router.py extract-todos <path>
python tools/local_llm_router.py generate-test-plan <path>
git diff | python tools/local_llm_router.py review-diff --stdin
python tools/local_llm_router.py risk-analysis <path>
```
