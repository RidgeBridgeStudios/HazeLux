# Always run before committing

- Test command: `pytest -v tests` (must pass 100% cleanly).
- Specific subsystem validation:
  - Conditions & regex engine: `pytest tests/test_conditions.py`
  - Safe file relocation: `pytest tests/test_relocation.py`
  - Journal & crash recovery: `pytest tests/test_reconcile_and_trash.py` tests/test_journal_retention.py
  - Schema consistency: `pytest tests/test_schema.py`
- Inspect git status: `git status --short` (ensure no transient runtime files or caches staged).
