"""XDG and container path resolution utilities for Hazelux."""

import os
from pathlib import Path


def is_flatpak() -> bool:
    """Check if running inside Flatpak sandbox."""
    return Path("/.flatpak-info").exists() or "FLATPAK_ID" in os.environ


def get_config_dir() -> Path:
    """Return canonical config directory for Hazelux."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"

    config_dir = base / "hazelux"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_rules_path() -> Path:
    """Return path to rules.json."""
    return get_config_dir() / "rules.json"


def get_rules_backup_path() -> Path:
    """Return path to rules.json.bak."""
    return get_config_dir() / "rules.json.bak"


def get_journal_db_path() -> Path:
    """Return path to journal.db."""
    return get_config_dir() / "journal.db"


def get_trash_dir() -> Path:
    """Return path to FreeDesktop Trash directory."""
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        base = Path(xdg_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "Trash"


def get_autostart_path() -> Path:
    """Return path to autostart desktop entry."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"
    autostart_dir = base / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    return autostart_dir / "io.github.hazelux.Hazelux.desktop"
