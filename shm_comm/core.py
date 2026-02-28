"""
Shared memory segment lifecycle management for shm_comm.

This module owns the low-level create / attach / destroy operations
for named shared memory segments and defines the binary header layout
that all ring buffers share.

Header layout (128 bytes, little-endian int64 values):
    Index  Offset  Field
    0      0       MAGIC  -- 0x53484D434F4D4D31  ("SHMCOMM1")
    1      8       VERSION
    2      16      HEAD   -- next write slot (updated only by writer)
    3      24      TAIL   -- next read slot  (push/pull shared tail)
    4      32      MSG_COUNT
    5      40      DROP_COUNT
    6      48      NUM_SLOTS
    7      56      SLOT_SIZE
    8-15   64-127  RESERVED (zeros)

Data area starts at byte offset 128.
Each slot: first 4 bytes = payload size (little-endian uint32),
           remaining bytes = payload.
"""

import struct
import logging
import numpy as np
from multiprocessing import shared_memory
from .exceptions import SHMConnectionError

logger = logging.getLogger("shmcomm.core")

# ── Constants ────────────────────────────────────────────────────────────────

MAGIC: int = 0x53484D434F4D4D31  # b"SHMCOMM1" as little-endian int64
VERSION: int = 1
HEADER_SIZE: int = 128  # bytes

# Header field indices in the int64 array
_IDX_MAGIC = 0
_IDX_VERSION = 1
_IDX_HEAD = 2
_IDX_TAIL = 3
_IDX_MSG_COUNT = 4
_IDX_DROP_COUNT = 5
_IDX_NUM_SLOTS = 6
_IDX_SLOT_SIZE = 7

# Each ring-buffer slot begins with a uint32 size prefix.
SLOT_PREFIX_SIZE: int = 4   # bytes for the size prefix


# ── Segment size helper ───────────────────────────────────────────────────────

def segment_size(num_slots: int, slot_size: int) -> int:
    """Return the total shared memory size in bytes for the given geometry.

    Args:
        num_slots: Number of ring-buffer slots.
        slot_size: Bytes per slot (including the 4-byte size prefix).

    Returns:
        Total size in bytes.
    """
    return HEADER_SIZE + num_slots * slot_size


# ── Header helpers ────────────────────────────────────────────────────────────

def _make_header_array(shm: shared_memory.SharedMemory) -> np.ndarray:
    """Return a numpy int64 view of the 128-byte header region.

    The array has 16 elements; only indices 0-7 are currently used.
    Reads and writes to individual int64 elements are atomic on all
    64-bit platforms (single-instruction store/load).
    """
    return np.ndarray((16,), dtype="<i8", buffer=shm.buf, offset=0)


def _init_header(
    shm: shared_memory.SharedMemory,
    num_slots: int,
    slot_size: int,
) -> None:
    """Write the initial header into a freshly created segment."""
    hdr = _make_header_array(shm)
    hdr[_IDX_MAGIC] = MAGIC
    hdr[_IDX_VERSION] = VERSION
    hdr[_IDX_HEAD] = 0
    hdr[_IDX_TAIL] = 0
    hdr[_IDX_MSG_COUNT] = 0
    hdr[_IDX_DROP_COUNT] = 0
    hdr[_IDX_NUM_SLOTS] = num_slots
    hdr[_IDX_SLOT_SIZE] = slot_size
    logger.debug(
        "Header initialised: num_slots=%d slot_size=%d total=%d",
        num_slots,
        slot_size,
        HEADER_SIZE + num_slots * slot_size,
    )


def _validate_header(shm: shared_memory.SharedMemory) -> None:
    """Raise :class:`~shm_comm.exceptions.SHMConnectionError` if the
    header does not look like a valid shm_comm segment."""
    hdr = _make_header_array(shm)
    if hdr[_IDX_MAGIC] != MAGIC:
        raise SHMConnectionError(
            f"Shared memory '{shm.name}' has invalid magic "
            f"0x{hdr[_IDX_MAGIC]:016X} (expected 0x{MAGIC:016X}). "
            "Are you connecting to the right segment?"
        )
    if hdr[_IDX_VERSION] != VERSION:
        raise SHMConnectionError(
            f"Shared memory '{shm.name}' has version "
            f"{hdr[_IDX_VERSION]} but this library expects version "
            f"{VERSION}."
        )


# ── Public API ────────────────────────────────────────────────────────────────

