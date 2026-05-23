# C2 — Streaming `stdout` Contract Audit

**v0.10.0-A | Read-only design audit | 2026-05-23**

## 1. Problem Statement

`tools/local_llm_mcp_server.py` has a **`stdout` contract divergence** between the
streaming and non-streaming subprocess execution paths inside `_wrap_worker_call`.

- **Non-streaming**: `stdout` is raw worker stdout text containing `JSON: <path>`
  markers. Downstream code calls `load_worker_output(result["stdout"])` to
  locate and parse the worker JSON output file.
- **Streaming** (line 1417): `stdout` is `json.dumps(output, …)` — a
  **serialized JSON string** of the already-parsed worker output dict. No
  `JSON:` markers survive. Every downstream call site that invokes
  `load_worker_output(result["stdout"])` on a streaming result receives
  `(None, "worker did not emit a JSON: marker …")`.

This is the **C2 double-serialization bug** identified in the P7-A grouped
audit (`tools/local_llm_mcp_server.py:1417`) and deferred at P7-C.

It was deferred because **"fixing changes the `stdout` field's contract for
every MCP tool that consumes it"** — the entire streaming path returns a
structurally different `stdout` format than the non-streaming path, and an
unknown number of tests and callers have adapted to (or been broken by) the
current behavior.

This document audits the full data flow, identifies every known consumer, and
proposes a migration plan. **It does not authorize implementation.**

## 2. Data Flow — Current State

### 2.1 Non-Streaming Path (`_wrap_worker_call`, line 1712)

```
worker process
  → stdout (raw text, contains "JSON: /path/to/output.json" marker)
  → run_subprocess(cmd, ...) returns {"stdout": raw_stdout, "ok": …, …}
  → load_worker_output(result["stdout"])
      → parse_worker_json_path(raw_stdout) finds the JSON file path
      → json.loads(file_content) → dict
  → payload = dict
  → build_success_response(tool, payload, …)
      → {"ok": True, "result": <dict>, "elapsed_seconds": …, "request_id": …}
  → handle_tools_call: json.dumps(response) (line 2580)
  → MCP client receives: text = JSON string, json.loads(text)["result"] = dict
```

**`stdout` in the intermediate result**: raw text with `JSON:` markers.
**`stdout` in the final MCP response**: not present — worker output is in
`result` field via `build_success_response`.

### 2.2 Streaming Path (`_wrap_worker_call`, line 1674)

```
worker process (--stream flag)
  → stdout (raw text, contains "JSON: /path/to/output.json" marker)
  → run_subprocess_streaming(cmd, …)
      → captures accumulated stdout
      → parse_worker_json_path(accumulated) finds the JSON file path
      → load_worker_output(json_path) → dict ("output")
      → return {"stdout": json.dumps(output, …), …}   ← LINE 1417
  → load_worker_output(result["stdout"])
      → parse_worker_json_path(json_string) → NO "JSON:" MARKER FOUND
      → returns (None, error)
  → payload = None
  → Falls through to error path: "missing_worker_output"
```

**`stdout` in the intermediate result**: `json.dumps(output)` — a serialized
JSON string of the worker output dict.
**`stdout` in the final MCP response**: double-serialized — first at line
1417, then again at line 2580. After `json.loads(text)`, the `stdout` field
is still a JSON string, not an object.

### 2.3 The Double-Serialization Chain

```
Worker output dict:  {"ok": true, "result": "…", "summary": "…", …}
                     ↓
Line 1417:           json.dumps(output, …) → '{"ok":true,"result":"…",…}'
                     ↓
Line 2580:           json.dumps({"ok":true, "stdout":'{"ok":true,…}',…}, …)
                     → '{"ok":true,"stdout":"{\\"ok\\":true,…}",…}'
                     ↓
MCP client:          json.loads(text)
                     result["stdout"] = '{"ok":true,"result":"…",…}'
                     (still a string, needs another json.loads)
```

### 2.4 Root Cause

`run_subprocess_streaming` at line 1417 does two things that `run_subprocess`
at line 1712 does not:

1. It calls `load_worker_output(json_path)` to pre-parse the output file
   into a dict.
