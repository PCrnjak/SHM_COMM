"""
Lock-free ring buffer operations for shm_comm.

This module contains the hot-path read/write functions called many
thousands of times per second.  No Python-level locks are used here;
correctness relies on the fact that numpy ``int64`` element reads and
writes are single machine instructions on 64-bit platforms, making them
effectively atomic.

Layout recap (see core.py for the full header description):
    Head pointer  — written only by the *producer* (publisher/pusher).
    Tail pointer  — written only by the *consumer* for SPSC patterns.
                    For PUSH/PULL (MPMC) the caller is responsible for
                    serialising tail updates via sync.FileLock.
    Slot format   — [ payload_size : uint32 (4 bytes) ]
                    [ payload      : bytes (slot_size - 4 bytes) ]
"""

import struct
import logging
import numpy as np
from multiprocessing import shared_memory

from .core import (
    HEADER_SIZE,
    SLOT_PREFIX_SIZE,
    IDX_HEAD,
    IDX_TAIL,
    IDX_MSG_COUNT,
    IDX_DROP_COUNT,
    IDX_NUM_SLOTS,
    IDX_SLOT_SIZE,
    get_header,
)
from .exceptions import SHMBufferFullError, SHMSerializationError

logger = logging.getLogger("shmcomm.buffer")

_SIZE_STRUCT = struct.Struct("<I")  # little-endian unsigned 32-bit int


# ── Low-level slot I/O ────────────────────────────────────────────────────────

def _slot_offset(slot_index: int, slot_size: int) -> int:
    """Return the byte offset of *slot_index* within the shared memory."""
    return HEADER_SIZE + slot_index * slot_size


def _write_slot(
    shm: shared_memory.SharedMemory,
    slot_index: int,
    slot_size: int,
    payload: bytes,
) -> None:
    """Write *payload* into a single slot.  Does NOT advance any pointer."""
    offset = _slot_offset(slot_index, slot_size)
    _SIZE_STRUCT.pack_into(shm.buf, offset, len(payload))
    end = offset + SLOT_PREFIX_SIZE + len(payload)
    shm.buf[offset + SLOT_PREFIX_SIZE : end] = payload


def _read_slot(
    shm: shared_memory.SharedMemory,
    slot_index: int,
    slot_size: int,
) -> bytes:
    """Read and return the payload stored in *slot_index*."""
    offset = _slot_offset(slot_index, slot_size)
    (payload_size,) = _SIZE_STRUCT.unpack_from(shm.buf, offset)
    start = offset + SLOT_PREFIX_SIZE
    return bytes(shm.buf[start : start + payload_size])


# ── Producer (write) side ─────────────────────────────────────────────────────

def write_message(
    shm: shared_memory.SharedMemory,
    payload: bytes,
    *,
    block: bool = False,
    timeout: float | None = None,
    overwrite: bool = False,
) -> bool:
    """Write *payload* bytes into the ring buffer.

    This is the SPSC producer path. Only one writer at a time may call
    this function on the same *shm* segment.

    Algorithm:
        1. Read current head (our write cursor).
        2. Compute next_head = (head + 1) % num_slots.
        3. If next_head == shared_tail the buffer is *full*:
           - ``overwrite=True``  (PUB/SUB): just write anyway. Slow
             subscribers will silently skip the overwritten slot.
           - ``overwrite=False`` (PUSH/PULL): respect *block*/*timeout*.
        4. Write payload into slot[head].
        5. Advance head to next_head — this is the *commit* step.

    Args:
        shm:       Open shared memory segment.
        payload:   Raw bytes to write (max ``slot_size - 4`` bytes).
        block:     If ``True``, spin until space is available or
                   *timeout* expires (ignored when *overwrite* is True).
        timeout:   Seconds to wait when *block* is ``True``.
        overwrite: If ``True``, write regardless of the shared tail
                   pointer (PUB/SUB semantics — latest data always wins).
                   If ``False`` (default), respect the shared tail
                   (PUSH/PULL semantics — no message may be lost).

    Returns:
        ``True`` on success, ``False`` if buffer is full and
        *block* is ``False`` and *overwrite* is ``False``.

    Raises:
        SHMBufferFullError: If *block* is ``True`` and the buffer is
            still full after *timeout*.
        ValueError: If *payload* is larger than the slot can hold.

    Example::

        ok = write_message(shm, b"hello world", overwrite=True)
    """
    import time

    hdr = get_header(shm)
    num_slots = int(hdr[IDX_NUM_SLOTS])
    slot_size = int(hdr[IDX_SLOT_SIZE])
    max_payload = slot_size - SLOT_PREFIX_SIZE

    if len(payload) > max_payload:
        raise ValueError(
            f"Payload size {len(payload)} exceeds slot capacity {max_payload}. "
            f"Increase slot_size when creating the channel."
        )

    if not overwrite:
        # PUSH/PULL path: respect the shared tail, block/drop if full.
        deadline = (time.monotonic() + timeout) if (block and timeout is not None) else None

        while True:
            head = int(hdr[IDX_HEAD])
            tail = int(hdr[IDX_TAIL])
            next_head = (head + 1) % num_slots

            if next_head != tail:
                break  # slot is free

            if not block:
                hdr[IDX_DROP_COUNT] += 1
                return False

            if deadline is not None and time.monotonic() >= deadline:
                raise SHMBufferFullError(
                    f"Ring buffer full for segment '{shm.name}' after "
                    f"{timeout:.3f}s; could not write message."
                )
            time.sleep(0.000_050)  # 50 µs

    head = int(hdr[IDX_HEAD])
    next_head = (head + 1) % num_slots

    _write_slot(shm, head, slot_size, payload)

    # Commit: advance head AFTER writing data.
    hdr[IDX_HEAD] = np.int64(next_head)
    hdr[IDX_MSG_COUNT] += 1

    logger.debug(
        "Wrote %d bytes to slot %d (head→%d)", len(payload), head, next_head
    )
    return True


