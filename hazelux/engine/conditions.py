"""Condition evaluation and type coercion engine for Hazelux."""

from datetime import datetime
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional, Union

import exifread
import regex

logger = logging.getLogger("hazelux.engine.conditions")

REGEX_TIMEOUT_SECONDS = 0.100  # 100 milliseconds timeout per match


def _match_string(
    actual: str,
    operator: str,
    expected: str,
    case_insensitive: bool = False,
) -> bool:
    """Evaluate string conditions with case-sensitivity control and regex safety."""
    if case_insensitive:
        act = actual.lower()
        exp = expected.lower()
    else:
        act = actual
        exp = expected

    if operator == "is":
        return act == exp
    elif operator == "is_not":
        return act != exp
    elif operator == "contains":
        return exp in act
    elif operator == "does_not_contain":
        return exp not in act
    elif operator == "starts_with":
        return act.startswith(exp)
    elif operator == "ends_with":
        return act.endswith(exp)
    elif operator == "matches_regex":
        flags = regex.IGNORECASE if case_insensitive else 0
        try:
            pattern = regex.compile(expected, flags=flags)
            match = pattern.search(actual, timeout=REGEX_TIMEOUT_SECONDS)
            return match is not None
        except TimeoutError:
            logger.warning(
                "Regex pattern '%s' timed out after %d ms on input '%s'",
                expected,
                int(REGEX_TIMEOUT_SECONDS * 1000),
                actual[:50],
            )
            return False
        except regex.error as err:
            logger.warning("Invalid regex pattern '%s': %s", expected, err)
            return False

    logger.warning("Unsupported string operator: %s", operator)
    return False


def _match_numeric(actual: Union[int, float], operator: str, expected: Union[int, float]) -> bool:
    """Evaluate numeric conditions."""
    if operator == "is":
        return actual == expected
    elif operator == "greater_than":
        return actual > expected
    elif operator == "less_than":
        return actual < expected
    logger.warning("Unsupported numeric operator: %s", operator)
    return False


def _extract_exif_timestamp(path: Path) -> Optional[float]:
    """Extract DateTimeOriginal from EXIF headers using exifread."""
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
            dt_tag = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
            if dt_tag:
                # Format is typically "YYYY:MM:DD HH:MM:SS"
                dt_str = str(dt_tag).strip()
                dt_obj = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                return dt_obj.timestamp()
    except Exception as e:
        logger.debug("Failed to extract EXIF from %s: %s", path, e)
    return None


def evaluate_single_condition(path: Path, rule: Dict[str, Any]) -> bool:
    """Evaluate a single rule condition against a file path.

    Returns False if file is inaccessible or condition is unmet.
    """
    field = rule.get("field")
    operator = rule.get("operator")
    expected_value = rule.get("value")
    case_insensitive = bool(rule.get("case_insensitive", False))

    if not path.exists():
        return False

    try:
        st = path.stat()
    except OSError as e:
        logger.debug("Stat error on %s: %s", path, e)
        return False

    if field == "name":
        actual = path.stem
        return _match_string(actual, operator, str(expected_value), case_insensitive)

    elif field == "extension":
        actual = path.suffix.lstrip(".")
        expected = str(expected_value).lstrip(".")
        return _match_string(actual, operator, expected, case_insensitive)

    elif field == "size_bytes":
        try:
            expected_num = int(expected_value)
        except (ValueError, TypeError):
            logger.warning("Non-integer size_bytes value: %r", expected_value)
            return False
        return _match_numeric(st.st_size, operator, expected_num)

    elif field == "date_modified":
        try:
            threshold_seconds = float(expected_value)
        except (ValueError, TypeError):
            return False
        offset = time.time() - st.st_mtime
        return _match_numeric(offset, operator, threshold_seconds)

    elif field == "date_created":
        # Check st_birthtime via Python 3.12+ os.stat() / statx
        if not hasattr(st, "st_birthtime"):
            logger.warning("Filesystem or OS does not expose st_birthtime for %s; condition is False", path)
            return False

        birthtime = getattr(st, "st_birthtime")
        if birthtime is None or birthtime <= 0:
            logger.warning("st_birthtime unavailable or invalid for %s; condition is False", path)
            return False

        try:
            threshold_seconds = float(expected_value)
        except (ValueError, TypeError):
            return False

        offset = time.time() - birthtime
        return _match_numeric(offset, operator, threshold_seconds)

    elif field == "exif_date":
        exif_ts = _extract_exif_timestamp(path)
        if exif_ts is None:
            return False

        # Support numeric seconds offset or ISO date comparison
        if isinstance(expected_value, (int, float)):
            offset = time.time() - exif_ts
            return _match_numeric(offset, operator, float(expected_value))
        elif isinstance(expected_value, str):
            try:
                # Try ISO string format
                expected_dt = datetime.fromisoformat(expected_value)
                expected_ts = expected_dt.timestamp()
                return _match_numeric(exif_ts, operator, expected_ts)
            except Exception:
                logger.warning("Cannot parse exif_date expected value: %r", expected_value)
                return False

    logger.warning("Unknown condition field: %s", field)
    return False


def evaluate_conditions(path: Path, conditions: Dict[str, Any]) -> bool:
    """Evaluate condition group (all / any / none) against a file path."""
    mode = conditions.get("mode", "all")
    rules = conditions.get("rules", [])
    if not rules:
        return False

    results = [evaluate_single_condition(path, r) for r in rules]

    if mode == "all":
        return all(results)
    elif mode == "any":
        return any(results)
    elif mode == "none":
        return not any(results)

    logger.warning("Unknown conditions mode: %s", mode)
    return False
