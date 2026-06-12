# Case 004: JSON Profile Contract Repair

## Purpose

Test whether the model can repair a profile JSON snippet without changing semantics.

## Prompt

Broken snippet:

```json
{
  "profiles": {
    "deep_reviewer": {
      "model": "llama4:code",
      "model": "qwen3.6:35b",
      "_strengths": [
        "deep-review",
        "architecture",
        "architecture-review"
      ],
      "candidates": [
        "qwen3.6:35b",
        "qwen3.5-35b:latest",
        "mistral-medium-3.5-128b-q5_k_xl:latest"
        "llama4:code"
      ],
      "risk_level": "high",
      "_backend_class": "ollama_heavy_manual"
      "_constraints": "Not for commit gate."
    }
  }
}
```

The intended correction: use qwen3.6:35b; keep llama4:code only as a fallback candidate if appropriate; preserve the deep_reviewer role; do not convert it into a cloud profile; do not change unrelated profiles.

## Required Output

```md
# JSON Repair

## Problems Found
## Corrected JSON
## Semantic Preservation Notes
## Validation Commands
## Risks
```
