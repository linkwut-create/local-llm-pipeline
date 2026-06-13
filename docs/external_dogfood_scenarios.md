# External Dogfood Scenario Bank

12 scenarios across 4 external projects. Each scenario lists expected risk,
expected actual label, cloud permission, and privacy concern.

---

## local-translator-agent

### 1. Subtitle regression test
- **Task**: "fix subtitle timing regression in episode 12"
- **Expected risk**: low
- **Expected actual**: `local-first`
- **Cloud allowed?**: No (ordinary implementation task)
- **Privacy concern?**: No

### 2. OCR fallback bug
- **Task**: "fix OCR fallback crash when Tesseract returns empty string"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No (no user data in task description)

### 3. Release checklist
- **Task**: "prepare release checklist for v2.1.0: verify all translations pass"
- **Expected risk**: high
- **Expected actual**: `pro-review`
- **Cloud allowed?**: No (release gate, governance)
- **Privacy concern?**: No (checklist, not source content)

---

## Google Play Management

### 4. Internal testing checklist
- **Task**: "verify internal testing track has correct APK before promoting to alpha"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No

### 5. Store listing update
- **Task**: "update Google Play store listing screenshots and description for v3.0"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No (marketing content)
- **Privacy concern?**: No

### 6. Release artifact review
- **Task**: "review release APK signing and ProGuard mapping before production rollout"
- **Expected risk**: high
- **Expected actual**: `pro-review`
- **Cloud allowed?**: No (release security boundary)
- **Privacy concern?**: No (signing metadata, not keys)

---

## browser-plugin

### 7. Content script permission review
- **Task**: "review content script permissions: is `tabs` permission needed?"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No (extension review)
- **Privacy concern?**: No

### 8. Local model connection test
- **Task**: "test local model connection from extension background script"
- **Expected risk**: low
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No

### 9. Extension manifest audit
- **Task**: "audit manifest.json for missing CSP and permissions before Chrome Web Store submission"
- **Expected risk**: high
- **Expected actual**: `pro-review`
- **Cloud allowed?**: No (security boundary)
- **Privacy concern?**: No

---

## game-dev

### 10. Asset import script
- **Task**: "fix asset import script crash when FBX has no texture channel"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No

### 11. Save system test
- **Task**: "test save system migration from v1 to v2 format"
- **Expected risk**: medium
- **Expected actual**: `local-first`
- **Cloud allowed?**: No
- **Privacy concern?**: No (test data, not real saves)

### 12. Build packaging review
- **Task**: "review build packaging: verify assets are compressed, no source leaks in release"
- **Expected risk**: high
- **Expected actual**: `pro-review`
- **Cloud allowed?**: No (release boundary)
- **Privacy concern?**: No (build config, not secrets)

---

## Summary

| # | Project | Scenario | Risk | Actual |
|---|---------|----------|------|--------|
| 1 | translator | subtitle regression test | low | local-first |
| 2 | translator | OCR fallback bug | medium | local-first |
| 3 | translator | release checklist | high | pro-review |
| 4 | Google Play | internal testing checklist | medium | local-first |
| 5 | Google Play | store listing update | medium | local-first |
| 6 | Google Play | release artifact review | high | pro-review |
| 7 | browser-plugin | content script permissions | medium | local-first |
| 8 | browser-plugin | local model connection test | low | local-first |
| 9 | browser-plugin | extension manifest audit | high | pro-review |
| 10 | game-dev | asset import script | medium | local-first |
| 11 | game-dev | save system test | medium | local-first |
| 12 | game-dev | build packaging review | high | pro-review |

All 12 scenarios: cloud not needed, no privacy concern, no secrets.
