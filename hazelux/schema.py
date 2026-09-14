"""JSON Schema definition and validation utilities for Hazelux rule configurations."""

from typing import Any, Dict, List, Tuple
import jsonschema
from jsonschema import Draft202012Validator

RULE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "HazeluxRuleConfig",
    "type": "object",
    "required": ["metadata", "triggers", "conditions", "actions"],
    "additionalProperties": False,
    "properties": {
        "metadata": {
            "type": "object",
            "required": ["id", "name", "enabled", "priority", "stop_on_match"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "name": {"type": "string", "minLength": 1, "maxLength": 128},
                "enabled": {"type": "boolean"},
                "priority": {"type": "integer", "minimum": 0},
                "stop_on_match": {"type": "boolean"},
            },
        },
        "triggers": {
            "type": "object",
            "required": ["paths", "recursive"],
            "additionalProperties": False,
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "recursive": {"type": "boolean"},
            },
        },
        "conditions": {
            "type": "object",
            "required": ["mode", "rules"],
            "additionalProperties": False,
            "properties": {
                "mode": {"type": "string", "enum": ["all", "any", "none"]},
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field", "operator", "value"],
                        "additionalProperties": False,
                        "properties": {
                            "field": {
                                "type": "string",
                                "enum": [
                                    "name",
                                    "extension",
                                    "size_bytes",
                                    "date_modified",
                                    "date_created",
                                    "exif_date",
                                ],
                            },
                            "operator": {
                                "type": "string",
                                "enum": [
                                    "is",
                                    "is_not",
                                    "contains",
                                    "does_not_contain",
                                    "starts_with",
                                    "ends_with",
                                    "matches_regex",
                                    "greater_than",
                                    "less_than",
                                ],
                            },
                            "value": {
                                "type": ["string", "number"],
                            },
                            "case_insensitive": {
                                "type": "boolean",
                                "default": False,
                            },
                        },
                    },
                    "minItems": 1,
                },
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type"],
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["move", "copy", "rename", "trash"],
                    },
                    "destination": {"type": "string"},
                    "pattern": {"type": "string"},
                    "conflict_strategy": {
                        "type": "string",
                        "enum": ["rename_counter", "skip", "overwrite"],
                    },
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {
                                "type": {"enum": ["move", "copy", "rename"]}
                            }
                        },
                        "then": {"required": ["conflict_strategy"]},
                    },
                    {
                        "if": {"properties": {"type": {"const": "rename"}}},
                        "then": {
                            "required": ["pattern"],
                            "not": {"required": ["destination"]},
                        },
                    },
                    {
                        "if": {
                            "properties": {"type": {"enum": ["move", "copy"]}}
                        },
                        "then": {
                            "required": ["destination"],
                            "not": {"required": ["pattern"]},
                        },
                    },
                    {
                        "if": {"properties": {"type": {"const": "trash"}}},
                        "then": {
                            "not": {
                                "anyOf": [
                                    {"required": ["destination"]},
                                    {"required": ["pattern"]},
                                ]
                            }
                        },
                    },
                ],
            },
            "minItems": 1,
        },
    },
}

RULES_FILE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "HazeluxRulesFile",
    "type": "object",
    "required": ["version", "rules"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "integer", "minimum": 1},
        "rules": {
            "type": "array",
            "items": RULE_SCHEMA,
        },
    },
}

_rule_validator = Draft202012Validator(RULE_SCHEMA)
_rules_file_validator = Draft202012Validator(RULES_FILE_SCHEMA)


def validate_rule(rule_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a single rule against RULE_SCHEMA."""
    errors = [err.message for err in _rule_validator.iter_errors(rule_data)]
    return (len(errors) == 0, errors)


def validate_config(config_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate the complete rules configuration file."""
    # Allow either a list of rules or an object with {version: 1, rules: [...]}
    if isinstance(config_data, list):
        all_errors = []
        for idx, rule in enumerate(config_data):
            valid, errs = validate_rule(rule)
            if not valid:
                all_errors.extend([f"Rule #{idx} ({rule.get('metadata', {}).get('name', 'unnamed')}): {e}" for e in errs])
        return (len(all_errors) == 0, all_errors)

    errors = [err.message for err in _rules_file_validator.iter_errors(config_data)]
    return (len(errors) == 0, errors)
