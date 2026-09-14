"""System inotify watch capacity inspection and calculation."""

import os
from pathlib import Path
from typing import Tuple


def get_max_user_watches() -> int:
    """Read max_user_watches from procfs. Defaults to 524288 if unreadable."""
    proc_path = Path("/proc/sys/fs/inotify/max_user_watches")
    try:
        if proc_path.exists():
            content = proc_path.read_text().strip()
            return int(content)
    except Exception:
        pass
    return 524288


def estimate_directory_watches(path: Path, recursive: bool = True) -> int:
    """Estimate number of inotify directory watches needed for a path."""
    if not path.is_dir():
        return 1
    if not recursive:
        return 1

    count = 0
    try:
        for root, dirs, _ in os.walk(path, followlinks=False):
            count += 1
    except OSError:
        count += 1
    return max(1, count)


def check_inotify_watch_limit(total_directories_to_watch: int) -> Tuple[bool, float, int]:
    """Check if total projected watches exceed 80% of max_user_watches.

    Returns:
        (is_warning, current_ratio, max_watches)
    """
    max_watches = get_max_user_watches()
    if max_watches <= 0:
        return (False, 0.0, max_watches)

    ratio = total_directories_to_watch / max_watches
    is_warning = ratio >= 0.80
    return (is_warning, ratio, max_watches)
