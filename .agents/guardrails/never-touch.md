# Never touch

- Generated build files: `_build/`, `debian/.debhelper/`, `debian/hazelux/`, `*.egg-info/`, `build/`, `dist/`.
- Runtime user databases and state: `rules.json`, `journal.db`, `journal.db-wal`, `journal.db-shm`, `.staging_*`.
- Python cache and virtual environment: `__pycache__/`, `.pytest_cache/`, `.venv/`, `env/`.
- Debian package artifacts: `*.deb`, `*.build`, `*.buildinfo`, `*.changes`.
- Secrets or credentials: `.env`, `*.pem`, `*.key`, tokens.
