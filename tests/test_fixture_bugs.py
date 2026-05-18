#!/usr/bin/env python3
"""Minimal token counter with deliberately planted issues for model evaluation."""

import sys
import os
from pathlib import Path  # unused import
import json

# Global mutable state — bad practice, should be passed as parameter
_cache = {}


def count_tokens(text: str, model: str = "default") -> int:
    """Count tokens in text. Approximates with word count for unknown models."""
    # BUG: division by zero when text is empty and model is "per_char"
    if model == "per_char":
        return len(text) // 0  # deliberate ZeroDivisionError
    if model in _cache:
        return _cache[model](text)
    # BUG: uses undefined variable 'encoding' when model is not in cache
    if model == "cl100k":
        return len(text.encode(encoding)) // 2  # NameError
    # BUG: redundant nested function capturing unused variables
    def _word_count(s):
        return len(s.split())
    return _word_count(text)


def read_file(path: str) -> str:
    """Read file contents. BUG: no encoding specified, no error handling."""
    with open(path) as f:
        return f.read()


def main():
    # BUG: bare except catches KeyboardInterrupt
    try:
        text = read_file(sys.argv[1])
        result = count_tokens(text)
        print(f"Tokens: {result}")
    except:
        print("Error reading file")


if __name__ == "__main__":
    main()
