"""Rule execution orchestrator and deterministic evaluation state machine."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from hazelux.config import ConfigManager
from hazelux.engine.actions import safe_copy_file, safe_relocate_file, safe_rename_file, safe_trash_file
from hazelux.engine.conditions import evaluate_conditions
from hazelux.engine.loop_prevention import CascadingLoopTracker, CooldownCache, DestinationEventSuppression
from hazelux.engine.watcher import WatcherManager
from hazelux.journal.manager import JournalManager

logger = logging.getLogger("hazelux.engine.runner")


class RuleEngine:
    """Evaluates declarative rules against filesystem events with loop prevention."""

    def __init__(
        self,
        config_manager: ConfigManager,
        journal_manager: JournalManager,
        on_loop_suspect: Optional[Callable[[int, Path], None]] = None,
        on_rule_action_executed: Optional[Callable[[Dict[str, Any], Path, str], None]] = None,
        max_workers: int = 4,
    ):
        self.config_manager = config_manager
        self.journal_manager = journal_manager
        self.on_rule_action_executed = on_rule_action_executed
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="hazelux-worker")

        # Loop prevention structures
        self.cooldown_cache = CooldownCache(default_ttl=10.0)
        self.destination_suppression = DestinationEventSuppression(default_ttl=15.0)
        self.loop_tracker = CascadingLoopTracker(
            window_seconds=60.0,
            max_actions=5,
            on_loop_detected=on_loop_suspect,
        )

        self.watcher = WatcherManager(
            on_file_quiescent=self._on_file_quiescent,
            on_enospc_error=self._on_enospc,
        )
        self._is_paused = False

    def pause(self) -> None:
        self._is_paused = True
        logger.info("Rule execution paused.")

    def resume(self) -> None:
        self._is_paused = False
        logger.info("Rule execution resumed.")

    def is_paused(self) -> bool:
        return self._is_paused

    def _on_enospc(self, path: str) -> None:
        logger.error("ENOSPC encountered while watching %s", path)

    async def _on_file_quiescent(self, path: Path) -> None:
        """Handle quiescent file event from watcher."""
        if self._is_paused:
            return
        await asyncio.to_thread(self.process_file, path)

    def get_monitored_directories(self) -> Set[str]:
        """Return set of normalized directories actively targeted by enabled rules."""
        dirs = set()
        for rule in self.config_manager.get_rules():
            if rule.get("metadata", {}).get("enabled", True):
                for p in rule.get("triggers", {}).get("paths", []):
                    norm = str(Path(p).expanduser().resolve())
                    dirs.add(norm)
        return dirs

    def _get_matching_rules_for_path(self, path: Path) -> List[Dict[str, Any]]:
        """Find enabled rules applicable to this path, sorted ascending by priority."""
        rules = self.config_manager.get_rules()
        applicable = []
        canonical_parent = str(path.parent.resolve())

        for r in rules:
            if not r.get("metadata", {}).get("enabled", True):
                continue

            triggers = r.get("triggers", {})
            recursive = triggers.get("recursive", False)
            trigger_paths = [str(Path(p).expanduser().resolve()) for p in triggers.get("paths", [])]

            matches_trigger = False
            for tp in trigger_paths:
                if recursive:
                    try:
                        path.relative_to(Path(tp))
                        matches_trigger = True
                        break
                    except ValueError:
                        pass
                else:
                    if canonical_parent == tp:
                        matches_trigger = True
                        break

            if matches_trigger:
                applicable.append(r)

        # Sort ascending by priority integer (0, 1, 2...)
        applicable.sort(key=lambda x: int(x.get("metadata", {}).get("priority", 0)))
        return applicable

    def process_file(self, path: Path) -> None:
        """Evaluate rules against a single file path in worker thread."""
        if not path.exists() or path.is_dir():
            return

        try:
            st = path.stat()
            inode = st.st_ino
        except OSError:
            return

        # 1. Check CooldownCache and DestinationEventSuppression
        if self.cooldown_cache.is_suppressed(path, inode):
            logger.debug("Path or inode %s (%d) is in cooldown; event discarded.", path, inode)
            return

        if self.destination_suppression.is_suppressed(path):
            logger.debug("Path %s is in destination suppression; event discarded.", path)
            return

        # 2. Check CascadingLoopTracker
        if self.loop_tracker.is_suspended(inode):
            logger.warning("File %s (inode %d) is suspended as a Loop Suspect; skipping.", path, inode)
            return

        matching_rules = self._get_matching_rules_for_path(path)
        current_path = path

        monitored_dirs = self.get_monitored_directories()

        for rule in matching_rules:
            if not current_path.exists():
                break

            conditions = rule.get("conditions", {})
            if not evaluate_conditions(current_path, conditions):
                continue

            meta = rule.get("metadata", {})
            rule_name = meta.get("name", "unnamed")
            stop_on_match = bool(meta.get("stop_on_match", False))
            actions = rule.get("actions", [])

            is_terminal = False

            for action in actions:
                if not current_path.exists():
                    break

                # Record action against loop tracker
                if not self.loop_tracker.record_action(inode, current_path):
                    return  # Cascading loop threshold exceeded!

                action_type = action.get("type")
                strategy = action.get("conflict_strategy", "rename_counter")

                if action_type == "move":
                    dest_dir = Path(action["destination"]).expanduser().resolve()
                    dest_name = current_path.name
                    new_path = safe_relocate_file(
                        source_path=current_path,
                        target_dir=dest_dir,
                        target_name=dest_name,
                        strategy=strategy,
                        journal_manager=self.journal_manager,
                    )
                    if new_path:
                        # Register cooldown
                        try:
                            new_st = new_path.stat()
                            self.cooldown_cache.add(new_path, new_st.st_ino, ttl=10.0)
                        except OSError:
                            self.cooldown_cache.add(new_path, ttl=10.0)

                        # Register destination suppression if dest_dir is actively monitored
                        if str(dest_dir) in monitored_dirs:
                            self.destination_suppression.add(new_path, ttl=15.0)

                        current_path = new_path
                        if self.on_rule_action_executed:
                            self.on_rule_action_executed(rule, current_path, "move")

                    is_terminal = True

                elif action_type == "copy":
                    dest_dir = Path(action["destination"]).expanduser().resolve()
                    dest_name = current_path.name
                    copied_path = safe_copy_file(
                        source_path=current_path,
                        target_dir=dest_dir,
                        target_name=dest_name,
                        strategy=strategy,
                        journal_manager=self.journal_manager,
                    )
                    if copied_path:
                        try:
                            cop_st = copied_path.stat()
                            self.cooldown_cache.add(copied_path, cop_st.st_ino, ttl=10.0)
                        except OSError:
                            self.cooldown_cache.add(copied_path, ttl=10.0)

                        if str(dest_dir) in monitored_dirs:
                            self.destination_suppression.add(copied_path, ttl=15.0)

                        if self.on_rule_action_executed:
                            self.on_rule_action_executed(rule, copied_path, "copy")

                elif action_type == "rename":
                    pattern = action["pattern"]
                    new_path = safe_rename_file(
                        source_path=current_path,
                        pattern=pattern,
                        strategy=strategy,
                        journal_manager=self.journal_manager,
                    )
                    if new_path:
                        try:
                            ren_st = new_path.stat()
                            self.cooldown_cache.add(new_path, ren_st.st_ino, ttl=10.0)
                        except OSError:
                            self.cooldown_cache.add(new_path, ttl=10.0)

                        current_path = new_path
                        if self.on_rule_action_executed:
                            self.on_rule_action_executed(rule, current_path, "rename")

                elif action_type == "trash":
                    safe_trash_file(
                        source_path=current_path,
                        journal_manager=self.journal_manager,
                    )
                    if self.on_rule_action_executed:
                        self.on_rule_action_executed(rule, current_path, "trash")
                    is_terminal = True
                    break

            if is_terminal:
                logger.debug("Terminal action completed on %s by rule %s; halting.", path, rule_name)
                break

            if stop_on_match:
                logger.debug("stop_on_match=True for rule %s; halting evaluation.", rule_name)
                break

    def run_rules_on_directory(self, directory: Path, recursive: bool = True) -> int:
        """Synchronously scan a directory and evaluate rules on existing files (manual run)."""
        count = 0
        if not directory.is_dir():
            return 0

        files_to_process = []
        if recursive:
            for root, _, files in os.walk(directory):
                for f in files:
                    if not f.startswith(".staging_"):
                        files_to_process.append(Path(root) / f)
        else:
            for item in directory.iterdir():
                if item.is_file() and not item.name.startswith(".staging_"):
                    files_to_process.append(item)

        for p in files_to_process:
            self.process_file(p)
            count += 1
        return count
