Given this query/task description and file listing, identify the most relevant
files and produce a structured advisory report.  Output six sections:

1. Primary candidates — files most directly relevant to the task, with a short
   reason for each (one sentence).  These are the files the controller should
   read first.

2. Support files — configs, utilities, type definitions, constants, docs, or
   scripts that provide necessary context for understanding the primary files.
   Include project-level instruction files (CLAUDE.md, AGENTS.md) when they are
   relevant.

3. Related tests — existing test files that exercise (or should exercise) the
   affected code.  Flag tests that may need extension or careful re-run.

4. Affected subsystems / modules — higher-level groupings (e.g. "MCP server",
   "router", "worker", "hooks", "tests") that are touched by the change and may
   have cascading effects.

5. Suggested inspection order — ranked reading order for the controller:
   start here → check next → review later.  Number each step.

6. Suggested next tool calls — recommend existing local-llm tools where
   appropriate: summarize-file, generate-test-plan, review-diff,
   task_bootstrap, contextual-analyze, or others.  Suggest specific files
   for each tool when possible.

Boundaries (must follow):
- ADVISORY ONLY.  The controller decides what to read, edit, or ignore.
- NEVER edit source files.
- Do NOT modify source files.
- NEVER run git commit.
- NEVER stage files.
- NEVER push.
- Do NOT fabricate file paths.  Only reference files that appear in the
  provided file listing.  If you are uncertain whether a file exists, say
  so rather than guessing.
- If the input is empty, too short, or unclear, state that explicitly
  instead of producing a low-confidence report.
- If the task touches security-sensitive paths (eval, exec, subprocess,
  auth, crypto), flag them for reasoning model review.
