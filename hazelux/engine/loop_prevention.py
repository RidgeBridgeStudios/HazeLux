"""Loop prevention, cooldown caching, and cascading threshold protection."""

from collections import defaultdict, deque
import logging
from pathlib import Path
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("hazelux.engine.loop_prevention")


class CooldownCache:
    """Thread-safe cache suppressing path and inode events for a 10.0-second TTL."""

    def __init__(self, default_ttl: float = 10.0):
        self.default_ttl = default_ttl
        self._path_cache: Dict[str, float] = {}  # canonical path -> expiry timestamp
        self._inode_cache: Dict[int, float] = {}  # inode -> expiry timestamp
        self._lock = threading.Lock()

    def add(self, path: Path, inode: Optional[int] = None, ttl: Optional[float] = None) -> None:
        """Register path and inode in cooldown cache."""
        expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
        canonical = str(path.resolve())

        with self._lock:
            self._path_cache[canonical] = expiry
            if inode is not None:
                self._inode_cache[inode] = expiry

    def is_suppressed(self, path: Path, inode: Optional[int] = None) -> bool:
        """Check whether path or inode is currently suppressed."""
        now = time.time()
        canonical = str(path.resolve())

        with self._lock:
            # Check path
            if canonical in self._path_cache:
                if self._path_cache[canonical] > now:
                    return True
                else:
                    del self._path_cache[canonical]

            # Check inode
            if inode is not None and inode in self._inode_cache:
                if self._inode_cache[inode] > now:
                    return True
                else:
                    del self._inode_cache[inode]

        return False

    def prune(self) -> None:
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            self._path_cache = {p: exp for p, exp in self._path_cache.items() if exp > now}
            self._inode_cache = {ino: exp for ino, exp in self._inode_cache.items() if exp > now}


class DestinationEventSuppression:
    """Suppresses events for destination paths for 15.0 seconds when moved into monitored dirs."""

    def __init__(self, default_ttl: float = 15.0):
        self.default_ttl = default_ttl
        self._cache: Dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, path: Path, ttl: Optional[float] = None) -> None:
        """Register path in destination suppression cache."""
        expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
        canonical = str(path.resolve())
        with self._lock:
            self._cache[canonical] = expiry

    def is_suppressed(self, path: Path) -> bool:
        """Check if destination path is currently suppressed."""
        now = time.time()
        canonical = str(path.resolve())
        with self._lock:
            if canonical in self._cache:
                if self._cache[canonical] > now:
                    return True
                else:
                    del self._cache[canonical]
        return False

    def prune(self) -> None:
        now = time.time()
        with self._lock:
            self._cache = {p: exp for p, exp in self._cache.items() if exp > now}


class CascadingLoopTracker:
    """Sliding-window tracker to prevent runaway cascaded operations.

    If an inode triggers > 5 actions within 60 seconds, automation for that
    inode is suspended and flagged as a Loop Suspect.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        max_actions: int = 5,
        on_loop_detected: Optional[Callable[[int, Path], None]] = None,
    ):
        self.window_seconds = window_seconds
        self.max_actions = max_actions
        self.on_loop_detected = on_loop_detected
        self._history: Dict[int, Deque[float]] = defaultdict(deque)
        self._suspended_inodes: Set[int] = set()
        self._lock = threading.Lock()

    def record_action(self, inode: int, path: Path) -> bool:
        """Record an action for an inode.

        Returns True if the operation is allowed, False if suspended as a Loop Suspect.
        """
        now = time.time()
        with self._lock:
            if inode in self._suspended_inodes:
                logger.warning("Action blocked: inode %d (%s) is suspended as a Loop Suspect.", inode, path)
                return False

            dq = self._history[inode]
            # Expire timestamps older than sliding window
            while dq and dq[0] <= now - self.window_seconds:
                dq.popleft()

            dq.append(now)

            if len(dq) > self.max_actions:
                self._suspended_inodes.add(inode)
                logger.error(
                    "Cascading loop detected for inode %d (%s): %d actions in %.1fs. Suspending automation.",
                    inode,
                    path,
                    len(dq),
                    self.window_seconds,
                )
                if self.on_loop_detected:
                    try:
                        self.on_loop_detected(inode, path)
                    except Exception as ex:
                        logger.error("Error in on_loop_detected callback: %s", ex)
                return False

            return True

    def is_suspended(self, inode: int) -> bool:
        with self._lock:
            return inode in self._suspended_inodes

    def reset_inode(self, inode: int) -> None:
        with self._lock:
            self._suspended_inodes.discard(inode)
            if inode in self._history:
                del self._history[inode]
