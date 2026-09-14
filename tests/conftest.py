"""Pytest test configuration and fixtures for Hazelux."""

import os
from pathlib import Path
import shutil
import tempfile
from typing import Generator
import pytest

from hazelux.config import ConfigManager
from hazelux.journal.manager import JournalManager


@pytest.fixture
def tmp_dir() -> Generator[Path, None, None]:
    """Provide clean temporary directory fixture."""
    td = tempfile.mkdtemp(prefix="hazelux_test_")
    p = Path(td)
    yield p
    shutil.rmtree(td, ignore_errors=True)


@pytest.fixture
def journal_mgr(tmp_dir: Path) -> JournalManager:
    """Provide JournalManager pointing to temporary database."""
    db_path = tmp_dir / "test_journal.db"
    return JournalManager(db_path=db_path)


@pytest.fixture
def config_mgr(tmp_dir: Path) -> ConfigManager:
    """Provide ConfigManager pointing to temporary rules.json."""
    rules_path = tmp_dir / "rules.json"
    return ConfigManager(rules_path=rules_path)
