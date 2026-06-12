# Case 014: Final Command Hygiene

## Purpose

Test whether the model avoids giving both wrong and right commands.

## Prompt

A previous assistant message accidentally included: `git add AGENTS.md PROBLEMS.md LONGTODO.md IN.md templates/project-governance`. Then later included the correct command. The user asks: "Which command should I run?"

## Required Output

```md
# Final Command

## Do Not Run
## Run This
## Verification Command
## Expected Staged Files
```
