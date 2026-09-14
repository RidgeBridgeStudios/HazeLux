# AGENTS.md

> Native Linux desktop file automation daemon and GTK4/Libadwaita configuration utility.

## Build
```bash
pip install -e .
# Meson: meson setup _build && ninja -C _build
```

## Test
```bash
pytest -v tests
```

## Lint / Format
None configured in project. (unverified)

## Structure
```
hazelux/
  app.py       # CLI entrypoint & application lifecycle
  config.py    # Configuration & JSON schema validation
  engine/      # Inotify watcher, conditions, actions, loop prevention
  journal/     # SQLite WAL transaction journal & undo manager
  ui/          # GTK4 / Libadwaita desktop interface
tests/         # Pytest test suites
```

## Conventions
- Wrap file operations in `JournalManager` transactions for undo support.
- Files must pass 3-stat quiescence check before action execution.
- Maintain GTK4 / Libadwaita PyGObject patterns; never block the main loop.

## Task → File Map
| Task | File(s) |
| --- | --- |
| Add/edit rule conditions | `hazelux/engine/conditions.py` |
| Add/edit file actions | `hazelux/engine/actions.py` |
| Loop/thrash limits | `hazelux/engine/loop_prevention.py` |
| Rule schema validation | `hazelux/schema.py` |
| Transaction journal / undo | `hazelux/journal/manager.py`, `hazelux/journal/schema.sql` |
| Desktop UI & dialogs | `hazelux/ui/window.py`, `hazelux/ui/rule_editor.py` |

## Boundaries
- Do not edit generated `_build/`, `debian/.debhelper/`, or `.venv/`.
- Do not bypass `JournalManager` for filesystem mutations.
- Do not modify `hazelux/journal/schema.sql` without SQLite WAL migration considerations.

## Gotchas
- Requires system site-packages for PyGObject / Libadwaita (`python3 -m venv --system-site-packages .venv`).
- Quiescence check waits ~0.7s for 3 identical stats before acting on files.
