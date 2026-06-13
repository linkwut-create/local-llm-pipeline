# External Project Dogfood Protocol

How to use the local-llm-pipeline soft gate and dogfood tools in external
projects (local-translator-agent, Google Play management, browser-plugin,
game-dev, etc.).

## Core Principle

The governance layer (soft gate, shadow route, privacy gate, cost ledger)
is project-agnostic. It classifies tasks by description and risk signals,
not by which repo you're in. External projects benefit from the same
safety invariants without modifying the control layer.

## Quick Start

```bash
# From any project root, run soft gate pre-task:
py -3 ../local-llm-pipeline/tools/claude_soft_gate.py \
    --stage pre-task --task "<task>" --json

# Record routing decision:
py -3 ../local-llm-pipeline/tools/shadow_route_log.py \
    "<task>" --actual "<decision>"

# Pre-commit advisory before commit:
py -3 ../local-llm-pipeline/tools/precommit_advisory.py --cloud-ok
```

## Actual Labeling Rule

Apply the same rules as internal dogfood:

| Condition | Actual |
|-----------|--------|
| `router_risk_level == "high"` | `pro-review` |
| `decision == "manual_confirm_recommended"` | `pro-review` |
| `task_type ∈ {governance-integration, release-risk-review, …}` | `pro-review` |
| Low/medium tests, docs, ordinary maintenance | `local-first` |

The actual label describes governance treatment level, not whether a cloud
call was made.

## Hard Constraints

- **Never** write external repo file contents into shadow route log.
- **Never** upload secrets, `.env`, credentials, or API keys.
- **Never** call DeepSeek for external project tasks unless explicitly
  authorized via separate design review.
- **Never** edit external source files via local models without controller
  approval.

## Privacy Gate for External Tasks

When a task touches external project files, run privacy gate on the task
description (not the file contents):

```bash
py -3 ../local-llm-pipeline/tools/privacy_gate.py --text "<task>"
```

If the task mentions file paths, check those paths:

```bash
py -3 ../local-llm-pipeline/tools/privacy_gate.py --path "<relative-path>"
```

## Cost Ledger

Cost ledger entries for external projects should use the project name as a
prefix in the task field. This allows per-project cost aggregation without
modifying the ledger schema.

## Dogfood Checkpoints

Same checkpoint protocol applies. Each external project task is a separate
dogfood record. Checkpoints report total critical_misrouting and new
critical_misrouting separately.

## Supported Project Types

See [external dogfood scenarios](external_dogfood_scenarios.md) for
specific examples.
