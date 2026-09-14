"""Configuration manager for Hazelux rules with atomic persistence and validation."""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from hazelux.schema import validate_config, validate_rule
from hazelux.utils.paths import get_rules_backup_path, get_rules_path

logger = logging.getLogger("hazelux.config")


class ConfigValidationError(Exception):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ConfigManager:
    """Manages rules.json lifecycle with atomic updates and backup retention."""

    def __init__(self, rules_path: Optional[Path] = None):
        self.rules_path = rules_path or get_rules_path()
        self.backup_path = self.rules_path.with_suffix(".json.bak")
        self.config: Dict[str, Any] = {"version": 1, "rules": []}
        self.is_valid: bool = True
        self.validation_errors: List[str] = []
        self._reload_callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def register_reload_callback(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for when rules are reloaded/updated."""
        self._reload_callbacks.append(cb)

    def _notify_reloaded(self) -> None:
        for cb in self._reload_callbacks:
            try:
                cb(self.config)
            except Exception as e:
                logger.error("Error in reload callback: %s", e)

    def load(self) -> Tuple[bool, List[str]]:
        """Load and validate rules.json.

        Returns:
            (is_valid, error_list)
        """
        if not self.rules_path.exists():
            # Initial default empty configuration
            self.config = {"version": 1, "rules": []}
            self.is_valid = True
            self.validation_errors = []
            self.save(self.config)
            return (True, [])

        try:
            raw_text = self.rules_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as e:
            self.is_valid = False
            self.validation_errors = [f"JSON syntax error in rules.json: {e}"]
            logger.error("Failed to parse %s: %s", self.rules_path, e)
            return (False, self.validation_errors)

        valid, errors = validate_config(data)
        if not valid:
            self.is_valid = False
            self.validation_errors = errors
            logger.warning("Rules configuration failed validation: %s", errors)
            return (False, errors)

        self.config = data
        self.is_valid = True
        self.validation_errors = []
        self._notify_reloaded()
        return (True, [])

    def save(self, config_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Atomically validate, backup, and save configuration."""
        valid, errors = validate_config(config_data)
        if not valid:
            raise ConfigValidationError(errors)

        # Ensure parent directory exists
        self.rules_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Backup existing valid configuration before overwrite
        if self.rules_path.exists():
            try:
                shutil.copy2(self.rules_path, self.backup_path)
            except OSError as e:
                logger.warning("Could not create backup %s: %s", self.backup_path, e)

        # 2. Write to temporary file with fsync
        tmp_path = self.rules_path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # 3. Atomic replace
            os.replace(tmp_path, self.rules_path)
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            logger.error("Failed atomic write to %s: %s", self.rules_path, e)
            raise

        self.config = config_data
        self.is_valid = True
        self.validation_errors = []
        self._notify_reloaded()
        return (True, [])

    def revert_to_backup(self) -> Tuple[bool, List[str]]:
        """Revert rules.json to the last known good rules.json.bak."""
        if not self.backup_path.exists():
            return (False, ["No backup file (rules.json.bak) found."])

        try:
            backup_text = self.backup_path.read_text(encoding="utf-8")
            backup_data = json.loads(backup_text)
            valid, errors = validate_config(backup_data)
            if not valid:
                return (False, [f"Backup file invalid: {err}" for err in errors])

            # Replace current rules.json with backup
            shutil.copy2(self.backup_path, self.rules_path)
            self.config = backup_data
            self.is_valid = True
            self.validation_errors = []
            self._notify_reloaded()
            return (True, [])
        except Exception as e:
            logger.error("Failed reverting to backup: %s", e)
            return (False, [f"Failed to restore backup: {e}"])

    def get_rules(self) -> List[Dict[str, Any]]:
        """Return the list of rules."""
        if isinstance(self.config, list):
            return self.config
        return self.config.get("rules", [])

    def get_watched_folders(self) -> List[str]:
        """Extract unique watched folder paths from enabled rules."""
        folders = set()
        for rule in self.get_rules():
            if rule.get("metadata", {}).get("enabled", True):
                paths = rule.get("triggers", {}).get("paths", [])
                for p in paths:
                    folders.add(os.path.abspath(os.path.expanduser(p)))
        return sorted(list(folders))
