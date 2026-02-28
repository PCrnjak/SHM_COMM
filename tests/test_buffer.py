"""
Tests for shm_comm.buffer — ring buffer read/write logic.
"""

import pytest
from shm_comm.core import create_segment, close_segment
from shm_comm.buffer import (
    write_message,
    read_message_spsc,
    read_message_shared_tail,
    get_stats,
)
from shm_comm.exceptions import SHMBufferFullError


_SEG = "shmcomm_test_buf"
_NUM_SLOTS = 8
_SLOT_SIZE = 128
_MAX_PAYLOAD = _SLOT_SIZE - 4


@pytest.fixture()
def shm():
    s = create_segment(_SEG, _NUM_SLOTS, _SLOT_SIZE)
    yield s
    close_segment(s, destroy=True)


# ── write_message ─────────────────────────────────────────────────────────────

def test_write_returns_true(shm):
    assert write_message(shm, b"hello") is True


def test_write_increments_msg_count(shm):
    write_message(shm, b"a")
    write_message(shm, b"b")
    stats = get_stats(shm)
    assert stats["msg_count"] == 2


def test_write_advances_head(shm):
    write_message(shm, b"data")
    stats = get_stats(shm)
    assert stats["head"] == 1


def test_write_oversized_raises(shm):
    big = b"x" * (_MAX_PAYLOAD + 1)
    with pytest.raises(ValueError):
        write_message(shm, big)


def test_buffer_full_non_blocking(shm):
    # Fill all slots (num_slots - 1 messages fit; last slot is sentinel)
    for i in range(_NUM_SLOTS - 1):
        ok = write_message(shm, b"fill")
    # Buffer is now full; next write should return False
    ok = write_message(shm, b"overflow", block=False)
    assert ok is False
    stats = get_stats(shm)
    assert stats["drop_count"] == 1


def test_buffer_full_blocking_timeout(shm):
    for _ in range(_NUM_SLOTS - 1):
        write_message(shm, b"fill")
    with pytest.raises(SHMBufferFullError):
        write_message(shm, b"overflow", block=True, timeout=0.05)


# ── read_message_spsc ─────────────────────────────────────────────────────────

def test_read_returns_none_when_empty(shm):
    assert read_message_spsc(shm, 0) is None


def test_round_trip_spsc(shm):
    payload = b"test payload 123"
    write_message(shm, payload)
    result = read_message_spsc(shm, 0)
    assert result is not None
    data, new_tail = result
    assert data == payload
    assert new_tail == 1


def test_multiple_messages_spsc(shm):
    messages = [f"msg{i}".encode() for i in range(5)]
    for m in messages:
        write_message(shm, m)

    tail = 0
    received = []
    for _ in range(5):
        result = read_message_spsc(shm, tail)
        assert result is not None
        data, tail = result
        received.append(data)

    assert received == messages


def test_spsc_wrap_around(shm):
    """Verify messages wrap around the ring correctly (overwrite=True).

    In PUB/SUB mode the publisher uses overwrite=True so the shared-tail
    check is bypassed and the ring truly wraps.
    """
    tail = 0
    for cycle in range(3):
        msgs = [f"cycle{cycle}_msg{i}".encode() for i in range(4)]
        for m in msgs:
            write_message(shm, m, overwrite=True)
        for expected in msgs:
            result = read_message_spsc(shm, tail)
            assert result is not None, f"No message at cycle={cycle} expected={expected}"
            payload, tail = result
            assert payload == expected


# ── read_message_shared_tail ──────────────────────────────────────────────────

def test_shared_tail_read(shm):
    write_message(shm, b"shared_tail_data")
    payload = read_message_shared_tail(shm)
    assert payload == b"shared_tail_data"


def test_shared_tail_empty(shm):
    assert read_message_shared_tail(shm) is None


# ── get_stats ─────────────────────────────────────────────────────────────────

def test_stats_structure(shm):
    stats = get_stats(shm)
    keys = {"head", "tail", "num_slots", "slot_size", "msg_count",
            "drop_count", "used_slots", "free_slots"}
    assert keys.issubset(stats.keys())


def test_stats_free_slots(shm):
    stats = get_stats(shm)
    # Empty buffer: free_slots = num_slots - 1  (one slot reserved as sentinel)
    assert stats["free_slots"] == _NUM_SLOTS - 1
    write_message(shm, b"one")
    stats2 = get_stats(shm)
    assert stats2["free_slots"] == _NUM_SLOTS - 2
