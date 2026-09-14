PRAGMA journal_mode = WAL;

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

CREATE INDEX IF NOT EXISTS idx_inode ON file_transactions(inode);
CREATE INDEX IF NOT EXISTS idx_state ON file_transactions(state);
