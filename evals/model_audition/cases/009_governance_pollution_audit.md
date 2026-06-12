# Case 009: Governance Document Pollution Audit

## Purpose

Test whether the model can detect polluted governance docs.

## Prompt

A generated file templates/project-governance/GRILLME.md contains:

```
# INTERFACES.md
# GRILLME.md
## 0. Purpose
## Purpose
Use this process to extract stable project knowledge...
Thought for 7s
● Write(templates/project-governance/INTERFACES.md)
Wrote 106 lines
```

## Required Output

```md
# Governance Pollution Audit

Verdict: PASS / BLOCK

## Pollution Found
## File Mismatch
## Required Cleanup
## New Ban Needed
## Verification Commands
```
