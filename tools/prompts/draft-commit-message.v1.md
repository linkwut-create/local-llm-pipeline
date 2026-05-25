Draft a commit message from the provided git diff. Output:
1. Conventional commit title (type: brief description, prefer <=72 chars)
2. Body bullets (max 3 — focus on WHY and WHAT, not HOW)
3. Affected areas (brief module/path list)
4. Risk notes (only if there are non-obvious risks)
5. Alternative titles (1-2 optional alternatives with different emphasis)

ADVISORY ONLY:
- NEVER run git commit
- NEVER stage files
- NEVER edit source files
- Do NOT modify source files
- This is a DRAFT suggestion — the controller decides the final message
- If the diff is empty or meaningless, say so instead of fabricating
- Keep the message generic and project-agnostic
