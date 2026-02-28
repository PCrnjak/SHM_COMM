"""
Cross-process file-based lock for shm_comm.

This module provides a lightweight, cross-platform advisory lock
built on OS file locking (``fcntl`` on POSIX, ``msvcrt`` on Windows).
It is used by the PUSH/PULL pattern where multiple consumers compete
for the shared tail pointer.

No external dependencies are required.
"""

import os
import sys
import time
import tempfile
import logging
from contextlib import contextmanager
from .exceptions import SHMTimeoutError

logger = logging.getLogger("shmcomm.sync")

_IS_WINDOWS = sys.platform == "win32"

# Acquire fcntl / msvcrt lazily so the module still imports on any
# platform even if the alternative branch is never executed.
if not _IS_WINDOWS:
    import fcntl
else:
    import msvcrt


def _lock_dir() -> str:
    """Return a writable directory for lock files."""
    return tempfile.gettempdir()


def _lock_path(name: str) -> str:
    """Return the absolute path of the lock file for *name*."""
    safe = name.replace("/", "_").replace("\\", "_")
    return os.path.join(_lock_dir(), f"shmcomm_{safe}.lock")


class FileLock:
    """Cross-process advisory lock backed by an OS lock file.

    Usage::

        lock = FileLock("push_channel")
        with lock:
            # only one process at a time executes this block
            tail = read_tail(shm)
            claim(shm, tail)
            write_tail(shm, tail + 1)

    Args:
        name:    A unique name identifying this lock (same as the
                 channel name it protects).
        timeout: Default acquire timeout in seconds. ``None`` keeps
                 spinning indefinitely.
    """

    def __init__(self, name: str, timeout: float | None = None):
        self._path = _lock_path(name)
        self._timeout = timeout
        self._fd: int | None = None
        # Ensure the lock file exists.
        open(self._path, "a").close()

    # ------------------------------------------------------------------
    # Low-level acquire / release
    # ------------------------------------------------------------------

    def acquire(self, timeout: float | None = None) -> None:
        """Acquire the lock, blocking until *timeout* seconds have passed.

        Args:
            timeout: Seconds to wait. Falls back to the constructor
                     default. ``None`` = wait forever.

        Raises:
            SHMTimeoutError: If the lock could not be acquired in time.
        """
        deadline = None
        if timeout is None:
            timeout = self._timeout
        if timeout is not None:
            deadline = time.monotonic() + timeout

        self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT)

        while True:
            try:
                if _IS_WINDOWS:
                    msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return  # acquired
            except (OSError, IOError):
                pass  # already locked by another process

            if deadline is not None and time.monotonic() >= deadline:
                os.close(self._fd)
                self._fd = None
                raise SHMTimeoutError(
                    f"Could not acquire lock '{self._path}' within "
                    f"{timeout:.3f}s"
                )
            time.sleep(0.000_050)  # 50 µs spin-wait

    def release(self) -> None:
        """Release the lock."""
        if self._fd is None:
            return
        try:
            if _IS_WINDOWS:
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *_) -> None:
        self.release()


@contextmanager
def named_lock(name: str, timeout: float | None = None):
    """Convenience context manager that creates and acquires a
    :class:`FileLock` around a block.

    Example::

        with named_lock("push_workers", timeout=1.0):
            tail = atomic_claim_tail(shm)
    """
    lock = FileLock(name, timeout=timeout)
    lock.acquire(timeout=timeout)
    try:
        yield lock
    finally:
        lock.release()