2. It then calls `json.dumps(output, …)` to re-serialize that dict into the
   `stdout` field of the result dict.

The non-streaming path (`run_subprocess`) leaves `stdout` as raw text with
`JSON:` markers, and lets the caller (`_wrap_worker_call` line 1714) call
`load_worker_output` separately.

The streaming path's pre-serialization breaks the single consistent entry
point for downstream parsing. Every caller that expects `stdout` to contain
raw text with `JSON:` markers receives a JSON string instead.

## 3. Affected MCP Tools

All **8 worker-backed MCP tools** that route through `_wrap_worker_call`:

| MCP Tool | Handler Line | Streaming? |
|----------|-------------|------------|
| `local_summarize_file` | 2049 | When MCP client enables streaming |
| `local_summarize_tree` | 2114 | When MCP client enables streaming |
| `local_generate_test_plan` | 2155 | When MCP client enables streaming |
| `local_review_diff` | 2212 | When MCP client enables streaming |
| `local_contextual_analyze` | 2440 | When MCP client enables streaming |
| `local_draft_code` | 2499 | When MCP client enables streaming |
| `local_debate_review_diff` | (separate path) | Not routed through `_wrap_worker_call` |
| `local_parallel_review` | (separate path) | Not routed through `_wrap_worker_call` |

Plus `local_check` which uses its own subprocess path (not affected).

**Streaming is only activated when** the MCP client (Claude Code) sets
`stream=true` on the JSON-RPC request AND the `_stream_ctx` singleton has a
`progress_token`. In practice, this depends on the MCP client implementation.

## 4. Known Consumers of `result["stdout"]`

### 4.1 MCP Server — `_wrap_worker_call` Streaming Handler (line 1681)

```python
payload, _ = load_worker_output(result["stdout"])
```

**Impact**: Always returns `(None, error)` when `result["stdout"]` is a JSON
string. On `result["ok"] is True`, the handler returns `"missing_worker_output"`.
On failure, it falls through to `coerce_failure_response`.

### 4.2 MCP Server — `call_review_diff` (line 2345)

```python
output = json.loads(result["stdout"])
```

**Impact**: This is the only call site that **expects** a JSON string in
`stdout`. It tries `json.loads` first, and if that fails, falls back to
`load_worker_output`. This dual-path pattern was likely added as a workaround
for the C2 double-serialization — it handles both raw text and JSON string.

### 4.3 MCP Server — `call_local_check` (line 1978)

```python
"stdout": result["stdout"][:10000],
```

**Impact**: Passes through `stdout` for display. Affected by format drift but
not functionally broken — `local_check` uses its own subprocess path.

### 4.4 MCP Server — `call_debate_review_diff` (line 2261)

```python
payload, parse_err = load_worker_output(result["stdout"])
```

**Impact**: Uses `_run_debate_subprocess` which is NOT the same as
`run_subprocess` — separate code path, also affected if streaming is enabled.

### 4.5 Commit Gate — `review_tool_succeeded` (`mcp_gate.py:209`)

```python
text = _extract_mcp_response_text(payload.get("tool_response"))
result = json.loads(text)
```

**Impact**: Consumes the **final MCP response** (after line 2580
serialization), not the intermediate `stdout`. The `ok` field is at the
top level of the MCP response. Not directly affected by the C2 `stdout`
format, but **indirectly affected** if the commit gate later parses the
`result` field for review findings.

### 4.6 Hook — `handle_post_tooluse` (`mcp_gate.py:889`)

```python
if review_tool_succeeded(payload, config_dir):
    state["diff_reviewed"] = True
```

**Impact**: Same as 4.5 — consumes the final MCP response, checks `ok`.
Not directly affected by `stdout` format.

### 4.7 Tests

Tests that mock `run_subprocess` or `run_subprocess_streaming` and inspect
`result["stdout"]` may be affected. Key test files:

- `tests/test_local_llm_v093.py` — MCP server integration tests
- `tests/test_mcp_server.py` — MCP server unit tests
- `tests/test_mcp_gate_boundary.py` — commit gate boundary tests

Some tests may already have workarounds (e.g., `json.loads(result["stdout"])`
before assertion) that mask the double-serialization.

