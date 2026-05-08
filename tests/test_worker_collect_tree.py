"""Test the adaptive collect_tree budget allocation."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from local_llm_worker import collect_tree


def _create_tree(tmp: Path, files: dict[str, int]):
    """Create files with specified char counts. files = {name: size}."""
    for name, size in files.items():
        fpath = tmp / name
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text("x" * size, encoding="utf-8")


def test_large_file_not_over_truncated():
    """A 21000-char file with 60000 budget and 10 max_files should keep most of the big file."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _create_tree(tmp_path, {
            "big_worker.py": 21000,
            "small_a.py": 500,
            "small_b.py": 300,
            "small_c.json": 200,
        })

        content, warnings, trunc_report = collect_tree(tmp_path, max_files=10, max_chars=60000)

        assert "big_worker.py" in content
        assert "small_a.py" in content
        assert "small_b.py" in content
        assert "small_c.json" in content

        # The big file should NOT be truncated to 6000 chars (old bug)
        big_marker = "=== FILE: big_worker.py ==="
        idx = content.index(big_marker)
        big_section = content[idx:]
        next_file = big_section.find("=== FILE:", len(big_marker))
        if next_file > 0:
            big_section = big_section[:next_file]

        assert len(big_section) > 15000, f"Big file section only {len(big_section)} chars, should be >15000"
        assert len(trunc_report) == 0, f"Should not truncate with 60000 budget, got: {trunc_report}"


def test_small_files_fully_preserved():
    """Small files should be included completely."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _create_tree(tmp_path, {
            "a.py": 100,
            "b.py": 200,
            "c.py": 300,
        })

        content, warnings, trunc_report = collect_tree(tmp_path, max_files=10, max_chars=60000)

        assert len(trunc_report) == 0
        assert "x" * 100 in content
        assert "x" * 200 in content
        assert "x" * 300 in content


def test_budget_exhaustion_produces_report():
    """When total file size exceeds budget, truncation_report should be populated."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _create_tree(tmp_path, {
            "huge_a.py": 40000,
            "huge_b.py": 40000,
        })

        content, warnings, trunc_report = collect_tree(tmp_path, max_files=10, max_chars=50000)

        # At least one file should be truncated or skipped
        total_original = 80000
        assert len(content) <= 50000 + 500  # allow for headers
        assert len(trunc_report) > 0 or any("TRUNCATED" in w or "SKIPPED" in w for w in warnings)


def test_max_files_limits_count():
    """max_files should limit how many files are included."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _create_tree(tmp_path, {f"file_{i}.py": 100 for i in range(20)})

        content, warnings, trunc_report = collect_tree(tmp_path, max_files=5, max_chars=60000)

        file_markers = content.count("=== FILE:")
        assert file_markers == 5


def test_blocked_paths_excluded():
    """Blocked directories should not appear in output."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _create_tree(tmp_path, {
            "good.py": 100,
            "node_modules/bad.js": 100,
            "__pycache__/cached.pyc": 100,
        })

        content, warnings, trunc_report = collect_tree(tmp_path, max_files=10, max_chars=60000)

        assert "good.py" in content
        assert "bad.js" not in content
        assert "cached.pyc" not in content


def test_truncation_report_fields():
    """Truncation report entries should have the required fields."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _create_tree(tmp_path, {
            "big.py": 50000,
            "also_big.py": 50000,
        })

        content, warnings, trunc_report = collect_tree(tmp_path, max_files=10, max_chars=30000)

        if trunc_report:
            for entry in trunc_report:
                assert "path" in entry
                assert "original_chars" in entry
                assert "included_chars" in entry
                assert "reason" in entry
                assert entry["original_chars"] >= entry["included_chars"]
