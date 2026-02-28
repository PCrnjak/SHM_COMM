"""
Tests for shm_comm Publisher / Subscriber.

Multiprocessing tests use function names defined at module scope so
they work with both fork (Linux/macOS) and spawn (Windows).
"""

import time
import multiprocessing as mp
import pytest

from shm_comm import Publisher, Subscriber, force_unlink
from shm_comm.exceptions import SHMConnectionError, SHMBufferFullError

_CH = "test_pubsub_ch"


@pytest.fixture(autouse=True)
def cleanup():
    from shm_comm.utils import pub_segment_name
    force_unlink(pub_segment_name(_CH))
    yield
    force_unlink(pub_segment_name(_CH))


# ── In-process tests ──────────────────────────────────────────────────────────

def test_send_recv_basic():
    with Publisher(_CH) as pub:
        with Subscriber(_CH) as sub:
            pub.send({"value": 42})
            msg = sub.recv(timeout=1.0)
            assert msg == {"value": 42}


def test_recv_timeout_returns_none():
    with Publisher(_CH) as pub:
        with Subscriber(_CH) as sub:
            result = sub.recv(timeout=0.1)
            assert result is None


def test_multiple_messages_in_order():
    with Publisher(_CH, num_slots=32) as pub:
        with Subscriber(_CH) as sub:
            for i in range(10):
                pub.send(i)
            received = []
            for _ in range(10):
                msg = sub.recv(timeout=1.0)
                assert msg is not None
                received.append(msg)
            assert received == list(range(10))


def test_subscriber_misses_old_messages():
    """A subscriber that connects after messages were published should
    start from the current head (miss historical messages)."""
    with Publisher(_CH) as pub:
        pub.send("old_message_1")
        pub.send("old_message_2")
        # Subscribe AFTER publishing
        with Subscriber(_CH) as sub:
            pub.send("new_message")
            msg = sub.recv(timeout=1.0)
            # Should only see the new message
            assert msg == "new_message"


def test_send_bytes_recv():
    with Publisher(_CH) as pub:
        with Subscriber(_CH) as sub:
            pub.send_bytes(b"\x01\x02\x03")
            raw = sub.recv_bytes(timeout=1.0)
            assert raw == b"\x01\x02\x03"


def test_stats_returned():
    with Publisher(_CH) as pub:
        pub.send("x")
        stats = pub.stats()
        assert stats["msg_count"] == 1
        assert "free_slots" in stats


def test_multiple_subscribers():
    """Two independent subscribers both receive the same messages."""
    with Publisher(_CH, num_slots=32) as pub:
        with Subscriber(_CH) as sub1, Subscriber(_CH) as sub2:
            pub.send("broadcast")
            m1 = sub1.recv(timeout=1.0)
            m2 = sub2.recv(timeout=1.0)
            assert m1 == "broadcast"
            assert m2 == "broadcast"


def test_subscriber_connect_before_publisher_raises():
    from shm_comm.utils import pub_segment_name
    force_unlink(pub_segment_name(_CH))
    with pytest.raises(SHMConnectionError):
        Subscriber(_CH, timeout_connect=0.1)


def test_large_message():
    """Messages close to the slot size should round-trip correctly."""
    big = {"data": "x" * 3000}
    with Publisher(_CH, slot_size=4096) as pub:
        with Subscriber(_CH) as sub:
            pub.send(big)
            msg = sub.recv(timeout=1.0)
            assert msg == big


def test_context_manager_cleans_up():
    """Publisher context manager should destroy the segment on exit."""
    with Publisher(_CH) as pub:
        pass  # pub.close() called here
    # Subscriber should now fail to connect immediately
    with pytest.raises(SHMConnectionError):
        Subscriber(_CH, timeout_connect=0.1)


# ── Multi-process test helpers (must be at module level for Windows spawn) ────

def _pub_worker(channel, messages, ready_event):
    from shm_comm import Publisher
    with Publisher(channel) as pub:
        ready_event.set()
        for msg in messages:
            pub.send(msg)
            time.sleep(0.001)


def _sub_worker(channel, result_queue, count):
    from shm_comm import Subscriber
    with Subscriber(channel, timeout_connect=5.0) as sub:
        received = []
        deadline = time.monotonic() + 5.0
        while len(received) < count and time.monotonic() < deadline:
            msg = sub.recv(timeout=0.1)
            if msg is not None:
                received.append(msg)
        result_queue.put(received)


@pytest.mark.multiprocess
def test_cross_process_pubsub():
    """Basic cross-process publish/subscribe."""
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    result_q = ctx.Queue()

    messages = [{"i": i} for i in range(5)]

    pub_p = ctx.Process(
        target=_pub_worker, args=(_CH, messages, ready), daemon=True
    )
    pub_p.start()
    ready.wait(timeout=5.0)

    sub_p = ctx.Process(
        target=_sub_worker, args=(_CH, result_q, len(messages)), daemon=True
    )
    sub_p.start()
    sub_p.join(timeout=10.0)
    pub_p.join(timeout=5.0)

    assert not sub_p.is_alive(), "Subscriber process timed out"
    received = result_q.get(timeout=2.0)
    assert len(received) == len(messages)
    assert received == messages