# ── Consumer (read) side ──────────────────────────────────────────────────────

def read_message_spsc(
    shm: shared_memory.SharedMemory,
    local_tail: int,
) -> tuple[bytes, int] | None:
    """Non-blocking read for a single-consumer scenario (PUB/SUB).

    The consumer maintains its own *local_tail* rather than writing to
    shared memory, so there is zero coordination overhead.

    Args:
        shm:        Open shared memory segment.
        local_tail: The caller's private read cursor.

    Returns:
        ``(payload_bytes, new_tail)`` if a message was available, or
        ``None`` if the buffer is empty.

    Example::

        tail = 0
        result = read_message_spsc(shm, tail)
        if result:
            data, tail = result
    """
    hdr = get_header(shm)
    head = int(hdr[IDX_HEAD])
    num_slots = int(hdr[IDX_NUM_SLOTS])
    slot_size = int(hdr[IDX_SLOT_SIZE])

    if local_tail == head:
        return None  # empty

    payload = _read_slot(shm, local_tail, slot_size)
    new_tail = (local_tail + 1) % num_slots

    logger.debug(
        "Read %d bytes from slot %d (tail→%d)",
        len(payload),
        local_tail,
        new_tail,
    )
    return payload, new_tail


def read_message_shared_tail(
    shm: shared_memory.SharedMemory,
) -> bytes | None:
    """Non-blocking read for the multi-consumer scenario (PUSH/PULL).

    The tail pointer in shared memory is used.  The caller is
    responsible for holding a :class:`~shm_comm.sync.FileLock` around
    this call to prevent two consumers from claiming the same slot.

    Args:
        shm: Open shared memory segment.

    Returns:
        Payload bytes if a message was claimed, or ``None`` if empty.

    Example::

        with FileLock("push_workers"):
            data = read_message_shared_tail(shm)
    """
    hdr = get_header(shm)
    head = int(hdr[IDX_HEAD])
    tail = int(hdr[IDX_TAIL])
    num_slots = int(hdr[IDX_NUM_SLOTS])
    slot_size = int(hdr[IDX_SLOT_SIZE])

    if tail == head:
        return None  # empty

    payload = _read_slot(shm, tail, slot_size)
    hdr[IDX_TAIL] = np.int64((tail + 1) % num_slots)

    logger.debug("Claimed slot %d via shared tail", tail)
    return payload


# ── Stats helper ──────────────────────────────────────────────────────────────

def get_stats(shm: shared_memory.SharedMemory) -> dict:
    """Return a snapshot of the ring buffer statistics.

    Returns a dict with keys:
    ``head``, ``tail``, ``num_slots``, ``slot_size``,
    ``msg_count``, ``drop_count``, ``used_slots``, ``free_slots``.

    Example::

        stats = get_stats(shm)
        print(f"Used: {stats['used_slots']} / {stats['num_slots']}")
    """
    hdr = get_header(shm)
    head = int(hdr[IDX_HEAD])
    tail = int(hdr[IDX_TAIL])
    num_slots = int(hdr[IDX_NUM_SLOTS])
    used = (head - tail) % num_slots

    return {
        "head": head,
        "tail": tail,
        "num_slots": num_slots,
        "slot_size": int(hdr[IDX_SLOT_SIZE]),
        "msg_count": int(hdr[IDX_MSG_COUNT]),
        "drop_count": int(hdr[IDX_DROP_COUNT]),
        "used_slots": used,
        "free_slots": num_slots - used - 1,
    }
