Draft a PR summary from the provided git diff or commit range. Output:

1. PR title (conventional, <=72 chars)
2. Summary bullets (3-5 — focus on WHY and WHAT)
3. Changes by area (grouped by module/path)
4. Tests / verification (what was tested, or what needs testing)
5. Risks / rollout notes (only if non-obvious)
6. Reviewer focus points (2-3 specific areas for review attention)

ADVISORY ONLY:
- NEVER create a PR
- NEVER push
- NEVER run git commit
- NEVER stage files
- Do NOT modify source files
- NEVER edit source files
- This is a DRAFT suggestion — the controller writes the final PR
- If the diff is empty or too small, say so instead of fabricating
- Keep the summary generic and project-agnostic
