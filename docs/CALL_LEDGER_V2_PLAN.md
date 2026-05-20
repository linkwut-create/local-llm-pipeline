# Call Ledger v2 — Real Provider Usage Passthrough · Plan

**Status**: planning only. No code changes; no signature changes; no schema changes.
Implementation gated on user approval of this document.

**Parent commit**: `bf83f11 feat: add call ledger audit for local LLM invocations` (v1).

---

## 1. Phasing

The v2 work is **explicitly split into three phases**. Each phase is small enough
to land as a single reviewable diff with a focused commit_gate review.

| Phase | Scope | Status |
|---|---|---|
| **v2-A** | Non-stream real provider usage passthrough | **planned (this document)** |
| **v2-B** | Streaming usage passthrough | deferred — separate plan |
| **v2-C** | DeepSeek cache-tier cost estimation / cost table expansion | deferred — separate plan |

**This plan covers v2-A only.** v2-B and v2-C are sketched in §6 / §7 for
direction, not implementation.

The split exists to keep blast radius small and review focused. v1 was committed
under exactly this discipline; v2 follows the same rule.

---

## 2. v1 starting point and current call chain

v1 records tokens via `chars // 4` with `tokens_estimated: true`. The worker
call chain today:

```
_run_inner
  └─ call_model_with_retry(system, user, config, task) -> (str, error_info)
       └─ call_model(system, user, config) -> str       ← local_llm_debate.py:188
            ├─ call_ollama         (POST /api/chat,            stream=false)
            ├─ call_openai_compat  (POST /chat/completions,    stream=false)
            └─ call_model_stream(...) -> Generator[str]
                 ├─ call_ollama_stream         (NDJSON)
                 └─ call_openai_compat_stream  (SSE)
```

External callers of `call_model` outside the worker: **exactly one** —
`tools/local_llm_debate.py:188` `raw = call_model(system, user, config)`.

All five `call_*` functions currently discard the provider's `usage` block.

---

## 3. v2-A — Non-stream real provider usage passthrough

### 3.1 Scope — in

| Item | Touched file | Nature |
|---|---|---|
| New `ModelCallResult` dataclass | `tools/local_llm_worker.py` (or new `tools/model_call_result.py`) | New type |
| New `normalize_usage(provider, data)` | same module as above | New pure function |
| `call_ollama` returns `ModelCallResult` | `tools/local_llm_worker.py` | Signature change |
| `call_openai_compat` returns `ModelCallResult` | `tools/local_llm_worker.py` | Signature change |
| `call_model` returns `ModelCallResult` (non-stream path) | `tools/local_llm_worker.py` | Signature change |
| `call_model_with_retry` returns `(ModelCallResult \| None, error_info)` | `tools/local_llm_worker.py` | Signature change |
| Worker `_run_inner` uses `result.content` / `result.usage` | `tools/local_llm_worker.py` | Internal adaptation |
| Worker `_emit_ledger` accepts and forwards usage | `tools/local_llm_worker.py` | Internal adaptation |
| `local_llm_debate.py:188` → `.content` | `tools/local_llm_debate.py` | One-line attribute access |
| Map DeepSeek `prompt_cache_hit_tokens / prompt_cache_miss_tokens` if present | `normalize_usage` | Pass-through only |
| Ledger prefers real usage; falls back to `chars // 4` if `usage is None` | `tools/call_ledger.py` (minor) or worker call site | Wiring |

### 3.2 Scope — out (explicit non-goals of v2-A)

- **Do not modify** `call_ollama_stream`.
- **Do not modify** `call_openai_compat_stream`.
- **Do not modify** `call_model_stream`.
- **Do not introduce** `Generator[str | ModelCallResult]` or any mixed-yield
  generator.
- **Do not add** `stream_options={"include_usage": true}` to any request.
- **Do not build** cache-tier (3-rate) cost estimation. DeepSeek
  `cached_tokens` is recorded but cost continues to use `in_per_1k / out_per_1k`
  as in v1 — accept this as a known approximation until v2-C.
- **Do not introduce** any thread-local, contextvar, or `config.last_usage`
  side-channel for carrying usage out of the call functions.
- **Do not extend** ledger to capture Codex / Claude / external direct DeepSeek
  API calls. Scope of the ledger remains "calls through `local_llm_worker.py`".
