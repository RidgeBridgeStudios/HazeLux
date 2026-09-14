"""Startup crash reconciliation routine for Hazelux transaction journal."""

import logging
import os
from pathlib import Path
import sqlite3

logger = logging.getLogger("hazelux.journal.reconcile")


def reconcile_journal_on_startup(db_path: Path) -> None:
    """Scans journal for uncommitted transactions from abnormal shutdowns

    and reconciles state to prevent duplicate files or orphaned artifacts.
    """
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, action_type, source_path, target_path, staging_path, state, inode "
            "FROM file_transactions WHERE state IN ('pending', 'staging_written', 'failed')"
        )
        unreconciled_txns = cursor.fetchall()

        for txn_id, action_type, source_path, target_path, staging_path, state, orig_inode in unreconciled_txns:
            staging = Path(staging_path) if staging_path else None
            source = Path(source_path)
            target = Path(target_path) if target_path else None

            if state == "pending":
                if action_type == "move_same_dev":
                    if source.exists():
                        # Crashed before replace. Clean up target placeholder.
                        if target and target.exists():
                            try:
                                target_stat = target.stat()
                                if target_stat.st_size == 0 and target_stat.st_ino != orig_inode:
                                    target.unlink()
                            except OSError:
                                pass
                        cursor.execute("UPDATE file_transactions SET state = 'reverted' WHERE id = ?", (txn_id,))
                    else:
                        # Source is gone. If target exists, we successfully committed.
                        if target and target.exists():
                            cursor.execute("UPDATE file_transactions SET state = 'committed' WHERE id = ?", (txn_id,))
                        else:
                            cursor.execute("UPDATE file_transactions SET state = 'failed' WHERE id = ?", (txn_id,))
                else:
                    # Cross-device move logic
                    if staging and staging.exists():
                        try:
                            staging.unlink()
                        except OSError:
                            pass
                    cursor.execute("UPDATE file_transactions SET state = 'reverted' WHERE id = ?", (txn_id,))

            elif state == "staging_written":
                if staging and staging.exists():
                    if source.exists():
                        # Source intact; staging is a redundant copy from an interrupted cross-device move.
                        try:
                            staging.unlink()
                        except OSError:
                            pass
                        cursor.execute("UPDATE file_transactions SET state = 'reverted' WHERE id = ?", (txn_id,))
                    else:
                        # Source is gone; staging holds the only data. Complete the commit.
                        if target and target.exists():
                            try:
                                target.unlink()
                            except OSError:
                                pass
                        try:
                            os.replace(staging, target)
                            cursor.execute("UPDATE file_transactions SET state = 'committed' WHERE id = ?", (txn_id,))
                        except OSError:
                            cursor.execute("UPDATE file_transactions SET state = 'failed' WHERE id = ?", (txn_id,))
                else:
                    # Staging is already gone. Check whether the final replace succeeded.
                    if target and target.exists():
                        cursor.execute("UPDATE file_transactions SET state = 'committed' WHERE id = ?", (txn_id,))
                    else:
                        cursor.execute("UPDATE file_transactions SET state = 'failed' WHERE id = ?", (txn_id,))

            elif state == "failed":
                # Cleanup any remaining staging file from failed operations; maintain failed state
                if staging and staging.exists():
                    try:
                        staging.unlink()
                    except OSError:
                        pass

        # Handle cross-device moves where replace completed but source wasn't unlinked
        cursor.execute(
            "SELECT id, source_path, target_path FROM file_transactions "
            "WHERE action_type = 'move_cross_dev' AND state = 'committed' AND reverted = 0"
        )
        for txn_id, source_path, target_path in cursor.fetchall():
            s, t = Path(source_path), Path(target_path)
            if s.exists() and t.exists() and s.stat().st_size == t.stat().st_size:
                try:
                    s.unlink()
                except OSError:
                    pass

        conn.commit()
    finally:
        conn.close()
