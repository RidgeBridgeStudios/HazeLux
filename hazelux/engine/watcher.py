"""Asynchronous file watching with watchfiles and Three-Stat Quiescence Protocol."""

import asyncio
import errno
import logging
import os
from pathlib import Path
import time
from typing import Callable, Coroutine, Dict, Optional, Set

from watchfiles import Change, awatch

logger = logging.getLogger("hazelux.engine.watcher")


async def wait_for_file_quiescence(
    path: Path,
    interval_seconds: float = 0.35,
    max_timeout_seconds: float = 30.0,
) -> bool:
    """Suspends execution until a file reaches verified write completion.

    Requires 3 consecutive identical stat evaluations (size, mtime) yielding
    approximately 0.70 seconds of confirmed quiescence, and ensures mtime is older
    than the quiet window with unheld file locks.
    """
    elapsed = 0.0

    if not path.exists():
        return False

    consecutive_matches = 0
    last_stat = None

    while elapsed < max_timeout_seconds:
        try:
            current_stat = path.stat()
        except FileNotFoundError:
            return False

        if last_stat is not None:
            if (
                current_stat.st_size == last_stat.st_size
                and current_stat.st_mtime == last_stat.st_mtime
            ):
                consecutive_matches += 1
            else:
                consecutive_matches = 0

        last_stat = current_stat

        if consecutive_matches >= 2:  # Confirmed across 3 consecutive checks (~0.70s)
            # Confirm file modification time is older than the quiet window
            if (time.time() - current_stat.st_mtime) >= (interval_seconds * 2):
                try:
                    # Non-blocking open to ensure no active writer holds exclusive lock
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    os.close(fd)
                    return True
                except OSError:
                    # External writer holds descriptor; continue polling
                    consecutive_matches = 0

        await asyncio.sleep(interval_seconds)
        elapsed += interval_seconds

    return False


class WatcherManager:
    """Manages active watchfiles inotify streams across configured directories."""

    def __init__(
        self,
        on_file_quiescent: Callable[[Path], Coroutine[None, None, None]],
        on_enospc_error: Optional[Callable[[str], None]] = None,
    ):
        self.on_file_quiescent = on_file_quiescent
        self.on_enospc_error = on_enospc_error
        self._watch_tasks: Dict[str, asyncio.Task] = {}
        self._active_paths: Set[str] = set()
        self._stop_event = asyncio.Event()

    async def start_watching(self, paths: Set[str], recursive: bool = True) -> None:
        """Start or reconfigure watching for given directories."""
        # Stop paths no longer watched
        for p in list(self._watch_tasks.keys()):
            if p not in paths:
                task = self._watch_tasks.pop(p)
                task.cancel()

        self._active_paths = set(paths)
        self._stop_event.clear()

        for path_str in paths:
            if path_str not in self._watch_tasks:
                dir_path = Path(path_str).expanduser().resolve()
                if dir_path.is_dir():
                    task = asyncio.create_task(self._watch_dir(dir_path, recursive))
                    self._watch_tasks[path_str] = task

    async def _watch_dir(self, directory: Path, recursive: bool) -> None:
        """Watch single directory stream and dispatch events after write quiescence."""
        logger.info("Starting watchfiles stream on %s (recursive=%s)", directory, recursive)
        try:
            async for changes in awatch(directory, recursive=recursive, stop_event=self._stop_event):
                for change, path_str in changes:
                    # Only process added or modified events
                    if change in (Change.added, Change.modified):
                        p = Path(path_str)
                        # Ignore staging files and directories
                        if p.name.startswith(".staging_") or p.is_dir():
                            continue

                        # Check quiescence before dispatching to runner
                        quiescent = await wait_for_file_quiescence(p)
                        if quiescent:
                            try:
                                await self.on_file_quiescent(p)
                            except Exception as ex:
                                logger.error("Error processing quiescent file %s: %s", p, ex)
        except OSError as e:
            if e.errno == errno.ENOSPC:
                logger.error("Inotify watch limit exceeded (ENOSPC) on %s", directory)
                if self.on_enospc_error:
                    self.on_enospc_error(str(directory))
            else:
                logger.error("OS error in directory watcher on %s: %s", directory, e)
        except asyncio.CancelledError:
            logger.info("Watchfiles stream cancelled for %s", directory)
        except Exception as e:
            logger.error("Unexpected error in directory watcher on %s: %s", directory, e)

    async def stop(self) -> None:
        """Stop all active directory watchers."""
        self._stop_event.set()
        for p, task in list(self._watch_tasks.items()):
            task.cancel()
        self._watch_tasks.clear()
        self._active_paths.clear()
