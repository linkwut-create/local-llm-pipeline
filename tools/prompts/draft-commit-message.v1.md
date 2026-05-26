Draft a commit message from the provided git diff. Output:

1. Commit title
   - One conventional commit title (type: brief description)
   - Imperative mood, no trailing period, prefer <=72 chars

2. Commit body
   - 2-5 bullets
   - Focus on what changed and why (not how)
   - Keep each bullet to one line

3. Tests / validation
   - List tests mentioned in the diff, or
   - Say "Not provided in input" if no tests are visible

4. Risk notes
   - Real risks only (breaking changes, missing coverage, migration needed)
   - If no obvious risk is visible from the diff, say "No obvious risk from provided diff"
   - Do not repeat input text as risk

5. Controller checklist
   - Verify diff scope matches the commit
   - Verify tests were run
   - Edit final message before committing

ADVISORY ONLY:
- NEVER run git commit
- NEVER stage files
- NEVER push
- NEVER edit source files
- Do NOT modify source files
- This is a DRAFT — the controller decides the final message
- If the diff is empty, too short, or unclear, say so instead of fabricating
- Do not claim tests passed unless present in the input
- Keep the message generic and project-agnostic
