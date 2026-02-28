"""
Miscellaneous utilities for shm_comm.
"""

import os
import sys
import time
import logging
from multiprocessing import shared_memory

logger = logging.getLogger("shmcomm.utils")


# ── Platform detection ────────────────────────────────────────────────────────

def platform_name() -> str:
    """Return a short string describing the current OS."""
    if sys.platform == "linux":
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return sys.platform


def is_linux() -> bool:
    return sys.platform == "linux"


def is_windows() -> bool:
    return sys.platform == "win32"


# ── SHM name helpers ──────────────────────────────────────────────────────────

def pub_segment_name(channel: str) -> str:
    """Return the SHM segment name used for a PUB/SUB channel."""
    return f"shmcomm_pub_{channel}"


def req_segment_name(channel: str) -> str:
    """Return the SHM segment name used for REQ (client→server) traffic."""
    return f"shmcomm_req_{channel}"


def rep_segment_name(channel: str) -> str:
    """Return the SHM segment name used for REP (server→client) traffic."""
    return f"shmcomm_rep_{channel}"


def push_segment_name(channel: str) -> str:
    """Return the SHM segment name used for PUSH/PULL distribution."""
    return f"shmcomm_push_{channel}"


# ── Polling helpers ───────────────────────────────────────────────────────────

def poll_until(
    check_fn,
    timeout: float | None,
    poll_interval: float = 0.000_100,
):
    """Spin-call *check_fn()* until it returns a truthy value or
    *timeout* expires.

    Args:
        check_fn:      Callable returning the result or ``None``/falsy.
        timeout:       Seconds. ``None`` = block indefinitely.
        poll_interval: Sleep time between retries (seconds).

    Returns:
        The first truthy value returned by *check_fn*, or ``None`` on timeout.
    """
    deadline = (time.monotonic() + timeout) if timeout is not None else None

    while True:
        result = check_fn()
        if result is not None and result is not False:
            return result

        if deadline is not None and time.monotonic() >= deadline:
            return None

        time.sleep(poll_interval)


# ── Cleanup helpers ───────────────────────────────────────────────────────────

def force_unlink(name: str) -> bool:
    """Forcibly destroy a shared memory segment by name if it exists.

    Useful for cleaning up after crashes during development.

    Args:
        name: The OS-level segment name (e.g. ``"shmcomm_pub_sensors"``).

    Returns:
        ``True`` if the segment existed and was destroyed,
        ``False`` if it was not found.

    Example::

        force_unlink("shmcomm_pub_sensors")
    """
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
        shm.close()
        shm.unlink()
        logger.info("Force-unlinked segment '%s'", name)
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.warning("Could not unlink '%s': %s", name, exc)
        return False


def list_segments() -> list[str]:
    """List all shm_comm shared memory segments visible on this system.

    Only works on Linux (reads ``/dev/shm``). Returns an empty list
    on other platforms.

    Returns:
        List of segment names (without the /dev/shm/ prefix) that
        match the ``shmcomm_`` prefix.
    """
    if not is_linux():
        logger.debug("list_segments() is only supported on Linux.")
        return []
    try:
        return [
            entry
            for entry in os.listdir("/dev/shm")
            if entry.startswith("shmcomm_")
        ]
    except Exception as exc:
        logger.warning("Could not list /dev/shm: %s", exc)
        return []
