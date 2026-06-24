#!/usr/bin/env python3
"""
Model Capability Assessment — each model takes a battery of standardized tests.
Results determine which role/profile each model is best suited for.

Usage:
    py -3 tools/model_capability_test.py
    py -3 tools/model_capability_test.py --model qwen3-coder:30b
    py -3 tools/model_capability_test.py --quick  # test fewer models faster
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from local_llm_api import call_chat_completion, get_available_models

SCRIPT_DIR = Path(__file__).parent
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "193.168.2.2:11434")
OLLAMA_API = f"http://{OLLAMA_HOST}/api/generate"

# ── Test Battery ──────────────────────────────────────────────
# Each test is a (capability, prompt, eval_criteria)
# eval: "contains:<word>" | "length:>N" | "speed:<Ns"
BATTERY = [
    {
        "id": "speed",
        "capability": "basic-response",
        "prompt": "Say hello.",
        "eval": "length:>2",
        "timeout": 30,
    },
    {
        "id": "summary",
        "capability": "summarization",
        "prompt": "Summarize this in exactly one short sentence: Artificial intelligence has transformed many industries including healthcare, finance, and transportation. Machine learning models can now diagnose diseases, predict market trends, and drive cars autonomously.",
        "eval": "length:>20",
        "timeout": 60,
    },
    {
        "id": "code",
        "capability": "code-understanding",
        "prompt": "In one sentence, what does this function return? `def f(n): return len([x for x in range(2, n) if all(x % d != 0 for d in range(2, int(x**0.5)+1))])`",
        "eval": "contains:prime",
        "timeout": 60,
    },
    {
        "id": "logic",
        "capability": "reasoning",
        "prompt": "All cats are mammals. Some mammals are aquatic. Can we conclude that some cats are aquatic? Answer ONLY: Yes or No.",
        "eval": "contains:No",
        "timeout": 60,
    },
    {
        "id": "chinese",
        "capability": "multilingual",
        "prompt": "用一句话翻译成英文：人工智能正在改变世界。",
        "eval": "contains:intelligence",
        "timeout": 60,
    },
    {
        "id": "structure",
        "capability": "structured-output",
        "prompt": "Output exactly this JSON and nothing else: {\"name\":\"test\",\"value\":42}",
        "eval": "contains:\"name\"",
        "timeout": 60,
    },
]

# ── Role assignment ──────────────────────────────────────────
# Based on which capabilities a model passes, assign it to roles
ROLE_RULES = [
    {
        "role": "fast_summary",
        "requires": ["basic-response", "summarization"],
        "prefers": ["speed < 5s"],
        "model_field": "fast lightweight summarizer",
    },
    {
        "role": "code_worker",
        "requires": ["basic-response", "code-understanding"],
        "prefers": ["structured-output"],
        "model_field": "coder / code-adjacent tasks",
    },
    {
        "role": "commit_reviewer",
        "requires": ["basic-response", "code-understanding"],
        "prefers": ["speed < 30s", "structured-output"],
        "model_field": "fast commit-gate reviewer",
    },
    {
        "role": "diff_reviewer",
        "requires": ["basic-response", "code-understanding", "reasoning"],
        "model_field": "thorough diff reviewer",
    },
    {
        "role": "deep_reviewer",
        "requires": ["basic-response", "code-understanding", "reasoning"],
        "prefers": ["structured-output"],
        "model_field": "deep architecture reviewer",
    },
    {
        "role": "reasoning_checker",
        "requires": ["basic-response", "reasoning"],
        "model_field": "risk analysis / logic check",
    },
    {
        "role": "deep_reasoning",
        "requires": ["basic-response", "reasoning", "structured-output"],
        "model_field": "deep reasoning for critical tasks",
    },
    {
        "role": "translation",
        "requires": ["basic-response", "multilingual"],
        "prefers": ["summarization"],
        "model_field": "translation tasks",
    },
    {
        "role": "smart_summary",
        "requires": ["basic-response", "summarization"],
        "prefers": ["structured-output", "speed < 10s"],
        "model_field": "high-quality summarizer",
    },
    {
        "role": "heavy_reviewer",
        "requires": ["basic-response", "code-understanding", "reasoning"],
        "prefers": ["summarization"],
        "model_field": "large backup reviewer",
    },
]


def call_ollama(model: str, prompt: str, timeout: int = 60) -> dict:
    """Call model via LiteLLM OpenAI-compat API."""
    return call_chat_completion(
        model, [{"role": "user", "content": prompt}],
        max_tokens=200, timeout=timeout)
def unload_model(model: str):
    """No-op: llama.cpp manages VRAM."""
    pass


def get_ollama_models() -> list[str]:
    return get_available_models()

if __name__ == "__main__":
    main()
