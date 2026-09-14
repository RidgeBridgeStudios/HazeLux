"""Unit tests for safe atomic relocation, collision strategies, and rollbacks."""

import os
from pathlib import Path
import shutil
import unittest.mock as mock
import pytest

from hazelux.engine.actions import (
    RelocationError,
    expand_rename_pattern,
    safe_copy_file,
    safe_relocate_file,
    safe_rename_file,
)
from hazelux.journal.manager import JournalManager


def test_rename_counter_collision_resolution(tmp_dir: Path, journal_mgr: JournalManager):
    source = tmp_dir / "invoice.pdf"
    source.write_text("invoice content")

    dest_dir = tmp_dir / "target"
    dest_dir.mkdir()

    # Pre-create conflicting files
    (dest_dir / "invoice.pdf").write_text("existing 0")
    (dest_dir / "invoice (1).pdf").write_text("existing 1")
    (dest_dir / "invoice (2).pdf").write_text("existing 2")

    result = safe_relocate_file(
        source_path=source,
        target_dir=dest_dir,
        target_name="invoice.pdf",
        strategy="rename_counter",
        journal_manager=journal_mgr,
    )

    # Next counter should be (3)
    assert result == dest_dir / "invoice (3).pdf"
    assert result.exists()
    assert result.read_text() == "invoice content"
    assert not source.exists()

    # Verify journal entry
    txns = journal_mgr.get_recent_transactions(limit=10)
    assert len(txns) == 1
    assert txns[0]["state"] == "committed"
    assert txns[0]["target_path"] == str(result)


def test_collision_skip_strategy(tmp_dir: Path, journal_mgr: JournalManager):
    source = tmp_dir / "doc.txt"
    source.write_text("new content")

    dest_dir = tmp_dir / "dest"
    dest_dir.mkdir()
    (dest_dir / "doc.txt").write_text("old content")

    result = safe_relocate_file(
        source_path=source,
        target_dir=dest_dir,
        target_name="doc.txt",
        strategy="skip",
        journal_manager=journal_mgr,
    )

    assert result is None
    assert source.exists()
    assert (dest_dir / "doc.txt").read_text() == "old content"


def test_collision_overwrite_strategy(tmp_dir: Path, journal_mgr: JournalManager):
    source = tmp_dir / "data.csv"
    source.write_text("overwritten")

    dest_dir = tmp_dir / "dest"
    dest_dir.mkdir()
    (dest_dir / "data.csv").write_text("original")

    result = safe_relocate_file(
        source_path=source,
        target_dir=dest_dir,
        target_name="data.csv",
        strategy="overwrite",
        journal_manager=journal_mgr,
    )

    assert result == dest_dir / "data.csv"
    assert result.read_text() == "overwritten"
    assert not source.exists()


def test_cross_device_transfer_integrity_and_staging(tmp_dir: Path, journal_mgr: JournalManager):
    source = tmp_dir / "cross_dev_source.bin"
    source.write_bytes(b"A" * 1024)
    dest_dir = tmp_dir / "dest"
    dest_dir.mkdir()

    real_stat = Path.stat

    def custom_stat(self_p, *args, **kwargs):
        st = real_stat(self_p, *args, **kwargs)
        if str(self_p) == str(dest_dir):
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev + 100, st.st_nlink, st.st_uid, st.st_gid, st.st_size, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
        return st

    with mock.patch.object(Path, "stat", custom_stat):
        result = safe_relocate_file(
            source_path=source,
            target_dir=dest_dir,
            target_name="cross_target.bin",
            strategy="rename_counter",
            journal_manager=journal_mgr,
        )

    assert result == dest_dir / "cross_target.bin"
    assert result.exists()
    assert result.stat().st_size == 1024
    assert not source.exists()

    staging_files = list(dest_dir.glob(".staging_*"))
    assert len(staging_files) == 0

    txns = journal_mgr.get_recent_transactions(limit=10)
    assert txns[0]["action_type"] == "move_cross_dev"
    assert txns[0]["state"] == "committed"


def test_cross_device_transfer_size_mismatch_failure(tmp_dir: Path, journal_mgr: JournalManager):
    source = tmp_dir / "failing_source.bin"
    source.write_bytes(b"B" * 500)
    dest_dir = tmp_dir / "dest"
    dest_dir.mkdir()

    real_stat = Path.stat

    def custom_stat(self_p, *args, **kwargs):
        st = real_stat(self_p, *args, **kwargs)
        if str(self_p) == str(dest_dir):
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev + 100, st.st_nlink, st.st_uid, st.st_gid, st.st_size, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
        return st

    def corrupt_copy(src, dst):
        Path(dst).write_bytes(b"B" * 200)

    with mock.patch.object(Path, "stat", custom_stat):
        with mock.patch("shutil.copy2", side_effect=corrupt_copy):
            with pytest.raises(RelocationError, match="Verification failure"):
                safe_relocate_file(
                    source_path=source,
                    target_dir=dest_dir,
                    target_name="corrupt.bin",
                    strategy="rename_counter",
                    journal_manager=journal_mgr,
                )

    assert source.exists()
    assert len(list(dest_dir.glob(".staging_*"))) == 0

    txns = journal_mgr.get_recent_transactions(limit=10)
    assert len(txns) >= 1
    assert txns[0]["state"] == "failed"


def test_rename_token_expansion(tmp_dir: Path, journal_mgr: JournalManager):
    f = tmp_dir / "report.pdf"
    f.write_text("pdf data")

    res = safe_rename_file(
        source_path=f,
        pattern="archived_{name}",
        strategy="rename_counter",
        journal_manager=journal_mgr,
    )
    assert res == tmp_dir / "archived_report.pdf"
    assert res.exists()
    assert not f.exists()