## 5. Desired Contract Options

### Option A: `stdout` = Always Raw Text (Align Streaming to Non-Streaming)

Remove `json.dumps(output, …)` at line 1417. Return raw worker stdout (with
`JSON:` markers) in `stdout`, same as `run_subprocess`.

**Pros**: Consistent contract across both paths. Every downstream call to
`load_worker_output(result["stdout"])` works the same way.
**Cons**: Loses the in-process pre-parsing benefit. Streaming path must
re-parse from the JSON file (same as non-streaming).

### Option B: `stdout` = Always Parsed Object (Align Non-Streaming to Streaming)

Change `run_subprocess` to also call `load_worker_output` and return the dict
directly in a new field (e.g., `payload`), deprecating `stdout` as a raw text
field.

**Pros**: Clean separation — `stdout` for display, `payload` for data.
**Cons**: Larger change. Touches `run_subprocess` and every `_wrap_worker_call`
consumer that reads `result["stdout"]`. Migration requires touching ~10 call
sites.

### Option C: Dual-Compatible Migration (Recommended)

1. Add a **compatibility parser** that detects whether `stdout` is raw text
   or JSON string, and delegates accordingly.
2. Insert it at every `load_worker_output(result["stdout"])` call site.
3. Then fix line 1417 to emit raw text (Option A).
4. Then remove the compatibility shim once all consumers are verified.

**Pros**: No consumer breaks during migration. Each step is independently
reversible. Can ship v0.10.0 with the compat parser and v0.11.0 with the
cleaned contract.
**Cons**: Two-phase migration. Temporary code (compat parser).

## 6. Recommended Migration Plan

### Phase 1: Compat Parser (v0.10.0-B, after design approval)

Add a new helper in `tools/local_llm_mcp_server.py`:

```
def _parse_worker_stdout(stdout: str) -> tuple[dict | None, str | None]:
    """Parse stdout from either raw text or pre-serialized JSON."""
```

- Try `parse_worker_json_path(stdout)` first (raw text path).
- If that fails, try `json.loads(stdout)` (JSON string path).
- If that also fails, return `(None, error)`.
- Replace all `load_worker_output(result["stdout"])` call sites with this helper.

**No behavior change** — just a centralized compat layer. All existing
behavior is preserved.

### Phase 2: Fix Producer (v0.10.0-C, after compat validated)

Remove `json.dumps(output, …)` at line 1417 in `run_subprocess_streaming`.
Return the raw accumulated stdout (with `JSON:` markers) in `stdout`, matching
`run_subprocess`.

Because the compat parser was installed in Phase 1, every consumer handles
both formats and the switch is transparent.

### Phase 3: Cleanup (v0.10.0-D, after full validation)

- Remove the compat parser's `json.loads(stdout)` fallback.
- Rename `_parse_worker_stdout` back to `load_worker_output` or merge.
- Remove the dual-path pattern in `call_review_diff` (line 2345).

### Phase 4: Tests

- Add tests for the compat parser (raw text path, JSON string path, neither).
- Add a streaming-path integration test that verifies `_wrap_worker_call`
  returns `build_success_response` when streaming.
- Update existing tests that may have workarounds for double-serialization.
- Regression: 1196 passed.

## 7. Non-Goals (Explicitly Out of Scope)

- No worker behavior changes (`local_llm_worker.py` untouched).
- No ledger schema or behavior changes.
- No hook behavior changes (`mcp_gate.py`, `mcp_auto_worker.py`, `mcp_doctor.py`).
- No implementation in v0.10.0-A (this document is design-only).
- No broad MCP protocol rewrite. The `jsonrpc` envelope (line 2580) is not
  part of C2 — only the `stdout` field inside it.
- No streaming feature removal. Streaming is a valid MCP feature; C2 fixes the
  data format, not the presence of streaming.

## 8. Test Surface

