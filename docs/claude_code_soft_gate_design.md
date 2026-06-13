# Claude Code Soft Gate Integration — Design Packet

**Status**: Design (2026-06-13). No implementation yet.
**Phase**: Claude Code governance integration, Stage A (soft gate only).

---

## 1. Gate Tier Definitions

| Tier | Behavior | Blocks? | Current Status |
|------|----------|---------|----------------|
| **Advisory tool** | User/Claude Code can invoke | No | ✅ Implemented (all tools) |
| **Soft gate** | Invoked by default at key points; output advisory only | No | ⬜ This design |
| **Warning gate** | Strong notice on high risk; requires awareness | No (warn) | ⬜ Stage B |
| **Manual-confirm gate** | High-risk requires explicit human confirmation | Soft block | ⬜ Stage C |
| **Hard block** | Secret / .env / private key / credential dump | Yes | ⬜ Stage D |

**This design covers soft gate only.** No blocking behavior is implemented.

---

## 2. Integration Points

Soft gate triggers at these Claude Code workflow points:

### Pre-Task Gate

```bash
# Before starting a substantial task:
py -3 tools/advisory_workflow.py --task "<task>" --cloud-ok
```

Triggers when:
- User describes a new non-trivial task
- Task involves multiple files or modules
- Task mentions cloud, API, release, security, or interface keywords

### Pre-Commit Gate

```bash
# Before commit:
py -3 tools/precommit_advisory.py --cloud-ok
```

Triggers before every commit. Already in use — always exits 0.

### Pre-Cloud Gate

```bash
# Before any cloud model call:
py -3 tools/deepseek_dry_run.py --task "<task>" --model deepseek-v4-flash \
    --input-tokens <N> --output-tokens <N> --budget <N> --cloud-ok
```

Triggers when Claude Code considers calling DeepSeek or any cloud model.

### First gate scope (v1)

| Point | Tool | Mandatory? |
|-------|------|------------|
| Task start | `advisory_workflow` | Recommended |
| Pre-commit | `precommit_advisory` | Yes (already) |
| Pre-cloud | `deepseek_dry_run` | Conditional |
| Large file edit | `local_summarize_file` | Already in CLAUDE.md |

---

## 3. Input Minimization

Soft gate MUST NOT auto-collect repository contents.

### Allowed inputs (v1)

```
- Task description (user-provided text)
- Diff summary (--stat only, not full diff)
- File path list (names only, not contents)
- Estimated token counts
- Explicit budget amount
```

### Forbidden inputs

```
- Full repository contents
- Complete diff text
- .env files
- .local_llm_out contents
- Hidden files
- Binary files
- Credential files
- Large log files
- User data or private content
```

---

## 4. Output Schema

Soft gate output must be short, stable, and machine-readable by Claude Code.

```json
{
  "decision": "allow | warn | defer | cloud_blocked | manual_confirm_recommended",
  "task_type": "<router classification>",
  "risk_level": "low | medium | high | critical",
  "privacy_status": "safe | needs_review | blocked",
  "budget_status": "ok | exceeded | unknown | not_set",
  "recommended_route": "local | local-first | flash-limited | pro-review | cloud-blocked",
  "reason": "<one-line explanation>",
  "next_required_action": "<what the user should do next, if anything>",
  "advisory_only": true
}
```

### Decision semantics

| decision | Meaning |
|----------|---------|
| `allow` | Safe to proceed with local execution |
| `warn` | Proceed but note risk; cloud escalation may need review |
| `defer` | Insufficient information; provide more task context |
| `cloud_blocked` | Privacy gate blocks cloud transmission; use local only |
| `manual_confirm_recommended` | High risk; human should explicitly confirm |

**Soft gate NEVER returns "block"**. Even `cloud_blocked` is advisory — it
recommends against cloud use but does not prevent local execution.

---

## 5. Severity Color Coding

