"""
Tests for shm_comm Replier / Requester.
"""

import time
import multiprocessing as mp
import pytest

from shm_comm import Replier, Requester, force_unlink
from shm_comm.exceptions import SHMConnectionError, SHMTimeoutError
from shm_comm.utils import req_segment_name, rep_segment_name

_SVC = "test_reqrep_svc"


@pytest.fixture(autouse=True)
def cleanup():
    force_unlink(req_segment_name(_SVC))
    force_unlink(rep_segment_name(_SVC))
    yield
    force_unlink(req_segment_name(_SVC))
    force_unlink(rep_segment_name(_SVC))


# ── In-process tests ──────────────────────────────────────────────────────────

def test_basic_request_reply():
    with Replier(_SVC) as rep, Requester(_SVC) as req:
        req.send({"query": "ping"})
        request = rep.recv(timeout=1.0)
        assert request == {"query": "ping"}

        rep.send({"reply": "pong"})
        reply = req.recv(timeout=1.0)
        assert reply == {"reply": "pong"}


def test_requester_convenience_method():
    with Replier(_SVC) as rep, Requester(_SVC) as req:
        # Run server in a thread so request() can block
        import threading

        def serve():
            r = rep.recv(timeout=2.0)
            rep.send({"echo": r})

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        result = req.request({"data": 42}, timeout=2.0)
        t.join(timeout=3.0)
        assert result == {"echo": {"data": 42}}


def test_request_timeout_raises():
    with Replier(_SVC) as rep, Requester(_SVC) as req:
        req.send("hello")
        # Nobody replies — should time out
        with pytest.raises(SHMTimeoutError):
            req.request({"never_answered": True}, timeout=0.1)


def test_requester_connect_before_replier_raises():
    force_unlink(req_segment_name(_SVC))
    force_unlink(rep_segment_name(_SVC))
    with pytest.raises(SHMConnectionError):
        Requester(_SVC, timeout_connect=0.1)


def test_multiple_exchanges():
    """Multiple sequential request-reply cycles on the same connection."""
    with Replier(_SVC) as rep, Requester(_SVC) as req:
        for i in range(5):
            req.send(i)
            request = rep.recv(timeout=1.0)
            assert request == i
            rep.send(i * 2)
            reply = req.recv(timeout=1.0)
            assert reply == i * 2


def test_bytes_round_trip():
    """Raw bytes path: send_bytes / recv_bytes skip serialization entirely."""
    with Replier(_SVC) as rep, Requester(_SVC) as req:
        req.send_bytes(b"raw_request")
        raw_req = rep.recv_bytes(timeout=1.0)
        assert raw_req == b"raw_request"

        rep.send_bytes(b"raw_reply")
        raw_reply = req.recv_bytes(timeout=1.0)
        assert raw_reply == b"raw_reply"


# ── Multi-process helpers (module level for Windows spawn) ────────────────────

def _replier_worker(svc, ready_event, count):
    from shm_comm import Replier
    with Replier(svc) as rep:
        ready_event.set()
        for _ in range(count):
            req = rep.recv(timeout=5.0)
            rep.send({"echo": req})


def _requester_worker(svc, result_queue, messages):
    from shm_comm import Requester
    with Requester(svc, timeout_connect=5.0) as req:
        results = []
        for msg in messages:
            req.send(msg)
            reply = req.recv(timeout=5.0)
            results.append(reply)
        result_queue.put(results)


@pytest.mark.multiprocess
def test_cross_process_reqrep():
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    result_q = ctx.Queue()
    messages = [{"n": i} for i in range(3)]

    rep_p = ctx.Process(
        target=_replier_worker, args=(_SVC, ready, len(messages)), daemon=True
    )
    rep_p.start()
    ready.wait(timeout=5.0)

    req_p = ctx.Process(
        target=_requester_worker, args=(_SVC, result_q, messages), daemon=True
    )
    req_p.start()
    req_p.join(timeout=15.0)
    rep_p.join(timeout=5.0)

    assert not req_p.is_alive(), "Requester process timed out"
    results = result_q.get(timeout=2.0)
    assert results == [{"echo": m} for m in messages]
