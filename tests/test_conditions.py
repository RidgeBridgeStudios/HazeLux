"""Unit tests for Hazelux rule condition matching and type coercion."""

import os
from pathlib import Path
import subprocess
import time
import pytest

from hazelux.engine.conditions import (
    REGEX_TIMEOUT_SECONDS,
    evaluate_conditions,
    evaluate_single_condition,
)


def test_name_string_operators(tmp_dir: Path):
    f = tmp_dir / "Document_2026_Final.pdf"
    f.write_text("dummy")

    # is
    assert evaluate_single_condition(f, {"field": "name", "operator": "is", "value": "Document_2026_Final"})
    assert not evaluate_single_condition(f, {"field": "name", "operator": "is", "value": "Document"})

    # starts_with & ends_with
    assert evaluate_single_condition(f, {"field": "name", "operator": "starts_with", "value": "Document"})
    assert evaluate_single_condition(f, {"field": "name", "operator": "ends_with", "value": "Final"})

    # contains & does_not_contain
    assert evaluate_single_condition(f, {"field": "name", "operator": "contains", "value": "2026"})
    assert evaluate_single_condition(f, {"field": "name", "operator": "does_not_contain", "value": "Draft"})


def test_name_case_insensitivity(tmp_dir: Path):
    f = tmp_dir / "Invoice_AUG.PDF"
    f.write_text("test")

    # Case-sensitive by default
    assert not evaluate_single_condition(
        f, {"field": "name", "operator": "is", "value": "invoice_aug", "case_insensitive": False}
    )
    # Case-insensitive toggle
    assert evaluate_single_condition(
        f, {"field": "name", "operator": "is", "value": "invoice_aug", "case_insensitive": True}
    )

    # Extension case sensitivity
    assert not evaluate_single_condition(
        f, {"field": "extension", "operator": "is", "value": "pdf", "case_insensitive": False}
    )
    assert evaluate_single_condition(
        f, {"field": "extension", "operator": "is", "value": "pdf", "case_insensitive": True}
    )


def test_extension_leading_dot_stripping(tmp_dir: Path):
    f = tmp_dir / "archive.tar.gz"
    f.write_text("test")

    # Extension evaluates suffix (lstrip('.'))
    assert evaluate_single_condition(f, {"field": "extension", "operator": "is", "value": ".gz"})
    assert evaluate_single_condition(f, {"field": "extension", "operator": "is", "value": "gz"})


def test_regex_evaluation_and_timeout(tmp_dir: Path):
    f = tmp_dir / "Report_v12_final.xlsx"
    f.write_text("test")

    # Valid regex
    assert evaluate_single_condition(
        f, {"field": "name", "operator": "matches_regex", "value": r"^Report_v\d+_final$"}
    )
    assert not evaluate_single_condition(
        f, {"field": "name", "operator": "matches_regex", "value": r"^Draft_\d+$"}
    )

    # Pathological pattern that causes catastrophic backtracking
    long_name_file = tmp_dir / ("a" * 35 + "!.txt")
    long_name_file.write_text("test")

    pathological_pattern = r"^(a+)+$"
    t0 = time.time()
    result = evaluate_single_condition(
        long_name_file,
        {"field": "name", "operator": "matches_regex", "value": pathological_pattern},
    )
    duration = time.time() - t0

    # Must return False and terminate without hanging
    assert result is False
    # Generous margin: should terminate well under 0.5s with a 100ms timeout
    assert duration < 0.8, f"Regex took too long to time out: {duration:.3f}s"


def test_sparse_file_size_evaluation(tmp_dir: Path):
    # Test boundary size evaluations using a 10GB sparse file (truncate -s 10G)
    sparse_file = tmp_dir / "sparse_test.bin"
    try:
        subprocess.run(["truncate", "-s", "10G", str(sparse_file)], check=True)
    except Exception:
        # Fallback to ftruncate if truncate CLI unavailable
        with open(sparse_file, "wb") as f:
            f.truncate(10 * 1024 * 1024 * 1024)

    assert sparse_file.stat().st_size == 10 * 1024 * 1024 * 1024

    # greater_than 5GB
    five_gb = 5 * 1024 * 1024 * 1024
    assert evaluate_single_condition(
        sparse_file, {"field": "size_bytes", "operator": "greater_than", "value": five_gb}
    )
    # less_than 20GB
    twenty_gb = 20 * 1024 * 1024 * 1024
    assert evaluate_single_condition(
        sparse_file, {"field": "size_bytes", "operator": "less_than", "value": twenty_gb}
    )
    # exact is
    assert evaluate_single_condition(
        sparse_file, {"field": "size_bytes", "operator": "is", "value": 10 * 1024 * 1024 * 1024}
    )


def test_date_modified_offset(tmp_dir: Path):
    f = tmp_dir / "old_file.txt"
    f.write_text("test")

    # Set mtime to 2 hours ago (7200s)
    now = time.time()
    two_hours_ago = now - 7200.0
    os.utime(f, (two_hours_ago, two_hours_ago))

    # modified > 3600 seconds ago -> True
    assert evaluate_single_condition(
        f, {"field": "date_modified", "operator": "greater_than", "value": 3600}
    )
    # modified < 10000 seconds ago -> True
    assert evaluate_single_condition(
        f, {"field": "date_modified", "operator": "less_than", "value": 10000}
    )
    # modified > 10000 seconds ago -> False
    assert not evaluate_single_condition(
        f, {"field": "date_modified", "operator": "greater_than", "value": 10000}
    )


def test_date_created_birthtime_handling(tmp_dir: Path):
    f = tmp_dir / "created_file.txt"
    f.write_text("test")
    st = f.stat()

    # If st_birthtime is absent (e.g. Linux ext4 without statx btime exposed), strictly False
    res = evaluate_single_condition(
        f, {"field": "date_created", "operator": "greater_than", "value": 10}
    )
    if not hasattr(st, "st_birthtime"):
        assert res is False


def test_group_modes_all_any_none(tmp_dir: Path):
    f = tmp_dir / "Project_Notes.md"
    f.write_text("hello")

    cond_all = {
        "mode": "all",
        "rules": [
            {"field": "name", "operator": "starts_with", "value": "Project"},
            {"field": "extension", "operator": "is", "value": "md"},
        ],
    }
    assert evaluate_conditions(f, cond_all)

    cond_any = {
        "mode": "any",
        "rules": [
            {"field": "name", "operator": "is", "value": "DoesNotMatch"},
            {"field": "extension", "operator": "is", "value": "md"},
        ],
    }
    assert evaluate_conditions(f, cond_any)

    cond_none = {
        "mode": "none",
        "rules": [
            {"field": "name", "operator": "contains", "value": "Secret"},
            {"field": "extension", "operator": "is", "value": "exe"},
        ],
    }
    assert evaluate_conditions(f, cond_none)
