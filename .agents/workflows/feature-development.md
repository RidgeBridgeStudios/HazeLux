# Feature development

1. Read `AGENTS.md` and `.agents/context-index.md`.
2. Identify target files using the Task → File Map.
3. Formulate a structured plan before editing code.
4. Write a failing unit or integration test first (`tests/test_*.py`).
5. Implement the minimal working change adhering to project patterns and YAGNI.
6. Verify changes with `pytest -v tests`.
7. Review `git diff` to confirm zero unintended modifications or transient files.
8. Summarize changes and provide verification results.
