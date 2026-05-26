Draft a changelog entry from the provided git diff or commit range. Output:

1. Suggested section heading (e.g. Unreleased / Post-v0.X.0 / v0.X.0 candidate)
2. Bullet entries grouped by area (features, fixes, docs, internal)
3. User-visible changes (what users will notice)
4. Internal/dev-only changes (refactors, tests, infrastructure)
5. Tests / validation notes
6. Risk / migration notes (only if relevant)
7. Suggested placement in existing CHANGELOG.md

ADVISORY ONLY:
- NEVER edit CHANGELOG.md
- Do NOT modify source files
- NEVER run git commit
- NEVER stage files
- NEVER push
- This is a DRAFT suggestion — the controller writes the final entry
- If the diff is empty or too small, say so instead of fabricating
- Keep the entry generic and project-agnostic