| Color | Risk | Example | Soft gate response |
|-------|------|---------|--------------------|
| Green | Low | docs update, README edit | `allow`, route=local |
| Yellow | Medium | multi-file feature, diff review | `allow`, route=local-first or flash-limited |
| Orange | High | release gate, security, interface change | `warn`, route=pro-review, manual_confirm_recommended |
| Red | Blocked | .env, secret, credential, full repo | `cloud_blocked`, route=cloud-blocked |

In soft gate mode, even Red only produces `cloud_blocked` advisory — no hard block.

---

## 6. Relationship to Existing Tools

| Tool | Role in soft gate |
|------|-------------------|
| `router_explain.py` | Task classification + risk grading |
| `privacy_gate.py` | Privacy/secret detection (advisory) |
| `cost_ledger.py` | Budget status (ok/exceeded/unknown) |
| `deepseek_dry_run.py` | Pre-cloud governance plan |
| `advisory_workflow.py` | Pre-task soft gate engine |
| `precommit_advisory.py` | Pre-commit soft gate (already in use) |
| `shadow_route_log.py` | Dogfood recording |
| `shadow_route_report.py` | Periodic accuracy reporting |
| `deepseek_execution_adapter.py` | Real-run boundary (NOT triggered by soft gate) |

Soft gate composes these tools without adding new execution capability.

---

## 7. Dogfood Protocol

Formalized dogfood rules for every real task:

### Task start

```bash
py -3 tools/advisory_workflow.py --task "<task>" --cloud-ok
py -3 tools/shadow_route_log.py "<task>" --actual "<decision>"
```

### Pre-commit

```bash
py -3 tools/precommit_advisory.py --cloud-ok
py -3 tools/shadow_route_log.py "precommit review for <feature>" --actual "<decision>"
```

### Periodic review

```bash
py -3 tools/shadow_route_report.py --since 2026-06-13 --json
```

### Actual decision enum (fixed)

```
local
local-first
flash-fallback
pro-review
cloud-blocked
defer
```

---

## 8. CLAUDE.md Integration Draft

Proposed addition to CLAUDE.md (not auto-applied):

```markdown
## Soft Gate Protocol

Before any non-trivial task, run:

```bash
py -3 tools/advisory_workflow.py --task "<task>" --cloud-ok
```

Before every commit:

```bash
py -3 tools/precommit_advisory.py --cloud-ok
```

Before any cloud model call:

```bash
py -3 tools/deepseek_dry_run.py --task "<task>" \
    --model deepseek-v4-flash \
    --input-tokens <N> --output-tokens <N> \
    --budget <N> --cloud-ok
```

Record routing decisions:

```bash
py -3 tools/shadow_route_log.py "<task>" --actual "<decision>"
```

Periodic review:

```bash
py -3 tools/shadow_route_report.py --since 2026-06-13 --json
```
```

---

## 9. Upgrade Criteria (Soft Gate → Warning Gate)

| Criterion | Threshold |
|-----------|-----------|
| Soft gate dogfood records | >= 30 labeled records beyond current 150+ |
| privacy_bypass_count | 0 |
| false_cloud_on_secret_count | 0 |
| new critical_misrouting | 0 (existing 2 are pre-calibration) |
| pro-review capture rate | release/security/interface tasks: >= 90% |
| cloud_blocked accuracy | .env/secret/credential: 100% blocked |
| User noise tolerance | Confirmed acceptable |

No upgrade before all criteria met.

---

## 10. Explicitly Paused Items

```
- Broader DeepSeek real-run implementation
- Flash limited real pilot
- Pro smoke chain
- Stop hook integration
- Hard block (selective or full)
- llm-proxy
- Automatic worker execution
- Automatic context collection
- Automatic DeepSeek call routing
- PreToolUse / PostToolUse hooks
- Commit blocking
```

These remain paused until soft gate design is implemented and audited, AND the
upgrade criteria above are met.

---

*Design packet completed 2026-06-13. No code changes. No hooks.*
