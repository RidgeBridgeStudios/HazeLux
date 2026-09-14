# Context Index

## Modules
| Path | Purpose | Key exports | Depends on |
| --- | --- | --- | --- |
| `hazelux/app.py` | CLI & GUI application entrypoint and lifecycle | `main`, `HazeluxApplication` | `hazelux.ui.window`, `hazelux.engine.runner`, `hazelux.config` |
| `hazelux/config.py` | Rule configuration management & persistence | `ConfigManager` | `hazelux.schema`, `hazelux.utils.paths` |
| `hazelux/schema.py` | JSON Schema definition & rule validation | `validate_config`, `RULE_SCHEMA` | `jsonschema` |
| `hazelux/engine/watcher.py` | Inotify monitoring with 3-stat quiescence protocol | `DirectoryWatcher` | `watchfiles` |
| `hazelux/engine/runner.py` | Rule matching coordinator & action executor | `RuleEngine` | `hazelux.engine.watcher`, `hazelux.engine.conditions`, `hazelux.engine.actions`, `hazelux.engine.loop_prevention`, `hazelux.journal.manager` |
| `hazelux/engine/conditions.py` | Condition evaluation engine | `evaluate_rule_conditions`, `evaluate_single_condition` | `exifread`, `regex` |
| `hazelux/engine/actions.py` | Safe file manipulation (move, copy, rename, trash) | `safe_relocate_file`, `ConflictStrategy` | `hazelux.journal.trash`, `shutil`, `os` |
| `hazelux/engine/loop_prevention.py` | Loop prevention & disk thrashing protection | `CooldownCache`, `DestinationEventSuppression`, `CascadingLoopTracker` | standard library |
| `hazelux/journal/manager.py` | SQLite WAL transaction journal & undo rollback | `JournalManager` | `hazelux.journal.trash`, `hazelux.journal.reconcile` |
| `hazelux/journal/reconcile.py` | Crash reconciliation on startup | `reconcile_journal_on_startup` | `hazelux.journal.trash` |
| `hazelux/journal/trash.py` | FreeDesktop trash capture and restoration | `trash_file`, `restore_from_trash` | `gio`, standard library |
| `hazelux/ui/window.py` | Main GTK4 Libadwaita desktop window | `MainWindow` | `hazelux.ui.sidebar`, `hazelux.ui.activity`, `hazelux.ui.rule_editor`, `hazelux.ui.tray` |
| `hazelux/ui/rule_editor.py` | Rule configuration & editing dialog | `RuleEditorDialog` | `hazelux.schema` |
| `hazelux/ui/sidebar.py` | Monitored folder sidebar list | `FolderSidebar` | `Adw` |
| `hazelux/ui/activity.py` | Activity log view with undo button | `ActivityView` | `hazelux.journal.manager` |
| `hazelux/ui/tray.py` | StatusNotifierItem tray icon support | `TrayIcon` | `pystray` |
| `hazelux/utils/paths.py` | Path sanitization and XDG resolution | `get_config_dir`, `get_data_dir` | standard library |
| `hazelux/utils/inotify_limits.py` | Inotify watch limits inspection & warning | `check_inotify_limits` | standard library |

## Entry points
- `hazelux/app.py:main` — CLI and desktop GUI entrypoint.
- `bin/hazelux` — Executable wrapper script.
- `hazelux/engine/runner.py:RuleEngine` — Background automation evaluation daemon.

## Data flow
1. **File Ingestion & Quiescence**: Kernel inotify event -> `DirectoryWatcher` streams events -> verifies 3 identical stats (`st_size`, `st_mtime`) over ~0.7s to prevent partial reads.
2. **Rule Evaluation**: `RuleEngine.evaluate_file()` -> checks `LoopPrevention` filters -> evaluates conditions in `conditions.py` (name, size, dates, regex, EXIF).
3. **Action Execution & Journaling**: Matches trigger `actions.py:safe_relocate_file()` -> starts transaction in `JournalManager` -> executes atomic move/copy/rename/trash -> transitions transaction to `committed` -> notifies UI.
4. **Undo Rollback**: User clicks Undo in `ActivityView` -> calls `JournalManager.revert_last_action()` -> performs inverse move or `trash.py:restore_from_trash()` -> marks transaction as `reverted`.
5. **Startup Crash Reconciliation**: Application boot -> `reconcile_journal_on_startup()` -> inspects `pending` or `staging_written` entries in `journal.db` -> restores consistent disk state.

## Risky areas
- `hazelux/engine/actions.py`: File mutation logic (atomic moves, collision strategies, cross-device copy-verify-delete). Must maintain zero data loss guarantees.
- `hazelux/journal/manager.py`: SQLite WAL transaction journal. Corruption or race conditions can break rollback capability.
- `hazelux/engine/loop_prevention.py`: Thresholds for file cooldown and event suppression. Regressions could cause disk thrashing loops.
- `hazelux/schema.py`: Breaking changes to rule JSON schema will invalidate user configuration files (`rules.json`).
