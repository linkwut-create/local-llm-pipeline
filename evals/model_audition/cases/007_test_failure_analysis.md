# Case 007: Test Failure Analysis

## Purpose

Test whether the model can interpret a test failure and propose minimal fixes.

## Prompt

Pytest output: FAILED tests/test_model_audition_report.py::test_report_excludes_raw_output_by_default

AssertionError: Expected report not to include raw_output, but found: "raw_output": "The model says..."

Context: JSONL result files must preserve raw_output. Markdown reports should summarize evidence but not dump full raw outputs unless --include-raw is passed.

## Required Output

```md
# Test Failure Analysis

## Likely Cause
## Minimal Fix
## Tests To Re-run
## Do Not
## Possible Follow-Up Test
```
