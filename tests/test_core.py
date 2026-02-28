"""
Tests for shm_comm.core — shared memory lifecycle.
"""

import pytest
from multiprocessing import shared_memory

from shm_comm.core import (
    create_segment,
    attach_segment,
    close_segment,
    get_header,
    segment_size,
    MAGIC,
    VERSION,
    HEADER_SIZE,
    IDX_HEAD,
    IDX_NUM_SLOTS,
    IDX_SLOT_SIZE,
)
from shm_comm.exceptions import SHMConnectionError


# ── Helpers ───────────────────────────────────────────────────────────────────

_SEG = "shmcomm_test_core_seg"
_NUM_SLOTS = 8
_SLOT_SIZE = 128


@pytest.fixture(autouse=True)
def cleanup():
    """Remove the test segment before and after each test."""
    from shm_comm.utils import force_unlink
    force_unlink(_SEG)
    yield
    force_unlink(_SEG)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_segment_size():
    size = segment_size(_NUM_SLOTS, _SLOT_SIZE)
    assert size == HEADER_SIZE + _NUM_SLOTS * _SLOT_SIZE


def test_create_and_header():
    shm = create_segment(_SEG, _NUM_SLOTS, _SLOT_SIZE)
    try:
        hdr = get_header(shm)
        assert hdr[0] == MAGIC
        assert hdr[1] == VERSION
        assert int(hdr[IDX_HEAD]) == 0
        assert int(hdr[IDX_NUM_SLOTS]) == _NUM_SLOTS
        assert int(hdr[IDX_SLOT_SIZE]) == _SLOT_SIZE
    finally:
        close_segment(shm, destroy=True)


def test_attach_after_create():
    shm_creator = create_segment(_SEG, _NUM_SLOTS, _SLOT_SIZE)
    try:
        shm_client = attach_segment(_SEG, timeout=1.0)
        try:
            assert shm_client.name == _SEG
        finally:
            close_segment(shm_client, destroy=False)
    finally:
        close_segment(shm_creator, destroy=True)


def test_attach_nonexistent_raises():
    from shm_comm.utils import force_unlink
    force_unlink("shmcomm_test_nonexistent")
    with pytest.raises(SHMConnectionError):
        attach_segment("shmcomm_test_nonexistent", timeout=0.1)


def test_create_overwrites_stale():
    # Create once
    shm1 = create_segment(_SEG, _NUM_SLOTS, _SLOT_SIZE)
    close_segment(shm1)  # close but do NOT destroy
    # Create again — should silently remove the stale segment
    shm2 = create_segment(_SEG, _NUM_SLOTS, _SLOT_SIZE)
    close_segment(shm2, destroy=True)


def test_destroy_removes_segment():
    shm = create_segment(_SEG, _NUM_SLOTS, _SLOT_SIZE)
    close_segment(shm, destroy=True)
    with pytest.raises(SHMConnectionError):
        attach_segment(_SEG, timeout=0.1)


def test_header_writes_are_visible_across_instances():
    """Check that writing via one handle is visible via another."""
    shm_w = create_segment(_SEG, _NUM_SLOTS, _SLOT_SIZE)
    shm_r = attach_segment(_SEG, timeout=1.0)
    try:
        hdr_w = get_header(shm_w)
        hdr_w[IDX_HEAD] = 5   # simulate advancing head
        hdr_r = get_header(shm_r)
        assert int(hdr_r[IDX_HEAD]) == 5
    finally:
        close_segment(shm_r)
        close_segment(shm_w, destroy=True)
