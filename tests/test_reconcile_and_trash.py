"""Unit tests for startup crash reconciliation and FreeDesktop trash undo."""

import configparser
from pathlib import Path
import sqlite3
import time
import unittest.mock as mock
import pytest

from hazelux.journal.manager import JournalManager
from hazelux.journal.reconcile import reconcile_journal_on_startup
from hazelux.journal.trash import restore_trashed_file, trash_file


def test_reconcile_pending_same_dev_source_intact(tmp_dir: Path, journal_mgr: JournalManager):
    """Crash before atomic replace: source intact, zero-byte target placeholder exists."""
    source = tmp_dir / "orig.txt"
    source.write_text("keep original")
    target = tmp_dir / "target.txt"
    target.touch()  # 0 bytes placeholder

    journal_mgr.log_transaction(
        txn_id="pending-same-dev-1",
        inode=source.stat().st_ino,
        action_type="move_same_dev",
        source_path=str(source),
        target_path=str(target),
        state="pending",
    )

    reconcile_journal_on_startup(journal_mgr.db_path)

    # Placeholder should be unlinked, source intact, transaction reverted
    assert source.exists()
    assert not target.exists()
    txn = journal_mgr.get_transaction("pending-same-dev-1")
    assert txn["state"] == "reverted"


def test_reconcile_staging_written_source_missing(tmp_dir: Path, journal_mgr: JournalManager):
    """Crash after source was unlinked: staging holds the only data, complete commit."""
    staging = tmp_dir / ".staging_123_data.bin"
    staging.write_text("payload data")
    target = tmp_dir / "data.bin"
    target.touch()

    journal_mgr.log_transaction(
        txn_id="staging-written-1",
        inode=999,
        action_type="move_cross_dev",
        source_path=str(tmp_dir / "nonexistent_source.bin"),
        target_path=str(target),
        staging_path=str(staging),
        state="staging_written",
    )

    reconcile_journal_on_startup(journal_mgr.db_path)

    # Staging should have been moved into target, and state committed
    assert not staging.exists()
    assert target.exists()
    assert target.read_text() == "payload data"
    txn = journal_mgr.get_transaction("staging-written-1")
    assert txn["state"] == "committed"


def test_reconcile_failed_orphaned_staging_cleanup(tmp_dir: Path, journal_mgr: JournalManager):
    """Orphaned staging files from failed transactions should be purged, maintaining failed state."""
    staging = tmp_dir / ".staging_failed_file.tmp"
    staging.write_text("orphaned bytes")

    journal_mgr.log_transaction(
        txn_id="failed-txn-1",
        inode=111,
        action_type="move_cross_dev",
        source_path=str(tmp_dir / "src.bin"),
        target_path=str(tmp_dir / "dest.bin"),
        staging_path=str(staging),
        state="failed",
    )

    reconcile_journal_on_startup(journal_mgr.db_path)

    assert not staging.exists()
    txn = journal_mgr.get_transaction("failed-txn-1")
    assert txn["state"] == "failed"


def test_reconcile_cross_dev_unlinked_source(tmp_dir: Path, journal_mgr: JournalManager):
    """Cross-device move where replace finished but source wasn't unlinked."""
    source = tmp_dir / "src.txt"
    source.write_text("same content")
    target = tmp_dir / "target.txt"
    target.write_text("same content")

    journal_mgr.log_transaction(
        txn_id="cross-dev-replace-done",
        inode=source.stat().st_ino,
        action_type="move_cross_dev",
        source_path=str(source),
        target_path=str(target),
        state="committed",
    )

    reconcile_journal_on_startup(journal_mgr.db_path)

    assert not source.exists()
    assert target.exists()


def test_trash_undo_metadata_fallback(tmp_dir: Path):
    """Test trash restoration heuristic using mock ~/.local/share/Trash."""
    mock_trash = tmp_dir / "Trash"
    info_dir = mock_trash / "info"
    files_dir = mock_trash / "files"
    info_dir.mkdir(parents=True)
    files_dir.mkdir(parents=True)

    original_file = tmp_dir / "documents" / "restore_me.txt"
    original_file.parent.mkdir(parents=True)

    trashed_payload = files_dir / "restore_me.txt"
    trashed_payload.write_text("restorable content")

    info_file = info_dir / "restore_me.txt.trashinfo"
    info_content = f"""[Trash Info]
Path={original_file}
DeletionDate=2026-09-14T12:00:00
"""
    info_file.write_text(info_content)

    with mock.patch("hazelux.journal.trash.get_trash_dir", return_value=mock_trash):
        # Restore with fallback strategy
        success = restore_trashed_file(source_path=str(original_file), trash_uri=None)

    assert success is True
    assert original_file.exists()
    assert original_file.read_text() == "restorable content"
    assert not trashed_payload.exists()
    assert not info_file.exists()
