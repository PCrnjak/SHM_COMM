"""
Tests for shm_comm Pusher / Puller (pipeline pattern).
"""

import time
import multiprocessing as mp
import pytest

from shm_comm import Pusher, Puller, force_unlink
from shm_comm.utils import push_segment_name
from shm_comm.exceptions import SHMConnectionError

_CH = "test_pipeline_ch"


@pytest.fixture(autouse=True)
def cleanup():
    force_unlink(push_segment_name(_CH))
    yield
    force_unlink(push_segment_name(_CH))


# ── In-process tests ──────────────────────────────────────────────────────────

def test_basic_push_pull():
    with Pusher(_CH) as push, Puller(_CH) as pull:
        push.send({"job": 1})
        result = pull.recv(timeout=1.0)
        assert result == {"job": 1}


def test_pull_timeout_returns_none():
    with Pusher(_CH) as push, Puller(_CH) as pull:
        result = pull.recv(timeout=0.1)
        assert result is None


def test_multiple_messages():
    with Pusher(_CH) as push, Puller(_CH) as pull:
        for i in range(5):
            push.send(i)
        received = []
        for _ in range(5):
            r = pull.recv(timeout=1.0)
            assert r is not None
            received.append(r)
        assert received == list(range(5))


def test_two_pullers_share_work():
    """With two Pullers, each message should be delivered once."""
    with Pusher(_CH) as push:
        with Puller(_CH) as p1, Puller(_CH) as p2:
            for i in range(6):
                push.send(i)
            received = []
            for _ in range(6):
                # Alternate between both pullers
                r = p1.recv(timeout=0.5) if len(received) % 2 == 0 else p2.recv(timeout=0.5)
                if r is None:
                    # Try the other puller
                    r = p2.recv(timeout=0.5) if len(received) % 2 == 0 else p1.recv(timeout=0.5)
                assert r is not None
                received.append(r)
    assert sorted(received) == list(range(6))


def test_push_raw_bytes():
    with Pusher(_CH) as push, Puller(_CH) as pull:
        push.send_bytes(b"raw_bytes_test")
        raw = pull.recv_bytes(timeout=1.0)
        assert raw == b"raw_bytes_test"


def test_puller_before_pusher_raises():
    force_unlink(push_segment_name(_CH))
    with pytest.raises(SHMConnectionError):
        Puller(_CH, timeout_connect=0.1)


def test_stats():
    with Pusher(_CH) as push:
        push.send("x")
        s = push.stats()
        assert s["msg_count"] == 1


# ── Multi-process helpers ─────────────────────────────────────────────────────

def _pusher_worker(channel, jobs, ready_event):
    from shm_comm import Pusher
    with Pusher(channel) as push:
        ready_event.set()
        for j in jobs:
            push.send(j)
            time.sleep(0.002)


def _puller_worker(channel, result_queue, count):
    from shm_comm import Puller
    with Puller(channel, timeout_connect=5.0) as pull:
        results = []
        deadline = time.monotonic() + 8.0
        while len(results) < count and time.monotonic() < deadline:
            r = pull.recv(timeout=0.2)
            if r is not None:
                results.append(r)
        result_queue.put(results)


@pytest.mark.multiprocess
def test_cross_process_pipeline():
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    q1 = ctx.Queue()
    q2 = ctx.Queue()
    jobs = list(range(10))

    push_p = ctx.Process(
        target=_pusher_worker, args=(_CH, jobs, ready), daemon=True
    )
    push_p.start()
    ready.wait(timeout=5.0)

    pull_p1 = ctx.Process(
        target=_puller_worker, args=(_CH, q1, 5), daemon=True
    )
    pull_p2 = ctx.Process(
        target=_puller_worker, args=(_CH, q2, 5), daemon=True
    )
    pull_p1.start()
    pull_p2.start()

    pull_p1.join(timeout=10.0)
    pull_p2.join(timeout=10.0)
    push_p.join(timeout=5.0)

    r1 = q1.get(timeout=2.0)
    r2 = q2.get(timeout=2.0)

    combined = sorted(r1 + r2)
    # Each job delivered to exactly one puller
    assert combined == list(range(10)), f"Got: {combined}"
