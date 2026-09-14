"""Unit tests for SQLite journal retention pruning and WAL truncation."""

from pathlib import Path
import time
import pytest

from hazelux.journal.manager import JournalManager


def test_journal_retention_and_vacuum(tmp_dir: Path, journal_mgr: JournalManager):
    now = 1750000000.0  # reference epoch timestamp

    day_seconds = 86400.0

    # 1. Committed, not reverted, 10 days old -> KEEP
    journal_mgr.log_transaction(
        txn_id="c-10d",
        inode=1,
        action_type="move_same_dev",
        source_path="/a",
        target_path="/b",
        state="committed",
        timestamp=now - (10 * day_seconds),
    )

    # 2. Committed, not reverted, 35 days old -> PURGE (> 30 days)
    journal_mgr.log_transaction(
        txn_id="c-35d",
        inode=2,
        action_type="move_same_dev",
        source_path="/c",
        target_path="/d",
        state="committed",
        timestamp=now - (35 * day_seconds),
    )

    # 3. Reverted, 50 days old -> KEEP (< 90 days)
    journal_mgr.log_transaction(
        txn_id="r-50d",
        inode=3,
        action_type="copy",
        source_path="/e",
        target_path="/f",
        state="reverted",
        timestamp=now - (50 * day_seconds),
    )

    # 4. Reverted, 95 days old -> PURGE (> 90 days)
    journal_mgr.log_transaction(
        txn_id="r-95d",
        inode=4,
        action_type="copy",
        source_path="/g",
        target_path="/h",
        state="reverted",
        timestamp=now - (95 * day_seconds),
    )

    # 5. Failed transaction, 100 days old -> KEEP (only committed & reverted are age-purged)
    journal_mgr.log_transaction(
        txn_id="failed-100d",
        inode=5,
        action_type="move_same_dev",
        source_path="/i",
        target_path="/j",
        state="failed",
        timestamp=now - (100 * day_seconds),
    )

    # Execute pruning with reference time
    journal_mgr.prune_and_vacuum(now=now)

    # Verify survivors
    assert journal_mgr.get_transaction("c-10d") is not None
    assert journal_mgr.get_transaction("r-50d") is not None
    assert journal_mgr.get_transaction("failed-100d") is not None

    # Verify purged
    assert journal_mgr.get_transaction("c-35d") is None
    assert journal_mgr.get_transaction("r-95d") is None
