"""SQLite WAL transaction journal manager for Hazelux."""

import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from hazelux.utils.paths import get_journal_db_path

logger = logging.getLogger("hazelux.journal.manager")


class JournalManager:
    """Manages transactional history in SQLite WAL database."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_journal_db_path()
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize SQLite database with WAL mode, tables, and indexes."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_transactions (
                        id TEXT PRIMARY KEY,
                        timestamp REAL NOT NULL,
                        inode INTEGER NOT NULL,
                        action_type TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        target_path TEXT,
                        staging_path TEXT,
                        trash_uri TEXT,
                        state TEXT CHECK(state IN ('pending', 'staging_written', 'committed', 'reverted', 'failed')) NOT NULL,
                        reverted INTEGER DEFAULT 0
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_inode ON file_transactions(inode);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_state ON file_transactions(state);")
                conn.commit()
            finally:
                conn.close()

    def log_transaction(
        self,
        txn_id: str,
        inode: int,
        action_type: str,
        source_path: str,
        target_path: Optional[str] = None,
        staging_path: Optional[str] = None,
        state: str = "pending",
        trash_uri: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Register a new transaction in the journal."""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO file_transactions
                    (id, timestamp, inode, action_type, source_path, target_path, staging_path, trash_uri, state, reverted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (txn_id, ts, inode, action_type, source_path, target_path, staging_path, trash_uri, state),
                )
                conn.commit()
            finally:
                conn.close()

    def update_state(
        self,
        txn_id: str,
        state: str,
        target_path: Optional[str] = None,
        staging_path: Optional[str] = None,
        trash_uri: Optional[str] = None,
    ) -> None:
        """Update the state and optional path fields of a transaction."""
        with self._lock:
            conn = self._get_connection()
            try:
                updates = ["state = ?"]
                params: List[Any] = [state]

                if target_path is not None:
                    updates.append("target_path = ?")
                    params.append(target_path)
                if staging_path is not None:
                    updates.append("staging_path = ?")
                    params.append(staging_path)
                if trash_uri is not None:
                    updates.append("trash_uri = ?")
                    params.append(trash_uri)

                params.append(txn_id)
                query = f"UPDATE file_transactions SET {', '.join(updates)} WHERE id = ?"
                conn.execute(query, tuple(params))
                conn.commit()
            finally:
                conn.close()

    def mark_reverted(self, txn_id: str) -> None:
        """Mark a transaction as reverted."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE file_transactions SET state = 'reverted', reverted = 1 WHERE id = ?",
                    (txn_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def get_transaction(self, txn_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve single transaction by ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT * FROM file_transactions WHERE id = ?", (txn_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def get_recent_transactions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieve recent transactions ordered by timestamp descending."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    """
                    SELECT id, timestamp, inode, action_type, source_path, target_path, staging_path, trash_uri, state, reverted
                    FROM file_transactions
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def prune_and_vacuum(self, now: Optional[float] = None) -> None:
        """Prune stale transactions and truncate WAL."""
        current_time = now if now is not None else time.time()
        cutoff_committed = current_time - (30 * 86400.0)  # 30 days
        cutoff_reverted = current_time - (90 * 86400.0)   # 90 days

        with self._lock:
            conn = self._get_connection()
            try:
                # Delete committed & non-reverted older than 30 days
                conn.execute(
                    "DELETE FROM file_transactions WHERE state = 'committed' AND reverted = 0 AND timestamp < ?",
                    (cutoff_committed,),
                )
                # Delete reverted older than 90 days
                conn.execute(
                    "DELETE FROM file_transactions WHERE state = 'reverted' AND timestamp < ?",
                    (cutoff_reverted,),
                )
                conn.commit()

                # Execute WAL checkpoint TRUNCATE
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception as e:
                logger.error("Error during journal pruning and vacuum: %s", e)
            finally:
                conn.close()
