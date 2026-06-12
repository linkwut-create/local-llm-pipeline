# Project Governance Templates

This directory contains the standard governance document templates used across
all projects developed under the local-llm-pipeline agent workflow.

## Quick Start (New Project)

```bash
# Copy templates to new project:
cp -r templates/project-governance/* ../new-project/

# Then run the GRILLME.md interview to customize:
# (use Claude Code or any AI assistant to ask the questions)
```

## Files

| File | Purpose | Universal or Project-Specific |
|------|---------|------------------------------|
| `AGENTS.md` | Project constitution + agent operation rules | **Project-specific** — customize per project |
| `PROBLEMS.md` | Cumulative problems, bans, fragile areas | **Project-specific** — customise per project |
| `LONGTODO.md` | Long-term roadmap, requirements, decisions | **Project-specific** — customize per project |
| `INTERFACES.md` | API/CLI/Config interface contracts | **Project-specific** — customize per project |
| `GRILLME.md` | Universal interview template | **Universal** — use as-is |

## Customization Workflow

1. **Copy** templates to new project root
2. **Run GRILLME.md interview** with the project owner (30-50 questions)
3. **Fill in** each file based on interview answers
4. **Remove** all `<!-- TODO -->` markers and `<!-- TEMPLATE -->` comments
5. **Commit** the customized files to the new project

## Maintenance

After initial creation, update these files at the end of every non-trivial task:

| Trigger | Update |
|---------|--------|
| New bug or limitation found | PROBLEMS.md §1 |
| Agent made a preventable mistake | PROBLEMS.md §2 (new BAN) |
| New feature planned | LONGTODO.md §2 or §3 |
| Interface changed | INTERFACES.md + INTERFACES.md §7 |
| Design decision made | AGENTS.md §1 or LONGTODO.md §5 |
| Old problem resolved | PROBLEMS.md §1 (update status) |
