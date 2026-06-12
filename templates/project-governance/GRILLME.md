# GRILLME.md

<!-- TEMPLATE: This file is a universal interview template.
     It does not need project-specific customization.
     Use it as-is to initialize AGENTS.md / PROBLEMS.md / LONGTODO.md / INTERFACES.md
     for any new project. -->

## Purpose

Use this process to extract stable project knowledge from the project owner and update:
- `AGENTS.md` — project constitution / agent operation rules
- `PROBLEMS.md` — cumulative problems / forbidden patterns / known pitfalls
- `LONGTODO.md` — long-term requirements / roadmap / deferred ideas
- `INTERFACES.md` — interface contracts / compatibility boundaries

**Do not implement code during this process.**

## Rules for the Interviewer

1. Ask hard questions. Don't accept vague answers.
2. Convert answers into durable project rules — not prose, not wishes.
3. Separate facts, preferences, prohibitions, and open questions.
4. After the interview, produce patch-ready markdown updates.
5. Each answer must map to a specific file and section.
6. Ask follow-up questions when answers are ambiguous or contradictory.

## Question Groups

### A. Project Identity
| # | Question | Maps To |
|---|----------|---------|
| A1 | This project is mainly for: yourself, a team, users, developers, or commercial use? | AGENTS.md §0 |
| A2 | What is the ONE thing this project must do better than any existing alternative? | AGENTS.md §0 |
| A3 | What should this project NEVER become? (3-5 hard prohibitions) | AGENTS.md §1, LONGTODO.md §1 |
| A4 | What is acceptable complexity, and what is unacceptable complexity? | AGENTS.md §1 |
| A5 | If this project had to be handed off, what 3 things must they understand first? | AGENTS.md §0 |

### B. Design Philosophy
| # | Question | Maps To |
|---|----------|---------|
| B1 | Rank these priorities: local-first, speed, quality, cost, extensibility, UI polish | AGENTS.md §1 |
| B2 | When trade-offs happen, what ALWAYS wins? Give 3 concrete examples. | AGENTS.md §1 |
| B3 | Should the system prefer explicit configuration or automatic behavior? | AGENTS.md §1 |
| B4 | Should failures be loud (crash/block) or silent (warn/continue)? | AGENTS.md §1, PROBLEMS.md §3 |
| B5 | Should the system optimize for expert users or ordinary users? | AGENTS.md §1 |

### C. Technical Boundaries
| # | Question | Maps To |
|---|----------|---------|
| C1 | Which dependencies are ALWAYS allowed? Which require explicit approval? | AGENTS.md §7 |
| C2 | Which dependencies are FORBIDDEN? | AGENTS.md §7, PROBLEMS.md §2 |
| C3 | What parts MUST stay local? What MAY call cloud services? | AGENTS.md §7 |
| C4 | What data must NEVER leave the machine? | AGENTS.md §7 |
| C5 | Which file paths must NEVER be modified by automated tools? | PROBLEMS.md §3 |

### D. Agent Workflow
| # | Question | Maps To |
|---|----------|---------|
| D1 | Which tasks can small local models do? Which require large models? | AGENTS.md §3 |
| D2 | Which tasks require human approval before execution? | AGENTS.md §3 |
| D3 | What context should EACH subagent type receive? | AGENTS.md §4 |
| D4 | What should a subagent NEVER be allowed to do? | AGENTS.md §7, PROBLEMS.md §2 |

### E. Interface Habits
| # | Question | Maps To |
|---|----------|---------|
| E1 | What CLI style should ALL tools follow? | INTERFACES.md §1 |
| E2 | What config format should be stable? | INTERFACES.md §3 |
| E3 | How should backward compatibility be handled? | INTERFACES.md §6 |
| E4 | What is the contract for version bumps? | INTERFACES.md §4 |

### F. Testing and Release
| # | Question | Maps To |
|---|----------|---------|
| F1 | What tests are mandatory before ANY commit? | AGENTS.md §5 |
| F2 | What tests are mandatory before a release? | AGENTS.md §6 |
| F3 | What should BLOCK a release (even if all tests pass)? | AGENTS.md §6 |
| F4 | What is the rollback process for a bad release? | AGENTS.md §6 |

### G. Long-Term Requirements
| # | Question | Maps To |
|---|----------|---------|
| G1 | What MUST exist in 3 months? In 1 year? | LONGTODO.md §2 |
| G2 | What is nice-to-have but NOT core? | LONGTODO.md §4 |
| G3 | What should be explicitly POSTPONED? | LONGTODO.md §4 |
| G4 | What would make this project a FAILURE? A SUCCESS? | LONGTODO.md §0 |
| G5 | What are the top 3 risks to the project's long-term viability? | LONGTODO.md §2 |

### H. Existing Problems and Pain Points
| # | Question | Maps To |
|---|----------|---------|
| H1 | What bugs or limitations do you keep running into but haven't fixed? | PROBLEMS.md §1 |
| H2 | What patterns have caused the most regressions? | PROBLEMS.md §2 |
| H3 | What parts of the codebase do you dread changing? Why? | PROBLEMS.md §3 |
| H4 | What "temporary" workarounds have become permanent? | PROBLEMS.md §1 |
| H5 | What would you tell a new contributor to NEVER do? | PROBLEMS.md §2 |

## Output Template

```markdown
## Grill-Me Session: YYYY-MM-DD

### Answers → AGENTS.md
- Section X: [new/updated content]

### Answers → PROBLEMS.md
- New Ban BAN-00X: [derived from Q-H5]
- New Active Problem PROB-00X: [derived from Q-H1]

### Answers → LONGTODO.md
- New Requirement REQ-00X: [derived from Q-G1]

### Answers → INTERFACES.md
- New IFACE-CHANGE-00X: [derived from Q-E3]

### Unresolved / Needs Follow-up
- Q-X: [why unresolved, what's needed]
```

## Post-Interview Checklist
- [ ] All AGENTS.md sections reviewed and updated
- [ ] All new problems documented in PROBLEMS.md
- [ ] All new long-term requirements in LONGTODO.md
- [ ] All interface changes in INTERFACES.md
- [ ] No vague answers left un-followed-up
- [ ] Output files are concise, stable, directly usable by future agents
