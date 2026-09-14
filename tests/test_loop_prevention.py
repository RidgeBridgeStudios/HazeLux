"""Unit tests for loop prevention, cooldown caching, and cascading threshold protection."""

import os
from pathlib import Path
import time
import pytest

from hazelux.config import ConfigManager
from hazelux.engine.loop_prevention import CascadingLoopTracker, CooldownCache, DestinationEventSuppression
from hazelux.engine.runner import RuleEngine
from hazelux.journal.manager import JournalManager


def test_cooldown_cache_ttl(tmp_dir: Path):
    cache = CooldownCache(default_ttl=0.2)
    p = tmp_dir / "file.txt"
    p.write_text("data")
    inode = p.stat().st_ino

    # Add to cache
    cache.add(p, inode=inode, ttl=0.2)
    assert cache.is_suppressed(p, inode)

    # Wait for TTL expiration
    time.sleep(0.25)
    assert not cache.is_suppressed(p, inode)


def test_destination_suppression(tmp_dir: Path):
    dest_supp = DestinationEventSuppression(default_ttl=0.2)
    p = tmp_dir / "target_folder" / "moved_file.txt"

    dest_supp.add(p, ttl=0.2)
    assert dest_supp.is_suppressed(p)

    time.sleep(0.25)
    assert not dest_supp.is_suppressed(p)


def test_cascading_loop_threshold_isolation(tmp_dir: Path):
    loop_detected = []

    def on_loop(ino, p):
        loop_detected.append((ino, p))

    tracker = CascadingLoopTracker(window_seconds=60.0, max_actions=5, on_loop_detected=on_loop)
    p = tmp_dir / "looping_file.txt"
    p.write_text("content")
    inode = p.stat().st_ino

    # First 5 actions should succeed
    for i in range(5):
        allowed = tracker.record_action(inode, p)
        assert allowed is True, f"Action {i+1} should be allowed"

    # 6th action should exceed threshold and suspend
    exceeded = tracker.record_action(inode, p)
    assert exceeded is False, "6th action must be blocked"
    assert tracker.is_suspended(inode)
    assert len(loop_detected) == 1
    assert loop_detected[0][0] == inode

    # Subsequent actions remain blocked
    assert tracker.record_action(inode, p) is False


def test_circular_rules_cooldown_suppression(tmp_dir: Path, config_mgr: ConfigManager, journal_mgr: JournalManager):
    """Simulate reciprocal rules (Folder A -> Folder B and Folder B -> Folder A)."""
    dir_a = tmp_dir / "folder_a"
    dir_b = tmp_dir / "folder_b"
    dir_a.mkdir()
    dir_b.mkdir()

    # Rule 1: Folder A moves to Folder B
    rule_1 = {
        "metadata": {"id": "r1", "name": "A to B", "enabled": True, "priority": 0, "stop_on_match": True},
        "triggers": {"paths": [str(dir_a)], "recursive": False},
        "conditions": {"mode": "all", "rules": [{"field": "extension", "operator": "is", "value": "txt"}]},
        "actions": [{"type": "move", "destination": str(dir_b), "conflict_strategy": "overwrite"}],
    }

    # Rule 2: Folder B moves to Folder A
    rule_2 = {
        "metadata": {"id": "r2", "name": "B to A", "enabled": True, "priority": 0, "stop_on_match": True},
        "triggers": {"paths": [str(dir_b)], "recursive": False},
        "conditions": {"mode": "all", "rules": [{"field": "extension", "operator": "is", "value": "txt"}]},
        "actions": [{"type": "move", "destination": str(dir_a), "conflict_strategy": "overwrite"}],
    }

    config_mgr.save({"version": 1, "rules": [rule_1, rule_2]})

    engine = RuleEngine(config_manager=config_mgr, journal_manager=journal_mgr)

    # Place file in Folder A and process
    test_file = dir_a / "pingpong.txt"
    test_file.write_text("loop test")

    engine.process_file(test_file)

    # File should have moved to Folder B
    file_in_b = dir_b / "pingpong.txt"
    assert file_in_b.exists()
    assert not test_file.exists()

    # Now simulate the inotify event arriving for Folder B.
    # Because of CooldownCache and DestinationEventSuppression, it must be suppressed and NOT move back to A!
    engine.process_file(file_in_b)

    # Assert it stayed in Folder B (did not ping-pong back to A)
    assert file_in_b.exists()
    assert not (dir_a / "pingpong.txt").exists()
