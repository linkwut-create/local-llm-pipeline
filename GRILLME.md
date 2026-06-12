# GRILLME.md

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
7. Do not let the interviewee skip questions. "I don't know" is acceptable; silence is not.

---

## Question Groups

### A. Project Identity

| # | Question | Maps To |
|---|----------|---------|
| A1 | This project is mainly for: yourself, a team, users, developers, or commercial use? | AGENTS.md §0 |
| A2 | What is the ONE thing this project must do better than any existing alternative? | AGENTS.md §0 |
| A3 | What should this project NEVER become? (3-5 hard prohibitions) | AGENTS.md §1, LONGTODO.md §1 |
| A4 | What is acceptable complexity, and what is unacceptable complexity? | AGENTS.md §1 |
| A5 | If this project had to be handed off to another developer tomorrow, what 3 things must they understand first? | AGENTS.md §0 |

### B. Design Philosophy

| # | Question | Maps To |
|---|----------|---------|
| B1 | Rank these priorities: local-first, speed, quality, cost, extensibility, UI polish | AGENTS.md §1 |
| B2 | When trade-offs happen, what ALWAYS wins? Give 3 concrete examples. | AGENTS.md §1 |
| B3 | Should the system prefer explicit configuration or automatic behavior? | AGENTS.md §1 |
| B4 | Should failures be loud (crash/block) or silent (warn/continue)? Give contexts. | AGENTS.md §1, PROBLEMS.md §3 |
| B5 | Should the system optimize for expert users or ordinary users? | AGENTS.md §1 |
| B6 | What are 3 design decisions you've made that you would defend even if others disagree? | AGENTS.md §1 |

### C. Technical Boundaries

| # | Question | Maps To |
|---|----------|---------|
| C1 | Which dependencies are ALWAYS allowed? Which require explicit approval? | AGENTS.md §7 |
| C2 | Which dependencies are FORBIDDEN unless there's an exceptional reason? | AGENTS.md §7, PROBLEMS.md §2 |
| C3 | What parts MUST stay local? What parts MAY call cloud services? | AGENTS.md §7 |
| C4 | What data must NEVER leave the machine? | AGENTS.md §7 |
| C5 | What is the maximum acceptable latency for a local model call? | INTERFACES.md §5 |
| C6 | What is the maximum acceptable model size? | AGENTS.md §1 |
| C7 | Which file paths must NEVER be modified by automated tools? | PROBLEMS.md §3 |

### D. Agent Workflow

| # | Question | Maps To |
|---|----------|---------|
| D1 | Which tasks can small local models do? Which require large models? | AGENTS.md §3 |
| D2 | Which tasks require human approval before execution? | AGENTS.md §3 |
| D3 | When should subagents be used instead of a single agent? | AGENTS.md §3, §4 |
| D4 | What context should EACH subagent type receive? (planner, coder, tester, reviewer, interface, docs) | AGENTS.md §4 |
| D5 | What is the maximum context size per subagent? | AGENTS.md §4 |
| D6 | What should a subagent NEVER be allowed to do? | AGENTS.md §7, PROBLEMS.md §2 |
| D7 | How should subagent outputs be validated by the controller? | AGENTS.md §5 |

### E. Interface Habits

| # | Question | Maps To |
|---|----------|---------|
| E1 | What CLI style should ALL tools follow? (flags, exit codes, output format) | INTERFACES.md §1, §2 |
| E2 | What config format should be stable? What can change? | INTERFACES.md §3 |
| E3 | What should the standard error response shape be? | INTERFACES.md §1 |
| E4 | How should backward compatibility be handled? (deprecation period, migration path) | INTERFACES.md §7 |
| E5 | What MCP tool output fields are REQUIRED across all tools? | INTERFACES.md §1 |
| E6 | What is the contract for version bumps? | INTERFACES.md §4 (VERSION) |
| E7 | What CLI subcommands/flags must never be removed? | INTERFACES.md §2 |

### F. Testing and Release

| # | Question | Maps To |
|---|----------|---------|
| F1 | What tests are mandatory before ANY commit? | AGENTS.md §5, §6 |
| F2 | What tests are mandatory before a release? | AGENTS.md §5, §6 |
| F3 | What is the minimum acceptable test pass rate? (100%? 99%?) | AGENTS.md §6 |
| F4 | When is a version allowed to be tagged? | AGENTS.md §6 |
| F5 | What should BLOCK a release (even if all tests pass)? | AGENTS.md §6, PROBLEMS.md §3 |
| F6 | How should release notes be structured? | AGENTS.md §6 |
| F7 | What is the rollback process for a bad release? | AGENTS.md §6 |

### G. Long-Term Requirements

| # | Question | Maps To |
|---|----------|---------|
| G1 | What MUST exist in 3 months? | LONGTODO.md §2 |
| G2 | What MUST exist in 1 year? | LONGTODO.md §2 |
| G3 | What is nice-to-have but NOT core? | LONGTODO.md §4 |
| G4 | What should be explicitly POSTPONED? | LONGTODO.md §4 |
| G5 | What would make this project a FAILURE? (3-5 failure conditions) | LONGTODO.md §0 |
| G6 | What would make this project a SUCCESS? (3-5 measurable success criteria) | LONGTODO.md §0 |
| G7 | What are the top 3 risks to the project's long-term viability? | LONGTODO.md §2 |

### H. Existing Problems and Pain Points

| # | Question | Maps To |
|---|----------|---------|
| H1 | What bugs or limitations do you keep running into but haven't fixed? | PROBLEMS.md §1 |
| H2 | What patterns have caused the most regressions? | PROBLEMS.md §2 |
| H3 | What parts of the codebase do you dread changing? Why? | PROBLEMS.md §3 |
| H4 | What "temporary" workarounds have become permanent? | PROBLEMS.md §1 |
| H5 | What mistakes have you made more than once? | PROBLEMS.md §2 |
| H6 | What would you tell a new contributor to NEVER do? | PROBLEMS.md §2 |

---

## Output Template

After the interview, produce updates in this format:

```markdown
## Grill-Me Session: YYYY-MM-DD

### Answers → AGENTS.md
- Section X: [new/updated content based on answer to Q-A3]

### Answers → PROBLEMS.md
- New Ban BAN-00X: [derived from Q-H5]
- New Active Problem PROB-00X: [derived from Q-H1]

### Answers → LONGTODO.md
- New Requirement REQ-00X: [derived from Q-G1]
- New Deferred Idea: [derived from Q-G4]

### Answers → INTERFACES.md
- New IFACE-CHANGE-00X: [derived from Q-E4]

### Unresolved / Needs Follow-up
- Q-X: [why unresolved, what's needed]
```

---

## Post-Interview Checklist

- [ ] All AGENTS.md sections reviewed and updated
- [ ] All new problems documented in PROBLEMS.md
- [ ] All new long-term requirements in LONGTODO.md
- [ ] All interface changes in INTERFACES.md
- [ ] No vague answers left un-followed-up
- [ ] No contradictions between different answers
- [ ] All "I don't know" answers tagged for future resolution
- [ ] Output files are concise, stable, directly usable by future agents
