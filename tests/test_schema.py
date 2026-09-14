"""Unit tests for Hazelux rule JSON schema validation."""

import uuid
import pytest
from hazelux.schema import validate_config, validate_rule


def test_valid_rule():
    rule = {
        "metadata": {
            "id": str(uuid.uuid4()),
            "name": "Move PDF receipts",
            "enabled": True,
            "priority": 0,
            "stop_on_match": True,
        },
        "triggers": {
            "paths": ["/home/user/Downloads"],
            "recursive": False,
        },
        "conditions": {
            "mode": "all",
            "rules": [
                {
                    "field": "extension",
                    "operator": "is",
                    "value": "pdf",
                    "case_insensitive": True,
                },
                {
                    "field": "size_bytes",
                    "operator": "greater_than",
                    "value": 1024,
                },
            ],
        },
        "actions": [
            {
                "type": "move",
                "destination": "/home/user/Documents/Receipts",
                "conflict_strategy": "rename_counter",
            }
        ],
    }
    valid, errors = validate_rule(rule)
    assert valid, f"Rule should be valid, got: {errors}"


def test_rename_action_schema():
    rule = {
        "metadata": {
            "id": str(uuid.uuid4()),
            "name": "Rename invoices",
            "enabled": True,
            "priority": 1,
            "stop_on_match": False,
        },
        "triggers": {
            "paths": ["/home/user/Downloads"],
            "recursive": True,
        },
        "conditions": {
            "mode": "any",
            "rules": [
                {
                    "field": "name",
                    "operator": "starts_with",
                    "value": "Invoice",
                }
            ],
        },
        "actions": [
            {
                "type": "rename",
                "pattern": "{date}_{name}",
                "conflict_strategy": "rename_counter",
            }
        ],
    }
    valid, errors = validate_rule(rule)
    assert valid, f"Rename rule should be valid, got: {errors}"


def test_trash_action_schema():
    rule = {
        "metadata": {
            "id": str(uuid.uuid4()),
            "name": "Trash old logs",
            "enabled": True,
            "priority": 2,
            "stop_on_match": False,
        },
        "triggers": {
            "paths": ["/home/user/Logs"],
            "recursive": False,
        },
        "conditions": {
            "mode": "none",
            "rules": [
                {
                    "field": "name",
                    "operator": "contains",
                    "value": "keep",
                }
            ],
        },
        "actions": [
            {
                "type": "trash",
            }
        ],
    }
    valid, errors = validate_rule(rule)
    assert valid, f"Trash rule should be valid, got: {errors}"


def test_invalid_action_constraints():
    # 1. Move action missing destination
    bad_move = {
        "metadata": {
            "id": str(uuid.uuid4()),
            "name": "Bad Move",
            "enabled": True,
            "priority": 0,
            "stop_on_match": False,
        },
        "triggers": {"paths": ["/tmp"], "recursive": False},
        "conditions": {"mode": "all", "rules": [{"field": "name", "operator": "is", "value": "a"}]},
        "actions": [{"type": "move", "conflict_strategy": "overwrite"}],
    }
    valid, errors = validate_rule(bad_move)
    assert not valid

    # 2. Rename action containing destination (forbidden)
    bad_rename = {
        "metadata": {
            "id": str(uuid.uuid4()),
            "name": "Bad Rename",
            "enabled": True,
            "priority": 0,
            "stop_on_match": False,
        },
        "triggers": {"paths": ["/tmp"], "recursive": False},
        "conditions": {"mode": "all", "rules": [{"field": "name", "operator": "is", "value": "a"}]},
        "actions": [{"type": "rename", "pattern": "abc", "destination": "/dest", "conflict_strategy": "overwrite"}],
    }
    valid, errors = validate_rule(bad_rename)
    assert not valid

    # 3. Trash action containing destination or pattern (forbidden)
    bad_trash = {
        "metadata": {
            "id": str(uuid.uuid4()),
            "name": "Bad Trash",
            "enabled": True,
            "priority": 0,
            "stop_on_match": False,
        },
        "triggers": {"paths": ["/tmp"], "recursive": False},
        "conditions": {"mode": "all", "rules": [{"field": "name", "operator": "is", "value": "a"}]},
        "actions": [{"type": "trash", "destination": "/somewhere"}],
    }
    valid, errors = validate_rule(bad_trash)
    assert not valid


def test_validate_config_file():
    cfg = {
        "version": 1,
        "rules": [
            {
                "metadata": {
                    "id": str(uuid.uuid4()),
                    "name": "Rule 1",
                    "enabled": True,
                    "priority": 0,
                    "stop_on_match": False,
                },
                "triggers": {"paths": ["/tmp"], "recursive": False},
                "conditions": {"mode": "all", "rules": [{"field": "extension", "operator": "is", "value": "txt"}]},
                "actions": [{"type": "copy", "destination": "/tmp/dest", "conflict_strategy": "skip"}],
            }
        ],
    }
    valid, errors = validate_config(cfg)
    assert valid, f"Config should be valid: {errors}"