| Test File | Tests Affected | Nature |
|-----------|---------------|--------|
| `tests/test_local_llm_v093.py` | ~15 MCP integration tests | Mock `run_subprocess` / `run_subprocess_streaming`; may need compat parser |
| `tests/test_mcp_server.py` | ~68 MCP server tests | Some mock `_wrap_worker_call`; verify response shape |
| `tests/test_mcp_gate_boundary.py` | ~12 commit gate tests | Verify `review_tool_succeeded` parsing |
| `tests/test_mcp_auto_worker.py` | ~35 auto worker tests | Background spawns; indirect via hook logs |

## 9. Validation Plan (for implementation phases)

```
py -3 -m pytest tests/test_local_llm_v093.py -q
py -3 -m pytest tests/test_mcp_server.py -q
py -3 -m pytest tests/test_mcp_gate_boundary.py -q
py -3 -m pytest tests/test_mcp_auto_worker.py -q
py -3 -m pytest tests/ -x --tb=short -q
py -3 tools/run_checks.py
```

Plus manual MCP smoke test: invoke `local_summarize_file` via Claude Code MCP
with streaming enabled (if supported by the client).

## 10. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Streaming path never used in practice → fix is cosmetic | Medium | Low | Verify with `call_ledger` — check if any records have `streamed=true`. If zero, C2 is lower priority. |
| Compat parser misses an edge case format | Low | Medium | Exhaustive unit tests for raw text, JSON string, empty, and mixed formats. |
| Consumer we didn't find breaks after Phase 2 | Low | High | Phase 1 (compat only) gives a full release cycle to discover unknown consumers before Phase 2 touches the producer. |
| Phase 2 changes `_wrap_worker_call` streaming behavior | Medium | High | The non-streaming path is the hot path. Streaming is only used when MCP client enables it. Phase 1 is zero-risk; Phase 2 is gated behind phase 1 validation. |

## 11. Relationship to Other Deferred Items

- **P6-B2-C** (write-failure propagation): Unrelated. C2 fixes the data
  format; P6-B2-C fixes error propagation.
- **H6** (classify_error): Unrelated. C2 fixes stdout serialization; H6 fixes
  error type classification.
- **M3** (ledger rotation): Unrelated. C2 fixes MCP tool output; M3 fixes
  call ledger lifecycle.
- **P7-B** (hook diagnostics): Compatible. C2 may change the `stdout` that
  `review_tool_succeeded` sees, but the compat parser keeps it transparent.

## 12. Decision Record

- **v0.10.0-A**: This document. Design only. No code changes. Landed at `b984511`.
- **v0.10.0-B**: Implement compat parser (Phase 1). Landed at `6f4a3c1`.
  - Added `_parse_worker_stdout(stdout)` with 4 string strategies.
  - Fixed `run_subprocess_streaming:1413` file-path-vs-stdout bug.
  - Replaced `load_worker_output(result["stdout"])` at all 4 consumer call sites.
  - 15 targeted tests.
  - No MCP contract change, no producer change.
- **v0.10.0-C**: Harden compat parser for dict/object input (Phase 1 hardening).
  - Parser now accepts already-loaded dicts (Strategy 0 — transparent pass-through).
  - Non-dict objects/lists rejected with a structured error.
  - Consumer inventory completed: all stdout consumers are inside
    `tools/local_llm_mcp_server.py`; hooks have zero direct consumers.
  - Producer contract migration (removing `json.dumps(output)` at line 1417)
    remains **not yet performed**.
- **v0.10.0-D**: Fix producer (Phase 2). Landed.
  - Removed `json.dumps(output, …)` at line 1417 in `run_subprocess_streaming`.
    Streaming producer now passes the parsed dict directly as `stdout`.
  - `_parse_worker_stdout` Strategy 0 (v0.10.0-C) handles the dict transparently.
  - All 4 consumer call sites unchanged — compat parser handles both string
    and dict shapes.
  - The streaming `stdout` contract is now unified with the non-streaming path:
    both produce a dict that `_parse_worker_stdout` can consume directly.
  - Targeted tests confirm dict passthrough from producer through parser.
- **v0.10.0-E**: Cleanup (Phase 3 — **not authorized**). Removes compat
  string fallbacks (Strategies 1-4) once dict is the sole observed format in
  production.

---

*Last updated: v0.10.0-D producer migration. Based on HEAD `bbed639` (v0.10.0-C).*