def create_segment(
    name: str,
    num_slots: int,
    slot_size: int,
) -> shared_memory.SharedMemory:
    """Create a new named shared memory segment and initialise its header.

    If a segment with *name* already exists (e.g. after a crash) it is
    unlinked first so a fresh segment is always returned.

    Args:
        name:      OS-level name for the shared memory object.
        num_slots: Number of ring-buffer slots.
        slot_size: Bytes per slot (payload + 4-byte size prefix).

    Returns:
        An open :class:`multiprocessing.shared_memory.SharedMemory`
        instance.  The caller owns it and must call
        :func:`close_segment` when done.

    Raises:
        SHMConnectionError: If the OS refuses to allocate the segment.

    Example::

        shm = create_segment("shmcomm_pub_sensors", num_slots=64, slot_size=4096)
    """
    size = segment_size(num_slots, slot_size)

    # Attempt to destroy a stale segment first so we always start clean.
    try:
        stale = shared_memory.SharedMemory(name=name, create=False)
        stale.close()
        stale.unlink()
        logger.debug("Removed stale shared memory segment '%s'", name)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("Could not clean stale segment '%s': %s", name, exc)

    try:
        shm = shared_memory.SharedMemory(name=name, create=True, size=size)
    except Exception as exc:
        raise SHMConnectionError(
            f"Failed to create shared memory '{name}' "
            f"({size} bytes): {exc}"
        ) from exc

    _init_header(shm, num_slots, slot_size)
    logger.info("Created shared memory segment '%s' (%d bytes)", name, size)
    return shm


def attach_segment(
    name: str,
    timeout: float = 5.0,
    poll_interval: float = 0.005,
) -> shared_memory.SharedMemory:
    """Attach to an existing named shared memory segment.

    Polls until the segment exists and its header is valid or *timeout*
    seconds have elapsed — useful when the publisher starts slightly
    after the subscriber.

    Args:
        name:          OS-level name of the segment to attach to.
        timeout:       Seconds to wait for the segment to appear.
        poll_interval: Seconds between retries.

    Returns:
        An open :class:`multiprocessing.shared_memory.SharedMemory`
        instance.

    Raises:
        SHMConnectionError: If the segment does not appear in time or
            its header is invalid.

    Example::

        shm = attach_segment("shmcomm_pub_sensors", timeout=5.0)
    """
    import time

    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None

    while time.monotonic() < deadline:
        try:
            shm = shared_memory.SharedMemory(name=name, create=False)
            _validate_header(shm)
            logger.info("Attached to shared memory segment '%s'", name)
            return shm
        except FileNotFoundError as exc:
            last_exc = exc
        except SHMConnectionError:
            raise
        except Exception as exc:
            last_exc = exc

        import time as _t
        _t.sleep(poll_interval)

    raise SHMConnectionError(
        f"Shared memory segment '{name}' did not appear within "
        f"{timeout:.1f}s. Is the publisher/server running? "
        f"(Last error: {last_exc})"
    )


def close_segment(
    shm: shared_memory.SharedMemory,
    *,
    destroy: bool = False,
) -> None:
    """Close (and optionally destroy) a shared memory segment.

    Args:
        shm:     The segment returned by :func:`create_segment` or
                 :func:`attach_segment`.
        destroy: If ``True``, unlink the OS-level object so it is
                 removed once all processes have closed it.
                 Only the creating process should pass ``destroy=True``.

    Example::

        close_segment(shm, destroy=True)   # publisher tear-down
        close_segment(shm)                  # subscriber tear-down
    """
    try:
        shm.close()
        if destroy:
            shm.unlink()
            logger.info("Destroyed shared memory segment '%s'", shm.name)
        else:
            logger.debug("Closed shared memory segment '%s'", shm.name)
    except Exception as exc:
        logger.warning("Error closing segment '%s': %s", shm.name, exc)


# ── Convenience accessors used by buffer.py ──────────────────────────────────

def get_header(shm: shared_memory.SharedMemory) -> np.ndarray:
    """Return the live numpy int64 view of the header.

    Callers may read/write individual fields directly::

        hdr = get_header(shm)
        head = int(hdr[2])   # _IDX_HEAD
    """
    return _make_header_array(shm)


# Re-export header indices so other modules don't need to know the magic
# numbers.
IDX_HEAD = _IDX_HEAD
IDX_TAIL = _IDX_TAIL
IDX_MSG_COUNT = _IDX_MSG_COUNT
IDX_DROP_COUNT = _IDX_DROP_COUNT
IDX_NUM_SLOTS = _IDX_NUM_SLOTS
IDX_SLOT_SIZE = _IDX_SLOT_SIZE
