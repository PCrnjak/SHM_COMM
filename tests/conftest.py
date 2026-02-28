"""
Shared test fixtures and helpers for shm_comm tests.
"""

import pytest
import time
import multiprocessing as mp


def wait_for(fn, timeout=5.0, interval=0.01):
    """Poll fn() until it returns truthy or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return None


def run_in_process(fn, *args, timeout=10.0):
    """Run *fn* in a child process; return (exitcode, exception_str).

    Returns exitcode=0 on success.
    """
    p = mp.Process(target=fn, args=args, daemon=True)
    p.start()
    p.join(timeout=timeout)
    if p.is_alive():
        p.terminate()
        p.join(1)
        return -1, "timeout"
    return p.exitcode, None
