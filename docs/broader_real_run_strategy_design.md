# Broader DeepSeek Real-Run Strategy — Design Packet

**Status**: Design (2026-06-13). No implementation yet.
**Prerequisite**: Flash smoke test complete (transport + semantic PASS after v2 params).
**Next step**: Flash limited real-run implementation skeleton (Stage 2).

---

## 1. Real-Run Tier Definitions

| Tier | Scope | Trigger | Status |
|------|-------|---------|--------|
| **Smoke real-run** | Fixed prompt, API availability only | `--allow-live-smoke` | ✅ Complete (3 runs) |
| **Limited real-run** | Small input, manual trigger, privacy safe, low risk, Flash only | TBD (Stage 2-4) | ⬜ Designed below |
| **General real-run** | Arbitrary tasks, automated routing | Not in scope | 🚫 NOT allowed in current phase |
| **Pro real-run** | High-risk review, arbitration | After Pro smoke | 🚫 Blocked until Pro smoke passes |

**Current phase ceiling**: Limited real-run design only. General real-run and Pro
real-run are out of scope until their respective gates are passed.

---

## 2. Task Classification

| Class | Definition | Cloud Action | Model |
|-------|-----------|-------------|-------|
| **local-only** | Default: all tasks unless explicitly escalated | Execute locally | Local Ollama models |
| **flash-limited** | Small, non-sensitive, low-risk, manually triggered | May use Flash after gates | deepseek-v4-flash |
| **pro-review** | Release, security, interface, API boundary, schema, irreversible | Design review only (no real-run yet) | deepseek-v4-pro (design phase) |
| **cloud-blocked** | Secrets, .env, keys, full repo, private data | Never to any cloud model | N/A |

### flash-limited allowed tasks (v1)

```
- Short plain-text explanation (max 4000 chars input)
- Non-sensitive documentation summary
- Small test plan generation from manually pasted requirements
- Small error explanation from non-secret command output
- Short manually-pasted code snippet explanation (no full file)
```

### flash-limited forbidden tasks

```
- Full repository or directory content
- Complete git diff
- .env / credential / key / secret files
- Private data or user privacy content
- Release gate or production deployment
- Security review or vulnerability analysis
- Interface-breaking review
- Database migration or DDL
- Auto-fix or auto-commit
- Auto-run worker or recursive context collection
```

### pro-review tasks (design only, no real-run)

```
- Release preparation
- Security audit
- Interface change review
- API execution boundary changes
- Schema migration
- Provider configuration changes
- Irreversible actions
- Flash vs Local conflict arbitration
```

### cloud-blocked (permanent)

```
- API keys, tokens, passwords
- .env files and contents
- Private keys (RSA, EC, OpenSSH, PGP)
- Full repository dumps
- Credential files (credentials.json, secrets.yaml)
- User privacy data
- Un-redacted logs
- Any content matching privacy_gate critical/high rules
```

---

## 3. Gate Sequence (Limited Real-Run)

Every limited real-run call MUST pass all gates in order:

```
[1]  Manual user confirmation (--manual-confirm or equivalent)
[2]  cloud_ok = true
[3]  real_run = true
[4]  Model in allowlist (Flash only for limited real-run)
[5]  Router classification (not unknown, not defer)
[6]  privacy_gate: status = safe (needs_review = block in v1)
[7]  budget_gate: budget set, price known, budget not exceeded
[8]  cost_ledger: pre_call_estimate recorded
[9]  Context size limit enforced (max 4000 chars input)
[10] API key lookup (os.environ, after all gates)
[11] deepseek_client.call_deepseek()
[12] Response redaction
[13] cost_ledger: post_call record
[14] Response return to user
```

Any gate failure → abort. No partial bypass.

---

## 4. Context Limits (v1)

| Constraint | Value |
|-----------|-------|
| max input tokens | 4000 |
| max output tokens | 1024 |
| max input chars | ~12000 |
| automatic file collection | FORBIDDEN |
| recursive context | FORBIDDEN |
| full repo | FORBIDDEN |
| binary files | FORBIDDEN |
| hidden files (.env, .git) | FORBIDDEN |
| .local_llm_out contents | FORBIDDEN |

All context must be explicitly provided by the user. No automatic scanning or
collection of files, directories, or environment.

---

## 5. Budget Strategy (v1)

### Per-call limits (Flash limited real-run)

| Limit | Value |
|------|-------|
| per-call max cost | 0.50 CNY |
| daily max cost | 5.00 CNY |
| monthly max cost | User-configured (default: 50 CNY) |
| unknown price | HARD BLOCK |
| budget exceeded | HARD BLOCK |
| budget not set | HARD BLOCK |

### Model pricing (current configurable defaults)

| Model | Input CNY/1M tokens | Output CNY/1M tokens |
|-------|---------------------|---------------------|
| deepseek-v4-flash | 1.0 | 2.0 |
| deepseek-v4-pro | 4.0 | 8.0 (blocked) |

### Budget enforcement

- Per-call budget checked via `cost_ledger.estimate()` before API call
- Daily budget tracked via cost_ledger records for current day
- Monthly budget tracked via cost_ledger records for current month
- All three checks must pass

