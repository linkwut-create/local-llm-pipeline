#!/usr/bin/env python3
"""
Comprehensive model task test — tests ALL Ollama models with real tasks.
Output: JSON report to .local_llm_out/model_test_report.json.

Usage:
    py -3 tools/test_all_models.py
    py -3 tools/test_all_models.py --task summarize-file   # single task
    py -3 tools/test_all_models.py --profile fast_summary  # single profile
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

__test__ = False  # This is a standalone script, not a pytest test module.

SCRIPT_DIR = Path(__file__).parent
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "193.168.2.2:11434")
OLLAMA_URL = f"http://{OLLAMA_HOST}"

# Tasks to test
DEFAULT_TASKS = ["summarize-file"]
TEST_INPUT = "README.md"  # small file for quick testing


def get_ollama_models() -> list[str]:
    return get_available_models()



def unload_model(model: str):
    """No-op: llama.cpp manages VRAM."""
    pass

if __name__ == "__main__":
    main()
