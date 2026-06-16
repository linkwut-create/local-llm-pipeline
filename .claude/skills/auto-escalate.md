# Auto-Escalate Skill

Automatically switch Claude Code models between execution phases based on
a structured execution plan from `draft_execution_plan.py`.

## Trigger

```
/auto-escalate <task description>
```

Or invoked programmatically when a multi-phase task is detected.

## Workflow

### Step 1: Draft plan with best model

Switch to Pro and generate the execution plan:

```
/model claude-sonnet-4-6   (or deepseek-v4-pro when real-run enabled)
```

Actually, the plan is drafted by `draft_execution_plan.py` which uses heuristic
templates + the RouterEngine. The "best model" is only needed when `--real-run`
is enabled (Phase D).

```bash
py -3 tools/draft_execution_plan.py "<task>" --json > .local_llm_out/current_plan.json
```

### Step 2: Review and confirm plan

Controller (Claude Code) reviews the plan and confirms phase order and model
assignments. The plan is **advisory** — controller may adjust.

### Step 3: Execute each phase with model switching

For each phase in the plan:

```
1. Read phase:  /model <recommended_model>
2. Execute:     <phase description>
3. Verify:      Check phase output
4. Next phase
```

### Step 4: Completion report

After all phases complete, generate a summary:
- Phases executed: N
- Models used: list
- Estimated vs actual cost: comparison
- Recommendations for next session

## Model Switching Contract

Models are resolved from `tools/local_llm_profiles.json`, never hardcoded.
The route type determines the model tier:

| Route | Profile Key | Purpose |
|-------|------------|---------|
| `claude_code_pro` | `deepseek_v4_pro_*` | High-stakes planning, code modification, security review |
| `flash_subagent` | `deepseek_v4_flash_*` | Review, test planning, analysis (moderate cost) |
| `flash_direct` | `deepseek_v4_flash_*` | Summarization, translation, docs (cheap, no overhead) |
| `local_only` | local profiles | Free, default for non-critical work |

**Local fallback**: When cloud is unavailable or budget exhausted, phases
route to local profiles instead (resolved from the same profiles config).

To determine the model for a phase:
```bash
py -3 tools/draft_execution_plan.py "<task>" --json | py -3 -c \
  "import json,sys; d=json.load(sys.stdin); [print(f'{p[\"name\"]}: /model {p[\"recommended_model\"]}') for p in d['phases']]"
```

## Budget Guard

Before each cloud phase, check:

```bash
py -3 tools/cost_ledger.py --budget 10 --summary
```

If budget exceeded, fall back to local models for remaining phases.

## Safety Checks

- privacy_gate.py runs before any cloud call
- cost_ledger.py records every cloud call
- shadow_route_log.py records the actual routing decision