- **Do not introduce** SQLite, Context Budget docs, or cross-project aggregation
  tooling.

### 3.3 `ModelCallResult` design

```python
@dataclass
class ModelCallResult:
    content: str
    usage: dict | None         # normalized usage; None if provider didn't report
    raw_provider: str | None   # 'ollama' | 'openai-compatible'
```

`content` is always populated (may be empty string on a degenerate response).
`usage` is `None` when the provider response did not contain a usage block, or
when normalization failed. Normalized `usage` schema:

```python
{
    "input_tokens": int,            # required when usage is not None
    "output_tokens": int,           # required when usage is not None
    "total_tokens": int,            # required when usage is not None
    "cached_tokens": int | None,    # DeepSeek prompt_cache_hit_tokens; else None
    "cache_miss_tokens": int | None,# DeepSeek prompt_cache_miss_tokens; else None
    "provider_raw": dict,           # untouched original usage block, for forensics
}
```

`provider_raw` exists so future vendor-specific fields are preserved without
schema churn. v2-A does not consume `provider_raw` itself; ledger ignores it.

`ModelCallResult` represents **successful call completion**. Failures continue
to flow as exceptions caught by `call_model_with_retry`, which returns
`(None, error_info)` instead of `(ModelCallResult, error_info)` on failure.
This keeps the success type free of error-shaped variants.

### 3.4 `normalize_usage(provider, data)`

Single entry point for vendor → normalized mapping. Pure function, no IO.
Never raises; returns `None` on any error or absent usage block.

**Ollama** (`/api/chat`, non-stream — usage fields sit at top level of `data`):

```python
{
  "input_tokens":    data["prompt_eval_count"],
  "output_tokens":   data["eval_count"],
  "total_tokens":    data["prompt_eval_count"] + data["eval_count"],
  "cached_tokens":   None,
  "cache_miss_tokens": None,
  "provider_raw":    {k: data[k] for k in (
        "prompt_eval_count","eval_count",
        "prompt_eval_duration","eval_duration","total_duration") if k in data},
}
```

**OpenAI-compatible** (`/chat/completions`, non-stream — usage inside `usage`):

```python
u = data.get("usage") or {}
{
  "input_tokens":  u.get("prompt_tokens", 0),
  "output_tokens": u.get("completion_tokens", 0),
  "total_tokens":  u.get("total_tokens", 0),
  "cached_tokens":     u.get("prompt_cache_hit_tokens"),    # DeepSeek extra
  "cache_miss_tokens": u.get("prompt_cache_miss_tokens"),   # DeepSeek extra
  "provider_raw":  dict(u),
}
```

`total_tokens` is taken from the provider if present (DeepSeek's
`prompt_tokens` already includes cache-hit tokens, so the sum is consistent).

### 3.5 Function signatures (v2-A — non-stream only)

| Function | v1 signature | v2-A signature | Notes |
|---|---|---|---|
| `call_ollama` | `(system, user, config) -> str` | `-> ModelCallResult` | non-stream only |
| `call_openai_compat` | `(system, user, config) -> str` | `-> ModelCallResult` | non-stream only |
| `call_ollama_stream` | `-> Generator[str]` | **unchanged** | v2-B |
| `call_openai_compat_stream` | `-> Generator[str]` | **unchanged** | v2-B |
| `call_model` (non-stream path) | `-> str` | `-> ModelCallResult` | scheme B: `debate.py` adapts |
| `call_model` (stream path) | `-> Generator[str]` | **unchanged generator** | continues to return generator unchanged |
| `call_model_stream` | `-> Generator[str]` | **unchanged** | v2-B |
| `call_model_with_retry` | `-> (str, dict)` | `-> (ModelCallResult \| None, dict)` | non-stream path only; stream path is not invoked through retry today |

**`call_model` is the only function with a mode-dependent return type.**
Non-stream branch returns `ModelCallResult`; stream branch returns the existing
`Generator[str]`. Callers already check `config.stream` before consuming the
result, so the mixed return type does not leak. If desired we can split into
`call_model_nonstream` + `call_model_stream` later, but v2-A keeps the existing
dispatcher shape to minimize churn.

