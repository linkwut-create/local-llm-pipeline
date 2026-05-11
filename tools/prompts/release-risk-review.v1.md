Review this release for risk. Check:
1. Version metadata consistency (VERSION, CHANGELOG, MCP server, global launcher)
2. CHANGELOG entry present for this version
3. Tests are complete and passing
4. run_checks is trustworthy (source_repo_mode runs full pytest)
5. No secrets (.env, key, pem, settings.local.json) included
6. No .local_llm_out / logs / cache / draft output included
7. No real project (non-pipeline) source files modified
8. MCP tool count (8) matches documentation
9. local_draft_code writes only to .local_llm_out/
10. Prompt registry hash matches stored values
11. Safe to tag / commit / push

Output structured JSON:
{
  "verdict": "PASS" | "WARN" | "FAIL",
  "blocking_risks": ["..."],
  "non_blocking_risks": ["..."],
  "required_fixes": ["..."],
  "suggested_checks": ["..."],
  "release_decision": "READY" | "FIX_REQUIRED" | "HOLD"
}
Do NOT make final decisions. Controller must verify all findings.