---

## 6. Ledger Events

| event_type | When |
|------------|------|
| `pre_call_estimate` | Before API call, after gates pass |
| `blocked_call` | Any gate blocks before API call |
| `flash_limited_call_attempted` | Flash API call initiated |
| `flash_limited_call_success` | Flash API returned ok with usage |
| `flash_limited_call_failed` | Flash API returned error |
| `pro_review_attempted` | Pro API call initiated (future) |
| `pro_review_success` | Pro API returned ok (future) |
| `pro_review_failed` | Pro API returned error (future) |

### Forbidden in ledger records

```
- API key value
- Raw secrets, passwords, tokens
- Full prompt text (unless confirmed safe and < 500 chars)
- Full response body
- Complete repo content or diff
- Un-redacted error messages
- reasoning_content raw text
```

---

## 7. Error & Retry Rules

| Trigger | Retry? | Max | Notes |
|---------|--------|-----|-------|
| 400 | No | 0 | Abort, record error |
| 401/403 | No | 0 | Abort, check credentials |
| 429 | Yes | 1 | Wait 5s, single retry |
| 5xx | Yes | 1 | Wait 3s, single retry |
| Timeout (>60s) | Yes | 1 | Wait 5s, single retry |
| Connection error | Yes | 1 | Wait 3s, single retry |
| Privacy gate block | No | 0 | Permanent |
| Budget gate block | No | 0 | Permanent |
| Router unknown/defer | No | 0 | Permanent |

---

## 8. CLI Draft (Design Only, Not Implemented)

```bash
# Limited real-run (Flash, small task):
py -3 tools/deepseek_execution_adapter.py \
    --task "summarize this non-sensitive text" \
    --model deepseek-v4-flash \
    --input-text "paste safe content here" \
    --max-input-tokens 4000 \
    --max-output-tokens 1024 \
    --budget 0.5 \
    --cloud-ok \
    --real-run \
    --manual-confirm \
    --json
```

**Not yet runnable** — broader adapter not implemented.

---

## 9. Pilot Sequence

| Pilot | Task | Model | Budget | Gates |
|-------|------|-------|--------|-------|
| P1 | Fixed non-sensitive plain text summary | Flash | 0.5 CNY | All gates |
| P2 | Small test plan from manually pasted requirements | Flash | 0.5 CNY | All gates |
| P3 | Local vs Flash comparison on explanation task | Flash | 0.5 CNY | All gates |
| P4 | Pro smoke design | N/A | Design only | Design audit |

Each pilot must:
- Be manually triggered
- Have small, fixed budget
- Be privacy-safe (verified by privacy_gate)
- Not upload repo, diff, or files
- Be stoppable at any point
- Record full ledger events
- Be completed and audited before next pilot

---

## 10. Pro Real-Run Status

```
CURRENTLY BLOCKED.
Pro real-run requires:
  1. Pro smoke test design packet
  2. Pro smoke test skeleton implementation
  3. Pro smoke test convergence audit
  4. Single Pro smoke test (manual, fixed prompt, Flash-comparable)
  5. Pro smoke PASS (transport + semantic)
  6. Separate strategy review for Pro usage

Pro is NOT available for any real-run until all 6 steps complete.
```

---

## 11. Block Conditions (Immediate Stop)

Any of the following triggers immediate halt of broader real-run:

```
- privacy_bypass_count > 0
- false_cloud_on_secret_count > 0
- unknown_price enters real call path
- budget exceeded enters real call path
- API key appears in any output, log, or ledger
- Raw secret/credential appears in prompt or ledger
- Response or error not redacted
- Router unknown task enters real call
- Pro real-run attempted before Pro smoke passes
- Automatic file collection occurs
- Worker auto-execution occurs
- Stop hook or auto real-run hook connected
```

---

## 12. Implementation Roadmap

```
Stage 0: ✅ Smoke tests complete (transport + semantic PASS)
Stage 1: ✅ Broader real-run strategy design (this document)
Stage 2: ⬜ Flash limited real-run implementation skeleton
Stage 3: ⬜ Flash limited convergence audit
Stage 4: ⬜ P1: First limited non-sensitive Flash real-run pilot
Stage 5: ⬜ Pro smoke design packet
Stage 6: ⬜ Pro smoke skeleton
Stage 7: ⬜ Single Pro smoke test
Stage 8: ⬜ Real-run policy review
```

No stage may be skipped. No automation may be introduced before Stage 8.

---

## 13. Current Limitations (Noted, Not Fixed)

| Limitation | Impact | Resolution |
|-----------|--------|------------|
| temperature param not in client | Can't set temperature=0 | Separate client parameter support task |
| Pro real-run blocked | No high-risk cloud review | Pro smoke design → skeleton → smoke test |
| No daily budget tracking in cost_ledger | Can't enforce daily cap | cost_ledger daily-summary feature |
| Flash reasoning tokens consume budget | Higher-than-expected token usage | max_tokens=128 minimum, monitor in pilots |

---

*Design packet completed 2026-06-13. No implementation. No API calls.*