**Stream path is fully untouched in v2-A** — it continues to yield only `str`,
worker continues to emit ledger with `usage=None`, ledger continues to fall back
to `chars // 4`. v1 streaming behavior is bit-for-bit preserved.

### 3.6 Call sites to adapt

1. **`tools/local_llm_worker.py:1119`** — `raw_result, error_info = call_model_with_retry(...)`
   → `result, error_info = call_model_with_retry(...)`. Downstream:
   `raw_result = result.content if result else ""` for existing code paths; `result.usage` for ledger.
2. **`tools/local_llm_worker.py:566`** — `result = call_model(system, user, config)` inside retry's
   non-stream branch → empty-check on `result.content`.
3. **`tools/local_llm_worker.py:1058+`** — `_emit_ledger` closure gains `usage: dict | None = None` param;
   forwarded to `build_record(input_tokens=..., output_tokens=..., cached_tokens=...)`. The three
   `_emit_ledger` call sites in v1 pass `usage=result.usage` (success / cache hit branches) or
   `usage=None` (failure branch).
4. **`tools/local_llm_worker.py` streaming branch (~line 1107)** — emits `usage=None` to ledger; no behavior change.
5. **`tools/local_llm_debate.py:188`** — `raw = call_model(system, user, config).content`. Scheme B.

Files outside worker / debate are not touched.

### 3.7 Ledger interaction

`tools/call_ledger.py:build_record(...)` already accepts `input_tokens`,
`output_tokens`, `cached_tokens` as explicit keyword args. v2-A wiring:

- Worker passes `input_tokens=usage["input_tokens"]`, etc., when usage is present.
- `build_record` already sets `tokens_estimated=False` automatically when both
  `input_tokens` and `output_tokens` are explicitly provided (existing v1 logic
  at the head of `build_record`). Nothing changes in ledger code structurally.
- One small ledger addition: an optional `cache_miss_tokens: int | None` field
  in the record dict, parallel to existing `cached_tokens`. Schema-additive
  and back-compat. Two test lines.

v1 `cache_hit: bool` semantics are **unchanged**:
- `cache_hit=True` ⇔ worker's local in-process cache hit; no provider call;
  `estimated_cost_cny=0.0`; `usage=None`.
- DeepSeek provider-side KV-cache hit is recorded via `cached_tokens` /
  `cache_miss_tokens` on a record with `cache_hit=False` (we did call the provider).

These two cache concepts are orthogonal and v2-A keeps them clearly separated.

### 3.8 Backward compatibility

| Risk | Mitigation |
|---|---|
| `debate.py` calling `call_model` expects str | Scheme B: one-line change to `.content`. Compat test required (see 3.9.F). |
| Streaming behavior regression | Stream path completely untouched in v2-A. |
| `tokens_estimated` semantics | Preserved. True when usage is None, False when usage present. |
| `cache_hit` semantics | Preserved. v2-A introduces `cached_tokens` / `cache_miss_tokens` separately. |
| `LOCAL_LLM_COST_TABLE` schema | Preserved. Cache-tier rates deferred to v2-C. v2-A continues to use `in_per_1k / out_per_1k` even when `cached_tokens` is present (known approximation). |
| `record_call` JSONL schema | Additive only: new optional `cache_miss_tokens` field. Older readers ignore unknown fields. |
| External callers other than `debate.py` | Grep confirms none. `local_llm_mcp_server.py` imports `is_blocked_path` only. Tests in `tests/` do not call `call_model` / `call_ollama` / `call_openai_compat`. |

### 3.9 Test list (v2-A)

New file `tests/test_model_call_result.py` (or absorb into `tests/test_call_ledger.py`):

**A. `ModelCallResult` dataclass**
- A1: construct with all fields; defaults; `content` is empty-string default if not specified.

**B. `normalize_usage`**
- B1: Ollama complete → all 5 fields populated; `provider_raw` contains 5 keys.
- B2: Ollama missing one of `prompt_eval_count`/`eval_count` → returns None (or zero-filled, decision to nail down at implementation time — recommend returns None so callers handle "partial" as "absent").
- B3: OpenAI-compatible standard `usage` → maps correctly.
- B4: OpenAI-compatible missing `usage` block → returns None.
- B5: DeepSeek-shaped `usage` with cache_hit/miss → `cached_tokens` and `cache_miss_tokens` set.
- B6: malformed input (None, non-dict) → returns None, no raise.
- B7: unknown provider → returns None, no raise.

