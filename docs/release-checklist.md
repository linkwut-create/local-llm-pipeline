# Release Checklist

## Before Tagging

```powershell
# 1. Working tree must be clean
git status

# 2. Full test suite must pass
python -m pytest

# 3. Stability checks must pass
python tools/run_checks.py

# 4. Quick benchmark (optional, to verify models responsive)
python tools/benchmark_profiles.py --profile fast_summary --json

# 5. Installer dry-run against a temp project
$tmp = Join-Path $env:TEMP "release-test"; `
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null; `
  python install_local_llm_pipeline.py $tmp --dry-run

# 6. Update mode dry-run against a temp project
python install_local_llm_pipeline.py $tmp --update --dry-run

# 7. Check what changed
git diff --stat

# 8. Verify VERSION matches the tag you're about to create
type VERSION
```

## Forbidden

- Do NOT commit `.env`, `.env.*`, `*.key`, `*.pem`, `id_rsa`
- Do NOT commit `.claude/settings.local.json` or `.claude/settings.json`
- Do NOT commit `.local_llm_out/` contents
- Do NOT move or delete existing tags
- Do NOT force-push to main/master
- Do NOT auto-commit — always review `git diff` first
- Do NOT skip tests (no `--no-verify`)

## Tagging

```powershell
git add .
git commit -m "<version>: <summary>"
git tag v<version>
```

## After Tagging

```powershell
# Verify clean state
git status

# Verify tag points to HEAD
git log --oneline --decorate -3

# Verify all tags are in order
git tag --sort=-v:refname

# Verify previous tags are untouched
git log --oneline --decorate -15
```

## Rollback

If a tag was created on the wrong commit:

```powershell
git tag -d v<bad-version>          # delete locally
git push origin :refs/tags/v<bad-version>  # delete remotely (if pushed)
```

Then re-tag on the correct commit.

## Version Consistency

After every release, these must agree:

| Source | Expected |
|---|---|
| `VERSION` file | current release |
| `install_local_llm_pipeline.py` PIPELINE_VERSION | from VERSION |
| `tools/local_llm_mcp_server.py` SERVER_VERSION | from VERSION |
| `python tools/local_llm_mcp_server.py --version` | matches tag |
| `git tag` | latest = current release |
