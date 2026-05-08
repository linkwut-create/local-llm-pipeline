# Local LLM Worker Documentation

## Architecture

```
Controller (Claude Code / Codex)
    |
    v
tools/local_llm_router.py   -- selects profile & model
    |
    v
tools/local_llm_worker.py   -- executes task against local model
    |
    v
Ollama / llama.cpp / OpenAI-compatible server
    |
    v
.local_llm_out/*.json + *.md  -- structured output
    |
    v
Controller reads output, verifies, and makes final decisions
```

## Setup

### Prerequisites

- Python 3.10+
- `pip install requests`
- Ollama installed and running (`ollama serve`)
- At least one model pulled (`ollama pull qwen3.5-9b-q8`)

### Quick Start

```bash
# Check environment
python tools/local_llm_check.py

# Summarize a file
python tools/local_llm_router.py summarize-file README.md

# Summarize a directory
python tools/local_llm_router.py summarize-tree src --max-files 30

# Extract TODOs
python tools/local_llm_router.py extract-todos src

# Generate test plan
python tools/local_llm_router.py generate-test-plan src/example.py

# Review current diff
git diff | python tools/local_llm_router.py review-diff --stdin

# Risk analysis
python tools/local_llm_router.py risk-analysis docs/plan.md
```

### Ollama Setup

```bash
# Install Ollama (Windows)
# Download from https://ollama.com

# Start the server
ollama serve

# Pull recommended models
ollama pull qwen3.5-9b-q8         # fast summary
ollama pull qwen3-coder:30b       # code worker
ollama pull qwen3.6:27b-q8-ud     # diff reviewer
ollama pull qwen3.5-35b-q8        # deep reviewer
ollama pull qwen3.5-27b-reasoning  # reasoning checker
ollama pull translategemma-27b-it-q8  # translation
```

### llama.cpp / OpenAI-Compatible Setup

```bash
# If using llama.cpp server on port 8080:
python tools/local_llm_router.py summarize-file README.md --provider openai-compatible

# Or set environment variable:
set LOCAL_LLM_PROVIDER=openai-compatible
set LOCAL_LLM_BASE_URL=http://localhost:8080/v1
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| LOCAL_LLM_PROVIDER | ollama | Provider: ollama or openai-compatible |
| LOCAL_LLM_MODEL | (from profile) | Model name override |
| LOCAL_LLM_BASE_URL | http://localhost:11434 | API base URL |
| LOCAL_LLM_TIMEOUT | 300 | API timeout in seconds |
| LOCAL_LLM_MAX_CHARS | 60000 | Max input characters |
| LOCAL_LLM_OUTPUT_DIR | .local_llm_out | Output directory |

## Output Format

Each task produces two files in `.local_llm_out/`:
- `<timestamp>_<task>.json` — structured JSON for programmatic use
- `<timestamp>_<task>.md` — human-readable Markdown

The JSON always includes: task, profile, model, ok, summary, key_files, must_read, risks, test_gaps, uncertain_points, confidence, result, warnings, error, created_at.

## Claude Code Usage

- Use `/local-check` to verify the environment.
- Use `/local-review-diff` before finalizing changes.
- Use `/local-test-plan` before writing tests.
- Use `/local-risk` for risk assessment.
- The `local-worker-auditor` subagent can run worker tasks autonomously.

## Codex Usage

- Reference AGENTS.md for the worker policy.
- Call `tools/local_llm_router.py` directly from Codex.
- Read `.codex/local-llm-worker.md` for allowed tasks and rules.

## Troubleshooting

| Problem | Solution |
|---|---|
| "No models available" | Run `ollama serve` and `ollama list` |
| "requests not installed" | Run `pip install requests` |
| "Model not found" | Check `ollama list` for exact model names |
| Timeout errors | Increase `--timeout` or `LOCAL_LLM_TIMEOUT` |
| Empty output | Check model is loaded: `ollama run <model> "hello"` |
| Wrong model selected | Use `--model <name>` to override |

## Upgrading

### Phase 2: Cross-Review (local_llm_debate.py)

Add when Phase 1 is stable and you need:
- Multiple models reviewing the same code
- Reasoning model challenging coder model conclusions
- Structured debate with max 2 rounds

### Phase 3: MCP Server (local_llm_mcp_server.py)

Add when CLI routing is stable and you want:
- Native Claude Code / Codex MCP tool integration
- Automatic tool discovery
- No manual command construction