**C. `call_ollama` / `call_openai_compat` integration** (mock `requests.post`)
- C1: ollama happy path → `content` and `usage` both correct.
- C2: ollama response without usage fields → `usage=None`, `content` intact.
- C3: openai-compat happy path → `content` and `usage` both correct.
- C4: openai-compat with DeepSeek-shaped extras → `cached_tokens` populated.
- C5: HTTP error → exception propagates (caught by `call_model_with_retry`).
- C6: empty content + present usage → still returns ModelCallResult (empty check is downstream).

**D. `call_model_with_retry`**
- D1: happy path → returns `(ModelCallResult, {})` with usage intact.
- D2: empty content triggers retry → on second success, usage is the second-call's usage (not the first).
- D3: all retries fail → returns `(None, error_info)`.
- D4: non-retry task fails once → returns `(None, error_info)`.

**E. Worker integration**
- E1: ollama path → ledger record has `input_tokens/output_tokens` from real usage; `tokens_estimated=False`.
- E2: openai-compat path with cost table → `estimated_cost_cny` computed from real tokens (not chars/4).
- E3: provider returns no usage → fallback to chars/4, `tokens_estimated=True`.
- E4: DeepSeek-shaped response → ledger `cached_tokens` and `cache_miss_tokens` set; `cache_hit=False`; cost uses standard rates (approximation accepted in v2-A).
- E5: local cache hit (v1 behavior) → still `cache_hit=True`, `estimated_cost_cny=0.0`, `usage=None` in record.

**F. `debate.py` compatibility**
- F1: existing debate round produces same `raw_output` and `summary` shape as v1.
- F2: a round with a mocked model returns string content via `.content` access without AttributeError.

**G. Regression — must continue to pass**
- G1: all 55 existing ledger tests pass unchanged.
- G2: full suite ≥ 737 passed.
- G3: streaming behavior unchanged (existing streaming-related tests, if any, pass).

Estimated new tests: **~22-28**, concentrated in B and E.

### 3.10 Review requirements (v2-A)

| Tool | Required? | When |
|---|---|---|
| `local_summarize_file` | Recommended for `local_llm_worker.py` (>200 lines, will be edited) | Before edit |
| `local_generate_test_plan` | **Mandatory** — `normalize_usage` and `ModelCallResult` are new API | On the stub before implementation |
| `local_review_diff` (commit_gate=true) | **Mandatory** — required for commit | Right before commit |
| `local_review_diff` (commit_gate=false, exploratory) | Recommended once, after initial implementation, before final commit_gate | Mid-implementation sanity check |
| `local_debate_review_diff` (fast mode, 2 rounds) | **Recommended, not strictly mandatory** | After exploratory review |
| Re-review on **staged** diff | **Mandatory** by hook | Last step before commit |

Rationale for the "recommended" debate review: v2-A is not in any of the
mandatory-debate categories per CLAUDE.md (not hook/gate/MCP server/router/
safety policy/DB schema/release). But it touches the provider call layer where
small bugs (off-by-one on usage frames, mis-mapped DeepSeek fields) hide easily.
Fast-mode debate costs ~150s and surfaces cross-vendor edge cases.

---

## 4. Why this phasing (rationales the user asked to spell out)

### 4.1 Why streaming usage is deferred to v2-B

1. **Mixed-yield generators are a known foot-gun.** `Generator[str | ModelCallResult]`
   forces every consumer to type-check each yield. Today the consumer is the
   worker; tomorrow if any other code starts consuming the stream, the contract
   has to be re-explained. A separate v2-B can design a cleaner contract
   (e.g., return tuple `(content_generator, lambda: usage)`, or a small
   StreamHandle object), which deserves its own review.

2. **OpenAI-compatible streaming usage requires `stream_options`.** That field
   is broadly supported but not universally. Validating across Ollama,
   llama.cpp server, vLLM, and DeepSeek streaming is a compatibility matrix
   that should be tested deliberately, not bundled.

