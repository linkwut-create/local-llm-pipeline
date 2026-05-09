# Local LLM Code Drafting

## Purpose

`local_draft_code` lets local models draft code fixes, features, refactors, and improvements.
All output goes to `.local_llm_out/` — never to source files. The controller (Claude Code / Codex / human)
reviews, decides, and applies manually.

## Available Tasks

| Task | What it does | When to use |
|---|---|---|
| `draft-fix` | Draft a bug fix | You know what's broken, want a candidate fix |
| `draft-feature` | Draft a new feature implementation | You have a spec, want a first draft |
| `draft-refactor` | Draft a refactoring plan | You see structural issues, want options |
| `suggest-improvements` | Proactively suggest improvements | You want the model to read code and propose changes |

## Safety Boundary

- Drafts write **only to `.local_llm_out/`**
- **Never** modifies source files
- Every draft task has `may_modify_code: false`
- Every draft task has `controller_must_verify: true`
- MCP tool `local_draft_code` is source-non-mutating
- Controller must review every line before applying

## Usage

### CLI

```powershell
# Draft a fix
echo "fix null pointer in parse_config" | python tools/local_llm_worker.py draft-fix --stdin src/config.py

# Draft a feature
echo "add retry logic to API calls" | python tools/local_llm_worker.py draft-feature --stdin src/api.py

# Suggest improvements (reads file, no prompt needed)
python tools/local_llm_worker.py suggest-improvements src/main.py
```

### MCP

```
Call local_draft_code with:
  task = "draft-fix"
  prompt = "description of the issue"
  context_file = "path/to/affected/file.py"
```

## Real Project Dogfood (v0.7.1)

Tested on `local-translator-agent` (Python translation service).

### draft-fix
- Task: fix typo "translaton" → "translation" in README
- Result: Correctly identified fix, provided before/after, listed risks
- Source: NOT modified
- Verdict: Useful for documentation fixes

### suggest-improvements
- Task: read README.md and suggest 3+ improvements
- Result: Proposed modular refactoring (OCR/audio/translation separation),
  dependency injection, caching for translations, type hints, logging
- Source: NOT modified
- Verdict: Surprising quality — suggestions were specific to the project

## Anti-Patterns

- **Don't** apply drafts without review — local models can hallucinate code
- **Don't** use draft-refactor on code you don't understand
- **Don't** expect drafts to compile or pass tests without modification
- **Don't** use MCP draft_code for critical security or auth code
- **Don't** treat draft output as "patches" — they are suggestions, not diffs

## Workflow

```
1. Identify need (bug, feature, improvement)
2. Call local_draft_code with context
3. Read draft in .local_llm_out/
4. Controller decides:
   ├── Good → manually apply (copy-paste or rewrite)
   ├── Needs work → discard draft, write own implementation
   └── Bad → discard
5. Run tests after applying
6. Commit only the reviewed, tested changes
```
