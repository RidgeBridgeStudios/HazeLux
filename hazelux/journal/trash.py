"""FreeDesktop Trash integration with transactional tracking and restoration."""

import configparser
from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Optional, Tuple
import urllib.parse

from hazelux.utils.paths import get_trash_dir

logger = logging.getLogger("hazelux.journal.trash")


def trash_file(path: Path) -> Tuple[bool, Optional[str]]:
    """Move file to FreeDesktop trash and resolve its unique trash URI.

    Returns:
        (success, trash_uri)
    """
    if not path.exists():
        logger.warning("Cannot trash nonexistent path: %s", path)
        return (False, None)

    canonical_source = str(path.resolve())
    t_pre = time.time()

    # 1. Execute gio trash <path>
    try:
        res = subprocess.run(
            ["gio", "trash", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            logger.error("gio trash failed on %s: %s", path, res.stderr.strip())
            return (False, None)
    except Exception as e:
        logger.error("Failed executing gio trash on %s: %s", path, e)
        return (False, None)

    # 2. Resolve matching trash URI from ~/.local/share/Trash/info/
    trash_dir = get_trash_dir()
    info_dir = trash_dir / "info"
    matched_uri: Optional[str] = None

    if info_dir.exists():
        try:
            for info_file in info_dir.glob("*.trashinfo"):
                try:
                    parser = configparser.ConfigParser(interpolation=None)
                    parser.read(info_file, encoding="utf-8")
                    if not parser.has_section("Trash Info"):
                        continue

                    raw_path = parser.get("Trash Info", "Path", fallback="")
                    decoded_path = urllib.parse.unquote(raw_path)
                    del_date_str = parser.get("Trash Info", "DeletionDate", fallback="")
                    if not del_date_str:
                        continue

                    del_dt = datetime.strptime(del_date_str, "%Y-%m-%dT%H:%M:%S")
                    del_timestamp = del_dt.timestamp()

                    # Match source path and within 2.0s of t_pre
                    if decoded_path == canonical_source and abs(del_timestamp - t_pre) <= 2.0:
                        file_stem = info_file.name[:-10]  # strip .trashinfo
                        matched_uri = f"trash:///{file_stem}"
                        break
                except Exception as ex:
                    logger.debug("Error reading %s: %s", info_file, ex)
        except Exception as e:
            logger.warning("Error scanning trash info directory: %s", e)

    return (True, matched_uri)


def restore_trashed_file(source_path: str, trash_uri: Optional[str] = None) -> bool:
    """Restore a previously trashed file back to its original location.

    Attempts gio trash --restore <uri> first, then falls back to .trashinfo parsing.
    """
    target = Path(source_path)

    # Strategy 1: Use gio trash --restore <trash_uri> if URI available
    if trash_uri:
        try:
            res = subprocess.run(
                ["gio", "trash", "--restore", trash_uri],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                logger.info("Successfully restored %s via gio trash --restore", trash_uri)
                return True
            else:
                logger.debug("gio trash --restore failed (%s): %s", trash_uri, res.stderr.strip())
        except Exception as e:
            logger.debug("gio trash --restore invocation error: %s", e)

    # Strategy 2: Heuristic fallback via ~/.local/share/Trash/
    trash_dir = get_trash_dir()
    info_dir = trash_dir / "info"
    files_dir = trash_dir / "files"

    if not info_dir.exists() or not files_dir.exists():
        logger.error("Trash directory not accessible for manual restore")
        return False

    candidate_info: Optional[Path] = None
    for info_file in info_dir.glob("*.trashinfo"):
        try:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(info_file, encoding="utf-8")
            if not parser.has_section("Trash Info"):
                continue

            raw_path = parser.get("Trash Info", "Path", fallback="")
            decoded_path = urllib.parse.unquote(raw_path)
            if decoded_path == source_path:
                candidate_info = info_file
                break
        except Exception:
            continue

    if candidate_info:
        file_basename = candidate_info.name[:-10]
        trashed_payload = files_dir / file_basename
        if trashed_payload.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(trashed_payload), str(target))
                candidate_info.unlink(missing_ok=True)
                logger.info("Successfully restored %s via fallback trash files move", source_path)
                return True
            except Exception as e:
                logger.error("Failed moving %s to %s: %s", trashed_payload, target, e)
                return False

    logger.warning("Cannot restore: original trash entry not found for %s", source_path)
    return False