3. **Streaming is currently a minority code path.** The bulk of pipeline
   calls go through `stream=False`. v2-A captures the 80% case immediately;
   v2-B captures the rest.

4. **v1 streaming behavior is preserved bit-for-bit in v2-A.** Streaming users
   are not regressed — they just continue to get chars/4 estimation until v2-B.

### 4.2 Why not thread-local / `config.last_usage` / contextvar

Side-channel state for "the most recent call's usage" is the kind of design
that works in isolation but breaks subtly when:

- **Streaming and non-stream are interleaved** — which usage block belongs to
  which call?
- **Retries fire** — does `last_usage` carry the failed attempt or the successful one?
- **Cache hits and real calls mix** — which subset of usage values does the
  next code read?
- **Future concurrency** (parallel review, debate orchestration) — thread-locals
  in a process that already has multiple subprocess workers is the worst
  combination: each subprocess thinks its slot is the only one.
- **MCP server invocations are spawned subprocesses** — `contextvar` doesn't
  cross the boundary, so we'd need a serialization path anyway.

Returning usage as a first-class field on the call result eliminates all of
these classes of bug by construction. The cost is one signature change (Scheme
B, one external caller). That cost is accepted once; the side-channel cost
recurs forever.

### 4.3 Why v2-A prioritizes non-stream

Three reasons, in order:

1. **Highest information value per LOC.** Non-stream is where the bulk of the
   pipeline's calls land (summarize, review, debate). Real usage on these calls
   immediately upgrades ledger accuracy for the majority of records.

2. **Lowest risk surface.** Non-stream is a single request/response cycle with
   the usage block in one place. Streaming has two protocol formats (NDJSON
   for Ollama, SSE for OpenAI-compatible), `stream_options` opt-in, frame
   ordering quirks. The non-stream change can be reasoned about purely
   functionally; the streaming change is a protocol re-implementation.

3. **debate.py adapter is trivial in non-stream.** `.content` works because
   `call_model` non-stream returns `ModelCallResult`. If we tried to do
   streaming in v2-A too, debate.py would need additional branching for the
   mixed-yield generator.

---

## 5. What v2-A explicitly does **not** address

- Streaming usage (→ v2-B)
- Cache-tier precise cost (→ v2-C)
- Codex / Claude / external direct DeepSeek API call recording (out of v2 scope)
- SQLite-backed ledger (out of v2 scope)
- Context Budget documentation (separate workstream)
- Cross-project ledger aggregation tooling (separate workstream)

---

## 6. v2-B — Streaming usage passthrough (sketch only)

Not for implementation now. Direction:

- Replace `Generator[str]` with a small `StreamHandle` object exposing
  `content_chunks() -> Iterator[str]` and `final_usage() -> dict | None`,
  resolved after the iterator drains. This avoids mixed yields entirely.
- For OpenAI-compatible streams, opt into usage via
  `stream_options={"include_usage": true}`, with a per-base-url cache of
  "server understood this field" / "server rejected this field" so we can
  fall back gracefully.
- For Ollama streams, parse the final `done` frame's usage fields.
- Worker's streaming branch consumes the new handle and forwards usage to
  the ledger.

A dedicated `docs/CALL_LEDGER_V2B_PLAN.md` will be written before v2-B starts.

## 7. v2-C — Cache-tier cost estimation (sketch only)

Not for implementation now. Direction:

- Extend `LOCAL_LLM_COST_TABLE` schema with optional `cached_in_per_1k`.
- Update `estimate_cost_cny` to compute as
  `(cached_tokens × cached_in_per_1k + cache_miss_tokens × in_per_1k + output_tokens × out_per_1k) / 1000`
  when both `cached_tokens` and `cached_in_per_1k` are present.
- Otherwise fall back to today's `in_per_1k × input_tokens + out_per_1k × output_tokens`.
- Backward compatible: cost tables without `cached_in_per_1k` continue to work.

A dedicated `docs/CALL_LEDGER_V2C_PLAN.md` will be written before v2-C starts.

---

## 8. One-line summary

v2-A = give the worker's non-stream path real `usage` from each provider,
piped through a single `ModelCallResult` value type and a single
`normalize_usage` mapping, with `debate.py` adapting one line; streaming and
cache-tier costing are deferred to v2-B and v2-C respectively.
